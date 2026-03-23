from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from hi_sweetheart.actions import (
    execute_action,
    load_pending,
    approve_action,
    reject_action,
)
from hi_sweetheart.classifier import classify, Classification, ClassifyAPIError
from hi_sweetheart.config import ConfigError, load_config
from hi_sweetheart.fetcher import extract_urls, fetch_content, has_actionable_content
from hi_sweetheart.notify import RunSummary, send_notification, setup_logging
from hi_sweetheart.reader import IMESSAGE_DB_PATH, read_messages
from hi_sweetheart.state import State

logger = logging.getLogger("hi-sweetheart")

DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent / "config.json"
DEFAULT_STATE_PATH = Path.home() / ".hi-sweetheart" / "state.json"


async def run_pipeline(
    config_path: Path = DEFAULT_CONFIG_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    db_path: Path = IMESSAGE_DB_PATH,
    mode_override: str | None = None,
):
    config = load_config(config_path)
    if mode_override:
        config.mode = mode_override

    log = setup_logging(config.log_path)
    log.info("=== hi-sweetheart run started ===")

    state = State(state_path)
    summary = RunSummary()

    api_key = os.environ.get(config.api_key_env, "")
    if not api_key:
        log.error(f"API key not found in env var: {config.api_key_env}")
        send_notification("hi-sweetheart", f"ERROR: {config.api_key_env} not set")
        return

    first_run = not state_path.exists()

    try:
        messages = read_messages(
            db_path, sender=config.sender,
            after_rowid=state.last_message_rowid,
            first_run=first_run,
        )
    except Exception as e:
        log.error(f"Failed to read iMessage DB: {e}")
        summary.add_error(f"DB read failed: {e}")
        send_notification("hi-sweetheart", summary.format())
        return

    log.info(f"Found {len(messages)} new messages")

    if not messages:
        send_notification("hi-sweetheart", summary.format())
        return

    for msg in messages:
        log.info(f"Processing message {msg.rowid}: {msg.text[:80]}...")
        try:
            urls = extract_urls(msg.text)

            if not urls and not has_actionable_content(msg.text):
                log.info(f"Message {msg.rowid}: no URLs or actionable content, skipping")
                state.update(msg.rowid)
                state.save()
                continue

            if urls:
                for url in urls:
                    log.info(f"Fetching: {url}")
                    fetch_result = await fetch_content(url)

                    if not fetch_result.success:
                        # Per spec: fetch failure -> create note with raw URL
                        log.warning(f"Fetch failed for {url}: {fetch_result.error}")
                        note = Classification(
                            type="note", confidence=0.0,
                            summary=f"Failed to fetch: {url}",
                            action_detail={"content": f"URL fetch failed ({fetch_result.error}): {url}"},
                        )
                        execute_action(note, config)
                        summary.add_error(f"Fetch failed: {url}")
                        continue

                    log.info(f"Classifying content from {url}")
                    classification = await classify(
                        message_text=msg.text,
                        fetched_content=fetch_result.text,
                        url=url,
                        api_key=api_key,
                    )
                    log.info(f"Classified as: {classification.type} ({classification.confidence})")

                    result = execute_action(classification, config)
                    summary.add(classification.type, result)
            else:
                # Actionable text content without URL
                log.info("Classifying text content directly")
                classification = await classify(
                    message_text=msg.text,
                    fetched_content=msg.text,
                    url="(no url)",
                    api_key=api_key,
                )
                result = execute_action(classification, config)
                summary.add(classification.type, result)

            state.update(msg.rowid)
            state.save()

        except ClassifyAPIError as e:
            # API failed after retries — abort run, don't advance ROWID
            log.error(f"Claude API exhausted retries at message {msg.rowid}: {e}")
            summary.add_error(f"API failure, aborting: {e}")
            break

        except Exception as e:
            # Action execution failures — advance ROWID, continue
            log.error(f"Failed to process message {msg.rowid}: {e}")
            summary.add_error(f"Message {msg.rowid}: {e}")
            state.update(msg.rowid)
            state.save()

    log.info("=== Run complete ===")
    notification_text = summary.format()
    log.info(notification_text)
    send_notification("hi-sweetheart", notification_text)


def cmd_run(args):
    asyncio.run(run_pipeline(
        config_path=Path(args.config),
        state_path=Path(args.state).expanduser(),
        mode_override=args.mode,
    ))


def cmd_pending(args):
    config = load_config(Path(args.config))
    pending = load_pending(config)
    if not pending:
        print("No pending actions.")
        return
    for p in pending:
        c = p["classification"]
        print(f"  [{p['id']}] {c['type']} — {c['summary']} (confidence: {c['confidence']})")


def cmd_approve(args):
    config = load_config(Path(args.config))
    approve_action(args.id, config)
    print(f"Approved and executed: {args.id}")


def cmd_reject(args):
    config = load_config(Path(args.config))
    reject_action(args.id, config)
    print(f"Rejected: {args.id}")


def cmd_log(args):
    config = load_config(Path(args.config))
    if not config.log_path.exists():
        print("No log file found.")
        return
    lines = config.log_path.read_text().splitlines()
    for line in lines[-50:]:
        print(line)


def main():
    parser = argparse.ArgumentParser(prog="hi-sweetheart", description="iMessage reader + Claude action agent")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config.json")
    parser.add_argument("--state", default=str(DEFAULT_STATE_PATH), help="Path to state.json")

    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Execute one pipeline run")
    run_parser.add_argument("--mode", choices=["auto", "tiered", "propose"], help="Override execution mode")
    run_parser.set_defaults(func=cmd_run)

    pending_parser = subparsers.add_parser("pending", help="List pending actions")
    pending_parser.set_defaults(func=cmd_pending)

    approve_parser = subparsers.add_parser("approve", help="Approve a pending action")
    approve_parser.add_argument("id", help="Action ID to approve")
    approve_parser.set_defaults(func=cmd_approve)

    reject_parser = subparsers.add_parser("reject", help="Reject a pending action")
    reject_parser.add_argument("id", help="Action ID to reject")
    reject_parser.set_defaults(func=cmd_reject)

    log_parser = subparsers.add_parser("log", help="Show recent run history")
    log_parser.set_defaults(func=cmd_log)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        args.func(args)
    except ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

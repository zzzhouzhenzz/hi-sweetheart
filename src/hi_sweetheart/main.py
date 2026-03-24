from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from hi_sweetheart.actions import action_podcast
from hi_sweetheart.classifier import classify, Classification, ClassifyAPIError
from hi_sweetheart.config import ConfigError, load_config
from hi_sweetheart.fetcher import extract_urls, fetch_content
from hi_sweetheart.items import add_item, make_item
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
    dry_run: bool = False,
):
    config = load_config(config_path)
    if mode_override:
        config.mode = mode_override

    log = setup_logging(config.log_path)
    if dry_run:
        log.info("=== hi-sweetheart DRY RUN started (no side effects) ===")
    else:
        log.info("=== hi-sweetheart run started ===")

    state = State(state_path)
    summary = RunSummary()
    items_path = config.items_path

    first_run = state.last_message_rowid == 0

    try:
        messages = read_messages(
            db_path, sender=config.sender,
            after_rowid=state.last_message_rowid,
            first_run=first_run,
        )
    except Exception as e:
        log.error(f"Failed to read iMessage DB: {e}")
        summary.add_error(f"DB read failed: {e}")
        if not dry_run:
            send_notification("hi-sweetheart", summary.format())
        return

    log.info(f"Found {len(messages)} new messages")

    if not messages:
        if not dry_run:
            send_notification("hi-sweetheart", summary.format())
        return

    max_rowid = messages[0].rowid
    api_failed = False

    for msg in messages:
        log.info(f"Processing message {msg.rowid}: {msg.text[:80]}...")
        try:
            urls = extract_urls(msg.text)

            if not urls:
                log.info(f"Message {msg.rowid}: no URLs, skipping")
                continue

            for url in urls:
                if "podcasts.apple.com" in url:
                    log.info(f"Podcast URL detected: {url}")
                    if not dry_run:
                        action_podcast(
                            Classification(
                                type="podcast", confidence=1.0,
                                summary=f"Apple Podcast",
                                action_detail={"podcast_url": url, "podcast_name": "(from iMessage)"},
                            ),
                            config,
                        )
                        item = make_item("podcast", "Podcast Episode", url, "Saved to Apple Podcasts")
                        add_item(items_path, item)
                    else:
                        log.info(f"[DRY RUN] Would save podcast: {url}")
                    summary.add("podcast", f"Podcast: {url}")
                    continue

                log.info(f"Fetching: {url}")
                fetch_result = await fetch_content(url, message_text=msg.text)

                if not fetch_result.success:
                    log.warning(f"Fetch failed for {url}: {fetch_result.error}")
                    if not dry_run:
                        item = make_item("note", "Fetch failed", url, fetch_result.error)
                        add_item(items_path, item)
                    summary.add_error(f"Fetch failed: {url}")
                    continue

                log.info(f"Classifying content from {url}")
                classification = await classify(
                    message_text=msg.text,
                    fetched_content=fetch_result.text,
                    url=url,
                )
                log.info(f"Classified as: {classification.type} ({classification.confidence})")

                if classification.type == "ignore":
                    summary.add("ignore", f"Ignored: {url}")
                    continue

                title = _extract_title(classification)
                if not dry_run:
                    item = make_item(classification.type, title, url, classification.summary)
                    add_item(items_path, item)
                else:
                    log.info(f"[DRY RUN] Would add: {classification.type} — {title}")
                summary.add(classification.type, f"{title}: {url}")

        except ClassifyAPIError as e:
            log.error(f"Claude API exhausted retries at message {msg.rowid}: {e}")
            summary.add_error(f"API failure, aborting: {e}")
            api_failed = True
            break

        except Exception as e:
            log.error(f"Failed to process message {msg.rowid}: {e}")
            summary.add_error(f"Message {msg.rowid}: {e}")
            if not dry_run:
                item = make_item("note", "Processing failed", "", str(e))
                add_item(items_path, item)

    if not dry_run and not api_failed:
        state.update(max_rowid)
        state.save()

    log.info("=== Run complete ===")
    notification_text = summary.format()
    log.info(notification_text)
    if not dry_run:
        send_notification("hi-sweetheart", notification_text)


def _extract_title(classification: Classification) -> str:
    d = classification.action_detail
    if classification.type == "bookmark":
        return d.get("title", classification.summary)
    if classification.type == "podcast":
        return d.get("podcast_name", "Podcast")
    if classification.type == "plugin_install":
        return d.get("plugin_name", classification.summary)
    if classification.type == "marketplace_install":
        return d.get("marketplace_name", classification.summary)
    return classification.summary


def cmd_run(args):
    asyncio.run(run_pipeline(
        config_path=Path(args.config),
        state_path=Path(args.state).expanduser(),
        mode_override=args.mode,
        dry_run=args.dry_run,
    ))


def cmd_reset(args):
    state_path = Path(args.state).expanduser()
    if state_path.exists():
        state_path.unlink()
        print(f"Deleted {state_path}")
    else:
        print("No state file to reset.")
    print("Next run will start fresh (last 3 days of messages).")


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
    run_parser.add_argument("--dry-run", action="store_true", help="Run full pipeline with zero side effects (no writes, no state advance, no notifications)")
    run_parser.set_defaults(func=cmd_run)

    reset_parser = subparsers.add_parser("reset", help="Clear state and start fresh on next run")
    reset_parser.set_defaults(func=cmd_reset)

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

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from hi_sweetheart.classifier import Classification
from hi_sweetheart.config import Config

logger = logging.getLogger("hi-sweetheart")

SAFE_ACTIONS = {"podcast", "note", "ignore"}


def execute_action(classification: Classification, config: Config) -> str:
    """Execute or queue an action based on mode. Returns description of what was done."""
    if classification.type == "ignore":
        return "Ignored"

    return _run_action(classification, config)


def _run_action(classification: Classification, config: Config) -> str:
    handlers = {
        "note": action_note,
        "podcast": action_podcast,
    }
    handler = handlers.get(classification.type)
    if not handler:
        logger.warning(f"No handler for action type: {classification.type}")
        return f"No handler for: {classification.type}"

    handler(classification, config)
    return f"Executed: {classification.summary}"


def action_note(classification: Classification, config: Config):
    path = config.notes_path
    path.parent.mkdir(parents=True, exist_ok=True)
    detail = classification.action_detail
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    entry = f"\n## {timestamp} — {classification.summary}\n\n{detail.get('content', '')}\n"
    if path.exists():
        existing = path.read_text()
        path.write_text(existing + entry)
    else:
        path.write_text(f"# Notes\n{entry}")
    logger.info(f"Noted: {classification.summary}")


def action_podcast(classification: Classification, config: Config):
    detail = classification.action_detail
    url = detail.get("podcast_url", "")
    if "podcasts.apple.com" in url:
        subscribe_url = url.replace("https://", "podcasts://")
    else:
        subscribe_url = url
    subprocess.run(["open", subscribe_url], capture_output=True, timeout=10)
    logger.info(f"Subscribed to podcast: {detail.get('podcast_name', 'unknown')}")

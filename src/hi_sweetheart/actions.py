from __future__ import annotations

import json
import logging
import subprocess
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from hi_sweetheart.classifier import Classification
from hi_sweetheart.config import Config

logger = logging.getLogger("hi-sweetheart")

SAFE_ACTIONS = {"bookmark", "podcast", "note", "ignore"}
RISKY_ACTIONS = {"plugin_install", "marketplace_install", "config_update"}


def execute_action(classification: Classification, config: Config) -> str:
    """Execute or queue an action based on mode. Returns description of what was done."""
    if classification.type == "ignore":
        return "Ignored"

    should_queue = False
    if config.mode == "propose":
        should_queue = True
    elif config.mode == "tiered" and classification.type in RISKY_ACTIONS:
        should_queue = True

    if should_queue:
        queue_pending(classification, config)
        return f"Queued for approval: {classification.summary}"

    return _run_action(classification, config)


def _run_action(classification: Classification, config: Config) -> str:
    handlers = {
        "bookmark": action_bookmark,
        "note": action_note,
        "podcast": action_podcast,
        "config_update": action_config_update,
        "plugin_install": action_plugin_install,
        "marketplace_install": action_marketplace_install,
    }
    handler = handlers.get(classification.type)
    if not handler:
        logger.warning(f"No handler for action type: {classification.type}")
        return f"No handler for: {classification.type}"

    handler(classification, config)
    return f"Executed: {classification.summary}"


def action_bookmark(classification: Classification, config: Config):
    path = config.reading_list_path
    path.parent.mkdir(parents=True, exist_ok=True)
    detail = classification.action_detail
    entry = f"\n## {detail.get('title', 'Untitled')}\n\n{detail.get('summary', '')}\n"
    if path.exists():
        existing = path.read_text()
        path.write_text(existing + entry)
    else:
        path.write_text(f"# Reading List\n{entry}")
    logger.info(f"Bookmarked: {detail.get('title', 'unknown')}")


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


SAVE_EPISODE_JXA = r"""
function findSaveButton(element, depth) {
    if (depth > 15) return null;
    try {
        var buttons = element.buttons();
        for (var i = 0; i < buttons.length; i++) {
            try {
                if (buttons[i].description() === "Save Episode") {
                    return buttons[i];
                }
            } catch(e) {}
        }
    } catch(e) {}
    try {
        var groups = element.groups();
        for (var i = 0; i < groups.length; i++) {
            var result = findSaveButton(groups[i], depth + 1);
            if (result) return result;
        }
    } catch(e) {}
    return null;
}

var podcasts = Application("System Events").processes["Podcasts"];
var win = podcasts.windows[0];
var btn = findSaveButton(win, 0);
if (!btn) {
    "not_found";
} else if (btn.value() === "On") {
    "already_saved";
} else {
    btn.click();
    "saved";
}
"""

PODCAST_OPEN_WAIT_SECS = 5


def action_podcast(classification: Classification, config: Config):
    """Save a podcast episode to Apple Podcasts library via UI automation.

    1. Opens the Apple Podcasts URL (navigates Podcasts.app to the episode).
    2. Waits for the page to load.
    3. Uses JXA (osascript) to find and click the "Save Episode" button.

    Saving through the app triggers iCloud sync across all Apple devices.
    """
    detail = classification.action_detail
    url = detail.get("podcast_url", "")
    name = detail.get("podcast_name", "Untitled Podcast")

    if not url or "podcasts.apple.com" not in url:
        logger.warning(f"Podcast URL not an Apple Podcasts link: {url}")
        return

    # Step 1: Open the episode in Podcasts.app
    result = subprocess.run(
        ["open", "-a", "Podcasts", url],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        logger.error(f"Failed to open Podcasts app: {result.stderr.strip()}")
        return

    # Step 2: Wait for the episode page to load
    time.sleep(PODCAST_OPEN_WAIT_SECS)

    # Step 3: Click "Save Episode" via JXA
    result = subprocess.run(
        ["osascript", "-l", "JavaScript", "-e", SAVE_EPISODE_JXA],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        logger.error(f"JXA save failed: {result.stderr.strip()}")
        return

    status = result.stdout.strip()
    if status == "saved":
        logger.info(f"Saved episode: {name} ({url})")
    elif status == "already_saved":
        logger.info(f"Episode already saved: {name} ({url})")
    elif status == "not_found":
        logger.error(f"Save Episode button not found — page may not have loaded: {url}")
    else:
        logger.warning(f"Unexpected JXA result for {name}: {status}")


def action_config_update(classification: Classification, config: Config):
    path = config.claude_settings_path
    if not path.exists():
        logger.error(f"Settings file not found: {path}")
        return

    backup = path.with_suffix(".json.bak")
    backup.write_text(path.read_text())
    logger.info(f"Backed up settings to {backup}")

    existing = json.loads(path.read_text())
    new_settings = classification.action_detail.get("settings", {})
    merged = _deep_merge(existing, new_settings)
    path.write_text(json.dumps(merged, indent=2) + "\n")
    logger.info(f"Updated settings: {list(new_settings.keys())}")


def action_plugin_install(classification: Classification, config: Config):
    detail = classification.action_detail
    steps = detail.get("install_steps", [])
    if not steps:
        logger.warning("No install steps provided for plugin install")
        return
    for step in steps:
        logger.info(f"Running install step: {step}")
        result = subprocess.run(
            step, shell=True, capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            logger.error(f"Install step failed: {step}\nstderr: {result.stderr}")
            raise RuntimeError(f"Install step failed: {step}")
        logger.info(f"Step output: {result.stdout.strip()}")
    logger.info(f"Installed plugin: {detail.get('plugin_name', 'unknown')}")


def action_marketplace_install(classification: Classification, config: Config):
    action_plugin_install(classification, config)


def _deep_merge(base: dict, override: dict) -> dict:
    result = deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        elif key in result and isinstance(result[key], list) and isinstance(value, list):
            result[key] = result[key] + value
        else:
            result[key] = value
    return result


# --- Pending actions queue ---

def queue_pending(classification: Classification, config: Config):
    pending = load_pending(config)
    entry = {
        "id": str(uuid.uuid4())[:8],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "classification": {
            "type": classification.type,
            "confidence": classification.confidence,
            "summary": classification.summary,
            "action_detail": classification.action_detail,
        },
    }
    pending.append(entry)
    _save_pending(pending, config)
    logger.info(f"Queued pending action: {entry['id']} ({classification.type})")


def load_pending(config: Config) -> list[dict]:
    path = config.pending_actions_path
    if not path.exists():
        return []
    return json.loads(path.read_text())


def approve_action(action_id: str, config: Config):
    pending = load_pending(config)
    action = None
    remaining = []
    for p in pending:
        if p["id"] == action_id:
            action = p
        else:
            remaining.append(p)

    if action is None:
        raise ValueError(f"Pending action not found: {action_id}")

    c = Classification(**action["classification"])
    original_mode = config.mode
    config.mode = "auto"
    try:
        _run_action(c, config)
    finally:
        config.mode = original_mode

    _save_pending(remaining, config)
    logger.info(f"Approved and executed action: {action_id}")


def reject_action(action_id: str, config: Config):
    pending = load_pending(config)
    remaining = [p for p in pending if p["id"] != action_id]
    if len(remaining) == len(pending):
        raise ValueError(f"Pending action not found: {action_id}")
    _save_pending(remaining, config)
    logger.info(f"Rejected action: {action_id}")


def _save_pending(pending: list[dict], config: Config):
    path = config.pending_actions_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pending, indent=2))

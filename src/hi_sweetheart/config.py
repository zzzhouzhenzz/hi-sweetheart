from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

VALID_MODES = ("auto", "tiered", "propose")
REQUIRED_FIELDS = ("sender", "mode", "log_path", "pending_actions_path")


class ConfigError(Exception):
    pass


DEFAULT_ITEMS_PATH = Path.home() / ".hi-sweetheart" / "items.md"


@dataclass
class Config:
    sender: str
    mode: str
    items_path: Path
    log_path: Path
    pending_actions_path: Path
    # Legacy fields kept for backward compat
    reading_list_path: Path = Path("/dev/null")
    notes_path: Path = Path("/dev/null")
    claude_settings_path: Path = Path("/dev/null")
    claude_plugins_path: Path = Path("/dev/null")


def load_config(path: Path) -> Config:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")

    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON in config: {e}") from e

    for field in REQUIRED_FIELDS:
        if field not in data:
            raise ConfigError(f"Missing required config field: {field}")

    if data["mode"] not in VALID_MODES:
        raise ConfigError(f"Invalid mode: {data['mode']}. Must be one of {VALID_MODES}")

    items_path = Path(data.get("items_path", str(DEFAULT_ITEMS_PATH))).expanduser()

    return Config(
        sender=data["sender"],
        mode=data["mode"],
        items_path=items_path,
        log_path=Path(data["log_path"]).expanduser(),
        pending_actions_path=Path(data["pending_actions_path"]).expanduser(),
    )

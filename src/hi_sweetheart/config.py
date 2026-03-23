from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

VALID_MODES = ("auto", "tiered", "propose")
REQUIRED_FIELDS = ("sender", "api_key_env", "mode", "reading_list_path",
                   "notes_path", "claude_settings_path", "claude_plugins_path",
                   "log_path", "pending_actions_path")


class ConfigError(Exception):
    pass


@dataclass
class Config:
    sender: str
    api_key_env: str
    mode: str
    reading_list_path: Path
    notes_path: Path
    claude_settings_path: Path
    claude_plugins_path: Path
    log_path: Path
    pending_actions_path: Path


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

    path_fields = ("reading_list_path", "notes_path", "claude_settings_path",
                   "claude_plugins_path", "log_path", "pending_actions_path")

    return Config(
        sender=data["sender"],
        api_key_env=data["api_key_env"],
        mode=data["mode"],
        **{f: Path(data[f]).expanduser() for f in path_fields},
    )

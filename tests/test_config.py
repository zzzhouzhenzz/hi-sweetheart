import json
import pytest
from pathlib import Path
from hi_sweetheart.config import load_config, ConfigError


def test_load_config_from_file(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "sender": "+15551234567",
        "api_key_env": "ANTHROPIC_API_KEY",
        "mode": "auto",
        "reading_list_path": "~/Downloads/reading-list.md",
        "notes_path": "~/.hi-sweetheart/notes.md",
        "claude_settings_path": "~/.claude/settings.json",
        "claude_plugins_path": "~/.claude/plugins",
        "log_path": "~/.hi-sweetheart/runs.log",
        "pending_actions_path": "~/.hi-sweetheart/pending.json",
    }))
    config = load_config(cfg_file)
    assert config.sender == "+15551234567"
    assert config.mode == "auto"
    assert "~" not in str(config.reading_list_path)
    assert isinstance(config.reading_list_path, Path)


def test_load_config_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.json")


def test_load_config_invalid_mode(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "sender": "+15551234567",
        "api_key_env": "ANTHROPIC_API_KEY",
        "mode": "yolo",
        "reading_list_path": "~/r.md",
        "notes_path": "~/n.md",
        "claude_settings_path": "~/.claude/settings.json",
        "claude_plugins_path": "~/.claude/plugins",
        "log_path": "~/log",
        "pending_actions_path": "~/pending.json",
    }))
    with pytest.raises(ConfigError, match="mode"):
        load_config(cfg_file)


def test_load_config_missing_required_field(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"mode": "auto"}))
    with pytest.raises(ConfigError, match="sender"):
        load_config(cfg_file)

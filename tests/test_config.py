import json
import pytest
from pathlib import Path
from hi_sweetheart.config import load_config, ConfigError


def _minimal_config():
    return {
        "sender": "+15551234567",
        "mode": "auto",
        "log_path": "~/.hi-sweetheart/runs.log",
        "pending_actions_path": "~/.hi-sweetheart/pending.json",
    }


def test_load_config_from_file(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(_minimal_config()))
    config = load_config(cfg_file)
    assert config.sender == "+15551234567"
    assert config.mode == "auto"
    assert str(config.items_path).endswith(".hi-sweetheart/items.md")
    assert isinstance(config.items_path, Path)


def test_load_config_custom_items_path(tmp_path):
    data = _minimal_config()
    data["items_path"] = "~/custom/items.md"
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(data))
    config = load_config(cfg_file)
    assert str(config.items_path).endswith("custom/items.md")
    assert "~" not in str(config.items_path)


def test_load_config_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.json")


def test_load_config_invalid_mode(tmp_path):
    data = _minimal_config()
    data["mode"] = "yolo"
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(data))
    with pytest.raises(ConfigError, match="mode"):
        load_config(cfg_file)


def test_load_config_missing_required_field(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"mode": "auto"}))
    with pytest.raises(ConfigError, match="sender"):
        load_config(cfg_file)

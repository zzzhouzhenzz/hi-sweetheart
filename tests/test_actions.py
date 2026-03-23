import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from hi_sweetheart.actions import (
    execute_action,
    action_note,
    action_podcast,
)
from hi_sweetheart.classifier import Classification
from hi_sweetheart.config import Config


def _make_config(tmp_path) -> Config:
    return Config(
        sender="+15551234567",
        mode="auto",
        reading_list_path=tmp_path / "reading-list.md",
        notes_path=tmp_path / "notes.md",
        claude_settings_path=tmp_path / "settings.json",
        claude_plugins_path=tmp_path / "plugins",
        log_path=tmp_path / "runs.log",
        pending_actions_path=tmp_path / "pending.json",
    )


# --- Action handlers ---

def test_action_note(tmp_path):
    config = _make_config(tmp_path)
    c = Classification(
        type="note", confidence=0.8, summary="Remember this",
        action_detail={"content": "Set up hooks for better workflow"},
    )
    action_note(c, config)
    content = config.notes_path.read_text()
    assert "Set up hooks" in content


def test_action_note_appends(tmp_path):
    config = _make_config(tmp_path)
    config.notes_path.parent.mkdir(parents=True, exist_ok=True)
    config.notes_path.write_text("# Notes\n\n- existing\n")
    c = Classification(
        type="note", confidence=0.8, summary="New note",
        action_detail={"content": "New content"},
    )
    action_note(c, config)
    content = config.notes_path.read_text()
    assert "existing" in content
    assert "New content" in content


@patch("hi_sweetheart.actions.subprocess")
def test_action_podcast(mock_subprocess, tmp_path):
    config = _make_config(tmp_path)
    c = Classification(
        type="podcast", confidence=0.95, summary="AI podcast",
        action_detail={"podcast_url": "https://podcasts.apple.com/us/podcast/id123", "podcast_name": "AI Show"},
    )
    action_podcast(c, config)
    mock_subprocess.run.assert_called_once()
    cmd = mock_subprocess.run.call_args[0][0]
    assert "open" in cmd
    assert "podcasts://" in cmd[1]


# --- Execute action dispatch ---

def test_execute_action_note(tmp_path):
    config = _make_config(tmp_path)
    c = Classification(
        type="note", confidence=0.9, summary="A tip",
        action_detail={"content": "Use claude -p for automation"},
    )
    result = execute_action(c, config)
    assert "Executed" in result
    assert config.notes_path.exists()


def test_execute_action_ignore_skips(tmp_path):
    config = _make_config(tmp_path)
    c = Classification(type="ignore", confidence=0.9, summary="Not relevant")
    result = execute_action(c, config)
    assert result == "Ignored"


def test_execute_action_unknown_type(tmp_path):
    config = _make_config(tmp_path)
    c = Classification(type="banana", confidence=0.9, summary="Unknown")
    result = execute_action(c, config)
    assert "No handler" in result

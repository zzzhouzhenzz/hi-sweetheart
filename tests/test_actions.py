import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from hi_sweetheart.actions import (
    execute_action,
    action_bookmark,
    action_note,
    action_podcast,
    action_config_update,
    action_plugin_install,
    queue_pending,
    load_pending,
    approve_action,
    reject_action,
    _deep_merge,
)
from hi_sweetheart.classifier import Classification
from hi_sweetheart.config import Config


def _make_config(tmp_path) -> Config:
    return Config(
        sender="+15551234567",
        mode="auto",
        items_path=tmp_path / "items.md",
        log_path=tmp_path / "runs.log",
        pending_actions_path=tmp_path / "pending.json",
        reading_list_path=tmp_path / "reading-list.md",
        notes_path=tmp_path / "notes.md",
        claude_settings_path=tmp_path / "settings.json",
        claude_plugins_path=tmp_path / "plugins",
    )


# --- Action handlers ---

def test_action_bookmark(tmp_path):
    config = _make_config(tmp_path)
    c = Classification(
        type="bookmark", confidence=0.9, summary="Good article",
        action_detail={"title": "Prompting Guide", "summary": "All about prompts"},
    )
    action_bookmark(c, config)
    content = config.reading_list_path.read_text()
    assert "Prompting Guide" in content
    assert "All about prompts" in content


def test_action_bookmark_appends(tmp_path):
    config = _make_config(tmp_path)
    config.reading_list_path.write_text("# Reading List\n\n- existing\n")
    c = Classification(
        type="bookmark", confidence=0.9, summary="New article",
        action_detail={"title": "New", "summary": "New content"},
    )
    action_bookmark(c, config)
    content = config.reading_list_path.read_text()
    assert "existing" in content
    assert "New" in content


def test_action_note(tmp_path):
    config = _make_config(tmp_path)
    c = Classification(
        type="note", confidence=0.8, summary="Remember this",
        action_detail={"content": "Set up hooks for better workflow"},
    )
    action_note(c, config)
    content = config.notes_path.read_text()
    assert "Set up hooks" in content


@patch("hi_sweetheart.actions.subprocess")
@patch("hi_sweetheart.actions.time")
def test_action_podcast_saves_episode(mock_time, mock_subprocess, tmp_path):
    """open URL → wait → JXA clicks Save Episode → 'saved'."""
    config = _make_config(tmp_path)
    # First call: open -a Podcasts URL (succeeds)
    # Second call: osascript JXA (returns "saved")
    mock_subprocess.run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),
        MagicMock(returncode=0, stdout="saved\n", stderr=""),
    ]
    c = Classification(
        type="podcast", confidence=0.95, summary="AI podcast",
        action_detail={"podcast_url": "https://podcasts.apple.com/us/podcast/id123?i=456", "podcast_name": "AI Show"},
    )
    action_podcast(c, config)
    assert mock_subprocess.run.call_count == 2
    # First call opens Podcasts app with the URL
    open_cmd = mock_subprocess.run.call_args_list[0][0][0]
    assert open_cmd[0] == "open"
    assert "podcasts.apple.com" in open_cmd[-1]
    # Second call runs JXA
    jxa_cmd = mock_subprocess.run.call_args_list[1][0][0]
    assert jxa_cmd[0] == "osascript"
    assert jxa_cmd[1] == "-l"
    assert jxa_cmd[2] == "JavaScript"


@patch("hi_sweetheart.actions.subprocess")
@patch("hi_sweetheart.actions.time")
def test_action_podcast_already_saved(mock_time, mock_subprocess, tmp_path):
    """If episode is already saved, JXA returns 'already_saved' — no error."""
    config = _make_config(tmp_path)
    mock_subprocess.run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),
        MagicMock(returncode=0, stdout="already_saved\n", stderr=""),
    ]
    c = Classification(
        type="podcast", confidence=0.95, summary="AI podcast",
        action_detail={"podcast_url": "https://podcasts.apple.com/us/podcast/id123?i=456", "podcast_name": "AI Show"},
    )
    action_podcast(c, config)
    assert mock_subprocess.run.call_count == 2


@patch("hi_sweetheart.actions.subprocess")
@patch("hi_sweetheart.actions.time")
def test_action_podcast_button_not_found(mock_time, mock_subprocess, tmp_path):
    """If Save Episode button not found (page didn't load), logs error."""
    config = _make_config(tmp_path)
    mock_subprocess.run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),
        MagicMock(returncode=0, stdout="not_found\n", stderr=""),
    ]
    c = Classification(
        type="podcast", confidence=0.95, summary="AI podcast",
        action_detail={"podcast_url": "https://podcasts.apple.com/us/podcast/id123?i=456", "podcast_name": "AI Show"},
    )
    action_podcast(c, config)
    assert mock_subprocess.run.call_count == 2


def test_action_podcast_skips_non_apple_url(tmp_path):
    config = _make_config(tmp_path)
    c = Classification(
        type="podcast", confidence=0.95, summary="Random podcast",
        action_detail={"podcast_url": "https://example.com/podcast", "podcast_name": "Test"},
    )
    action_podcast(c, config)
    # Should not crash, just log warning


@patch("hi_sweetheart.actions.subprocess")
@patch("hi_sweetheart.actions.time")
def test_action_podcast_open_fails(mock_time, mock_subprocess, tmp_path):
    """If `open` command fails, bail out before JXA."""
    config = _make_config(tmp_path)
    mock_subprocess.run.return_value = MagicMock(returncode=1, stdout="", stderr="app not found")
    c = Classification(
        type="podcast", confidence=0.95, summary="AI podcast",
        action_detail={"podcast_url": "https://podcasts.apple.com/us/podcast/id123?i=456", "podcast_name": "AI Show"},
    )
    action_podcast(c, config)
    # Only the open call, no JXA call
    assert mock_subprocess.run.call_count == 1


def test_action_config_update(tmp_path):
    config = _make_config(tmp_path)
    config.claude_settings_path.write_text(json.dumps({
        "permissions": {"allow": ["Bash(git:*)"]},
        "model": "sonnet",
    }))
    c = Classification(
        type="config_update", confidence=0.9, summary="Update model",
        action_detail={"settings": {"model": "opus"}},
    )
    action_config_update(c, config)
    settings = json.loads(config.claude_settings_path.read_text())
    assert settings["model"] == "opus"
    assert settings["permissions"]["allow"] == ["Bash(git:*)"]
    assert (config.claude_settings_path.with_suffix(".json.bak")).exists()


def test_action_config_update_missing_file(tmp_path):
    config = _make_config(tmp_path)
    c = Classification(
        type="config_update", confidence=0.9, summary="Update",
        action_detail={"settings": {"model": "opus"}},
    )
    # Should not raise, just log error
    action_config_update(c, config)


# --- Deep merge ---

def test_deep_merge_arrays_appended():
    base = {"permissions": {"allow": ["Bash(git:*)"]}}
    override = {"permissions": {"allow": ["Edit"]}}
    result = _deep_merge(base, override)
    assert result["permissions"]["allow"] == ["Bash(git:*)", "Edit"]


def test_deep_merge_nested_dicts():
    base = {"a": {"b": 1, "c": 2}}
    override = {"a": {"b": 3, "d": 4}}
    result = _deep_merge(base, override)
    assert result == {"a": {"b": 3, "c": 2, "d": 4}}


# --- Execute action dispatch ---

def test_execute_action_auto_mode(tmp_path):
    config = _make_config(tmp_path)
    config.mode = "auto"
    c = Classification(
        type="bookmark", confidence=0.9, summary="Article",
        action_detail={"title": "Test", "summary": "Test"},
    )
    result = execute_action(c, config)
    assert "Executed" in result
    assert config.reading_list_path.exists()


def test_execute_action_tiered_queues_risky(tmp_path):
    config = _make_config(tmp_path)
    config.mode = "tiered"
    c = Classification(
        type="plugin_install", confidence=0.9, summary="Plugin",
        action_detail={"install_steps": ["echo hi"]},
    )
    result = execute_action(c, config)
    assert "Queued" in result
    pending = load_pending(config)
    assert len(pending) == 1


def test_execute_action_tiered_runs_safe(tmp_path):
    config = _make_config(tmp_path)
    config.mode = "tiered"
    c = Classification(
        type="bookmark", confidence=0.9, summary="Article",
        action_detail={"title": "Test", "summary": "Test"},
    )
    result = execute_action(c, config)
    assert "Executed" in result


def test_execute_action_propose_queues_everything(tmp_path):
    config = _make_config(tmp_path)
    config.mode = "propose"
    c = Classification(
        type="bookmark", confidence=0.9, summary="Article",
        action_detail={"title": "Test", "summary": "Test"},
    )
    result = execute_action(c, config)
    assert "Queued" in result


def test_execute_action_ignore_skips(tmp_path):
    config = _make_config(tmp_path)
    c = Classification(type="ignore", confidence=0.9, summary="Not relevant")
    result = execute_action(c, config)
    assert result == "Ignored"


# --- Pending queue ---

def test_queue_and_load_pending(tmp_path):
    config = _make_config(tmp_path)
    c = Classification(
        type="plugin_install", confidence=0.9, summary="Cool plugin",
        action_detail={"repo_url": "https://github.com/foo/bar"},
    )
    queue_pending(c, config)
    pending = load_pending(config)
    assert len(pending) == 1
    assert pending[0]["classification"]["type"] == "plugin_install"
    assert "id" in pending[0]


def test_approve_action(tmp_path):
    config = _make_config(tmp_path)
    c = Classification(
        type="bookmark", confidence=0.9, summary="Saved article",
        action_detail={"title": "Test", "summary": "Test summary"},
    )
    queue_pending(c, config)
    pending = load_pending(config)
    action_id = pending[0]["id"]

    approve_action(action_id, config)
    assert config.reading_list_path.exists()
    assert len(load_pending(config)) == 0


def test_reject_action(tmp_path):
    config = _make_config(tmp_path)
    c = Classification(
        type="bookmark", confidence=0.9, summary="Nope",
        action_detail={"title": "Nope", "summary": "Nah"},
    )
    queue_pending(c, config)
    pending = load_pending(config)
    action_id = pending[0]["id"]

    reject_action(action_id, config)
    assert len(load_pending(config)) == 0

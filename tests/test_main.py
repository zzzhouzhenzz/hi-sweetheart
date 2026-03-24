import json
import sqlite3
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock
from hi_sweetheart.main import run_pipeline
from hi_sweetheart.classifier import ClassifyAPIError
from hi_sweetheart.reader import _datetime_to_imessage_ns


def _find_run_file(tmp_path: Path, prefix: str) -> Path:
    """Find the timestamped output file (e.g. reading-list-20260324-011300.md)."""
    matches = sorted(tmp_path.glob(f"{prefix}-*.md"))
    assert matches, f"No {prefix}-*.md file found in {tmp_path}"
    return matches[-1]


def _setup_environment(tmp_path) -> dict:
    """Create config, state dir, and mock iMessage DB."""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "sender": "+15551234567",
        "mode": "auto",
        "reading_list_path": str(tmp_path / "reading-list.md"),
        "notes_path": str(tmp_path / "notes.md"),
        "claude_settings_path": str(tmp_path / "settings.json"),
        "claude_plugins_path": str(tmp_path / "plugins"),
        "log_path": str(tmp_path / "runs.log"),
        "pending_actions_path": str(tmp_path / "pending.json"),
    }))

    state_path = tmp_path / "state.json"
    # rowid=0 means first run — only loads last 3 days of messages
    state_path.write_text(json.dumps({"last_message_rowid": 0, "last_run": None}))

    # Use a recent timestamp so messages pass the 3-day first_run filter
    recent_date = _datetime_to_imessage_ns(datetime.now(timezone.utc) - timedelta(hours=1))

    db_path = tmp_path / "chat.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT)")
    conn.execute("CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, chat_identifier TEXT)")
    conn.execute("CREATE TABLE chat_handle_join (chat_id INTEGER, handle_id INTEGER)")
    conn.execute("CREATE TABLE message (ROWID INTEGER PRIMARY KEY, text TEXT, handle_id INTEGER, date INTEGER, is_from_me INTEGER DEFAULT 0)")
    conn.execute("CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER)")
    conn.execute("INSERT INTO handle (ROWID, id) VALUES (1, '+15551234567')")
    conn.execute("INSERT INTO chat (ROWID, chat_identifier) VALUES (1, '+15551234567')")
    conn.execute("INSERT INTO chat_handle_join (chat_id, handle_id) VALUES (1, 1)")
    conn.execute("INSERT INTO message (ROWID, text, handle_id, date, is_from_me) VALUES (1, 'check this https://example.com/article', 1, ?, 0)", (recent_date,))
    conn.execute("INSERT INTO chat_message_join (chat_id, message_id) VALUES (1, 1)")
    conn.commit()
    conn.close()

    return {
        "config_path": config_path,
        "state_path": state_path,
        "db_path": db_path,
    }


@pytest.mark.asyncio
async def test_run_pipeline_processes_messages(tmp_path):
    env = _setup_environment(tmp_path)

    mock_fetch = AsyncMock(return_value=MagicMock(
        success=True, text="An article about prompt engineering", url="https://example.com/article",
    ))
    mock_classify = AsyncMock(return_value=MagicMock(
        type="bookmark", confidence=0.9, summary="Prompt engineering article",
        action_detail={"title": "Prompting", "summary": "Guide to prompts"},
    ))

    with patch("hi_sweetheart.main.fetch_content", mock_fetch), \
         patch("hi_sweetheart.main.classify", mock_classify), \
         patch("hi_sweetheart.main.send_notification"):

        await run_pipeline(
            config_path=env["config_path"],
            state_path=env["state_path"],
            db_path=env["db_path"],
        )

    reading_list = _find_run_file(tmp_path, "reading-list").read_text()
    assert "Prompting" in reading_list

    state = json.loads(env["state_path"].read_text())
    assert state["last_message_rowid"] == 1


@pytest.mark.asyncio
async def test_run_pipeline_no_new_messages(tmp_path):
    env = _setup_environment(tmp_path)
    env["state_path"].write_text(json.dumps({
        "last_message_rowid": 999,
        "last_run": "2026-03-23T09:00:00Z",
    }))

    with patch("hi_sweetheart.main.send_notification") as mock_notify:
        await run_pipeline(
            config_path=env["config_path"],
            state_path=env["state_path"],
            db_path=env["db_path"],
        )
        mock_notify.assert_called_once()


@pytest.mark.asyncio
async def test_run_pipeline_api_error_aborts_without_advancing(tmp_path):
    """API failure should abort run and NOT advance ROWID."""
    env = _setup_environment(tmp_path)

    mock_fetch = AsyncMock(return_value=MagicMock(
        success=True, text="content", url="https://example.com",
    ))

    with patch("hi_sweetheart.main.fetch_content", mock_fetch), \
         patch("hi_sweetheart.main.classify", AsyncMock(side_effect=ClassifyAPIError("API down"))), \
         patch("hi_sweetheart.main.send_notification"):

        await run_pipeline(
            config_path=env["config_path"],
            state_path=env["state_path"],
            db_path=env["db_path"],
        )

    # ROWID should NOT have advanced
    state = json.loads(env["state_path"].read_text())
    assert state["last_message_rowid"] == 0


@pytest.mark.asyncio
async def test_run_pipeline_fetch_failure_creates_note(tmp_path):
    """Failed URL fetch should create a note action."""
    env = _setup_environment(tmp_path)

    mock_fetch = AsyncMock(return_value=MagicMock(
        success=False, text="", url="https://example.com", error="HTTP 404",
    ))

    with patch("hi_sweetheart.main.fetch_content", mock_fetch), \
         patch("hi_sweetheart.main.send_notification"):

        await run_pipeline(
            config_path=env["config_path"],
            state_path=env["state_path"],
            db_path=env["db_path"],
        )

    notes = _find_run_file(tmp_path, "notes").read_text()
    assert "example.com" in notes

    state = json.loads(env["state_path"].read_text())
    assert state["last_message_rowid"] == 1


@pytest.mark.asyncio
async def test_full_pipeline_tiered_mode(tmp_path):
    """Integration test: tiered mode queues risky action, executes safe one."""
    env = _setup_environment(tmp_path)
    recent_date = _datetime_to_imessage_ns(datetime.now(timezone.utc) - timedelta(hours=1))
    conn = sqlite3.connect(str(env["db_path"]))
    conn.execute("INSERT INTO message (ROWID, text, handle_id, date, is_from_me) VALUES (2, 'try this plugin https://github.com/foo/bar', 1, ?, 0)", (recent_date,))
    conn.execute("INSERT INTO chat_message_join (chat_id, message_id) VALUES (1, 2)")
    conn.commit()
    conn.close()

    call_count = 0

    async def mock_classify(message_text, fetched_content, url):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return MagicMock(
                type="bookmark", confidence=0.9, summary="Article",
                action_detail={"title": "Article", "summary": "Good read"},
            )
        return MagicMock(
            type="plugin_install", confidence=0.9, summary="Cool plugin",
            action_detail={"repo_url": "https://github.com/foo/bar", "install_steps": ["echo test"]},
        )

    mock_fetch = AsyncMock(return_value=MagicMock(
        success=True, text="Some content", url="https://example.com",
    ))

    config_data = json.loads(env["config_path"].read_text())
    config_data["mode"] = "tiered"
    env["config_path"].write_text(json.dumps(config_data))

    with patch("hi_sweetheart.main.fetch_content", mock_fetch), \
         patch("hi_sweetheart.main.classify", mock_classify), \
         patch("hi_sweetheart.main.send_notification"):

        await run_pipeline(
            config_path=env["config_path"],
            state_path=env["state_path"],
            db_path=env["db_path"],
        )

    assert _find_run_file(tmp_path, "reading-list")

    pending = json.loads((tmp_path / "pending.json").read_text())
    assert len(pending) == 1
    assert pending[0]["classification"]["type"] == "plugin_install"

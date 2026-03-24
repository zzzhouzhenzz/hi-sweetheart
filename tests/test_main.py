import json
import sqlite3
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock
from hi_sweetheart.main import run_pipeline, cmd_reset
from hi_sweetheart.classifier import ClassifyAPIError
from hi_sweetheart.items import read_items, add_item, make_item
from hi_sweetheart.reader import _datetime_to_imessage_ns


def _setup_environment(tmp_path) -> dict:
    """Create config, state dir, and mock iMessage DB."""
    config_path = tmp_path / "config.json"
    items_path = tmp_path / "items.md"
    config_path.write_text(json.dumps({
        "sender": "+15551234567",
        "mode": "auto",
        "items_path": str(items_path),
        "log_path": str(tmp_path / "runs.log"),
        "pending_actions_path": str(tmp_path / "pending.json"),
    }))

    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"last_message_rowid": 0, "last_run": None}))

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
        "items_path": items_path,
    }


@pytest.mark.asyncio
async def test_run_pipeline_processes_messages(tmp_path):
    env = _setup_environment(tmp_path)

    mock_fetch = AsyncMock(return_value=MagicMock(
        success=True, text="An article about prompt engineering", url="https://example.com/article",
    ))
    mock_classify = AsyncMock(return_value=MagicMock(
        type="bookmark", confidence=0.9, summary="Prompt engineering article",
        action_detail={"title": "Prompting Guide", "summary": "Guide to prompts"},
    ))

    with patch("hi_sweetheart.main.fetch_content", mock_fetch), \
         patch("hi_sweetheart.main.classify", mock_classify), \
         patch("hi_sweetheart.main.send_notification"):

        await run_pipeline(
            config_path=env["config_path"],
            state_path=env["state_path"],
            db_path=env["db_path"],
        )

    items = read_items(env["items_path"])
    assert len(items) == 1
    assert items[0].title == "Prompting Guide"
    assert items[0].action_type == "bookmark"
    assert items[0].status == "pending"

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

    state = json.loads(env["state_path"].read_text())
    assert state["last_message_rowid"] == 0


@pytest.mark.asyncio
async def test_run_pipeline_fetch_failure_creates_note_item(tmp_path):
    """Failed URL fetch should create a note item in items.md."""
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

    items = read_items(env["items_path"])
    assert len(items) == 1
    assert items[0].action_type == "note"
    assert items[0].title == "Fetch failed"
    assert "example.com" in items[0].url

    state = json.loads(env["state_path"].read_text())
    assert state["last_message_rowid"] == 1


@pytest.mark.asyncio
async def test_run_pipeline_skips_messages_without_urls(tmp_path):
    """Messages without URLs should be skipped entirely."""
    env = _setup_environment(tmp_path)

    # Replace the message with one that has no URL
    conn = sqlite3.connect(str(env["db_path"]))
    conn.execute("UPDATE message SET text = 'just a plain text message' WHERE ROWID = 1")
    conn.commit()
    conn.close()

    with patch("hi_sweetheart.main.send_notification"):
        await run_pipeline(
            config_path=env["config_path"],
            state_path=env["state_path"],
            db_path=env["db_path"],
        )

    # No items created
    items = read_items(env["items_path"])
    assert len(items) == 0

    # State still advances
    state = json.loads(env["state_path"].read_text())
    assert state["last_message_rowid"] == 1


@pytest.mark.asyncio
async def test_run_pipeline_podcast_auto_done(tmp_path):
    """Podcast URLs get saved via JXA and marked done in items.md."""
    env = _setup_environment(tmp_path)

    conn = sqlite3.connect(str(env["db_path"]))
    conn.execute("UPDATE message SET text = 'listen to this https://podcasts.apple.com/us/podcast/id123?i=456' WHERE ROWID = 1")
    conn.commit()
    conn.close()

    with patch("hi_sweetheart.main.action_podcast") as mock_podcast, \
         patch("hi_sweetheart.main.send_notification"):

        await run_pipeline(
            config_path=env["config_path"],
            state_path=env["state_path"],
            db_path=env["db_path"],
        )

    mock_podcast.assert_called_once()
    items = read_items(env["items_path"])
    assert len(items) == 1
    assert items[0].action_type == "podcast"
    assert items[0].status == "done"


@pytest.mark.asyncio
async def test_run_pipeline_ignore_not_added(tmp_path):
    """Classified as 'ignore' should not create an item."""
    env = _setup_environment(tmp_path)

    mock_fetch = AsyncMock(return_value=MagicMock(
        success=True, text="Some irrelevant content",
    ))
    mock_classify = AsyncMock(return_value=MagicMock(
        type="ignore", confidence=0.9, summary="Not relevant",
        action_detail={},
    ))

    with patch("hi_sweetheart.main.fetch_content", mock_fetch), \
         patch("hi_sweetheart.main.classify", mock_classify), \
         patch("hi_sweetheart.main.send_notification"):

        await run_pipeline(
            config_path=env["config_path"],
            state_path=env["state_path"],
            db_path=env["db_path"],
        )

    items = read_items(env["items_path"])
    assert len(items) == 0


@pytest.mark.asyncio
async def test_run_pipeline_plugin_stays_pending(tmp_path):
    """Plugin installs should be listed as pending (no auto-execution)."""
    env = _setup_environment(tmp_path)

    mock_fetch = AsyncMock(return_value=MagicMock(
        success=True, text="A Claude Code plugin repo",
    ))
    mock_classify = AsyncMock(return_value=MagicMock(
        type="plugin_install", confidence=0.9, summary="Cool plugin",
        action_detail={"plugin_name": "engram", "repo_url": "https://github.com/foo/engram"},
    ))

    with patch("hi_sweetheart.main.fetch_content", mock_fetch), \
         patch("hi_sweetheart.main.classify", mock_classify), \
         patch("hi_sweetheart.main.send_notification"):

        await run_pipeline(
            config_path=env["config_path"],
            state_path=env["state_path"],
            db_path=env["db_path"],
        )

    items = read_items(env["items_path"])
    assert len(items) == 1
    assert items[0].action_type == "plugin_install"
    assert items[0].title == "engram"
    assert items[0].status == "pending"


def test_cmd_reset_clears_state_and_items(tmp_path):
    """Reset should delete state and clear items.md."""
    config_path = tmp_path / "config.json"
    items_path = tmp_path / "items.md"
    state_path = tmp_path / "state.json"

    config_path.write_text(json.dumps({
        "sender": "+15551234567",
        "mode": "auto",
        "items_path": str(items_path),
        "log_path": str(tmp_path / "runs.log"),
        "pending_actions_path": str(tmp_path / "pending.json"),
    }))

    state_path.write_text(json.dumps({"last_message_rowid": 42, "last_run": "2026-03-23"}))

    # Seed some items
    add_item(items_path, make_item("bookmark", "Article", "https://example.com", "A read"))
    add_item(items_path, make_item("note", "Tip", "https://example.com/tip", "A tip"))
    assert len(read_items(items_path)) == 2

    # Simulate CLI args
    args = MagicMock()
    args.config = str(config_path)
    args.state = str(state_path)
    cmd_reset(args)

    assert not state_path.exists()
    items = read_items(items_path)
    assert len(items) == 0
    assert items_path.read_text().startswith("# Hi Sweetheart")

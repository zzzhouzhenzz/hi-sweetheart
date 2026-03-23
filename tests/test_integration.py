"""Integration tests — bottom-up, each component tested with mocked inputs.

Layer order (bottom to top):
  1. state + config (persistence)
  2. reader (iMessage DB) with real state
  3. fetcher (URL extraction + HTTP)
  4. classifier (claude -p subprocess)
  5. actions (execute/queue with real filesystem)
  6. reader -> classifier -> actions (multi-layer)
  7. full pipeline (main.run_pipeline)
"""

import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from hi_sweetheart.state import State
from hi_sweetheart.config import Config, load_config
from hi_sweetheart.reader import read_messages, _datetime_to_imessage_ns, IMESSAGE_EPOCH
from hi_sweetheart.fetcher import extract_urls, has_actionable_content
from hi_sweetheart.classifier import Classification, _parse_response, classify, ClassifyAPIError
from hi_sweetheart.actions import (
    execute_action, action_bookmark, action_note, action_config_update,
    queue_pending, load_pending, approve_action, reject_action,
)
from hi_sweetheart.notify import RunSummary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _make_db(db_path: Path, sender: str, messages: list[tuple[str, int]]):
    """Create a minimal iMessage-shaped SQLite DB.

    messages: list of (text, rowid_offset_from_1).
    Each message gets a date = now in iMessage nanosecond epoch.
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT)")
    conn.execute("CREATE TABLE message (ROWID INTEGER PRIMARY KEY, text TEXT, date INTEGER, handle_id INTEGER, is_from_me INTEGER)")
    conn.execute("CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, chat_identifier TEXT)")
    conn.execute("CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER)")
    conn.execute("CREATE TABLE chat_handle_join (chat_id INTEGER, handle_id INTEGER)")

    conn.execute("INSERT INTO handle VALUES (1, ?)", (sender,))
    conn.execute("INSERT INTO chat VALUES (1, ?)", (sender,))
    conn.execute("INSERT INTO chat_handle_join VALUES (1, 1)")

    now_ns = _datetime_to_imessage_ns(datetime.now(timezone.utc))
    for i, (text, rowid) in enumerate(messages):
        conn.execute(
            "INSERT INTO message VALUES (?, ?, ?, 1, 0)",
            (rowid, text, now_ns - (len(messages) - i) * 1_000_000),
        )
        conn.execute("INSERT INTO chat_message_join VALUES (1, ?)", (rowid,))

    conn.commit()
    conn.close()
    return db_path


# ===========================================================================
# Layer 1: state + config integration
# ===========================================================================

class TestStateConfigIntegration:
    """State persists across config-driven paths."""

    def test_state_round_trip_through_config_path(self, tmp_path):
        config_data = {
            "sender": "+15551234567",
            "mode": "auto",
            "reading_list_path": str(tmp_path / "rl.md"),
            "notes_path": str(tmp_path / "notes.md"),
            "claude_settings_path": str(tmp_path / "settings.json"),
            "claude_plugins_path": str(tmp_path / "plugins"),
            "log_path": str(tmp_path / "runs.log"),
            "pending_actions_path": str(tmp_path / "pending.json"),
        }
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config_data))
        config = load_config(config_path)

        state_path = tmp_path / "state.json"
        state = State(state_path)
        assert state.last_message_rowid == 0

        state.update(42)
        state.save()

        # Reload from same path — simulates next run
        state2 = State(state_path)
        assert state2.last_message_rowid == 42
        assert state2.last_run is not None


# ===========================================================================
# Layer 2: reader with real state
# ===========================================================================

class TestReaderStateIntegration:
    """Reader respects after_rowid from State to only fetch new messages."""

    def test_reader_skips_already_seen_messages(self, tmp_path):
        sender = "+15551234567"
        db_path = _make_db(tmp_path / "chat.db", sender, [
            ("old message", 1),
            ("new message", 2),
            ("newest message", 3),
        ])
        # Simulate: state says we've seen up to rowid 1
        msgs = read_messages(db_path, sender=sender, after_rowid=1)
        assert len(msgs) == 2
        assert msgs[0].text == "new message"
        assert msgs[1].text == "newest message"

    def test_reader_first_run_3day_filter(self, tmp_path):
        sender = "+15551234567"
        db_path = tmp_path / "chat.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT)")
        conn.execute("CREATE TABLE message (ROWID INTEGER PRIMARY KEY, text TEXT, date INTEGER, handle_id INTEGER, is_from_me INTEGER)")
        conn.execute("CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, chat_identifier TEXT)")
        conn.execute("CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER)")
        conn.execute("CREATE TABLE chat_handle_join (chat_id INTEGER, handle_id INTEGER)")

        conn.execute("INSERT INTO handle VALUES (1, ?)", (sender,))
        conn.execute("INSERT INTO chat VALUES (1, ?)", (sender,))
        conn.execute("INSERT INTO chat_handle_join VALUES (1, 1)")

        # Message from 5 days ago — should be filtered out on first_run
        old_date = _datetime_to_imessage_ns(datetime.now(timezone.utc) - timedelta(days=5))
        conn.execute("INSERT INTO message VALUES (1, 'very old', ?, 1, 0)", (old_date,))
        conn.execute("INSERT INTO chat_message_join VALUES (1, 1)")

        # Message from 1 day ago — should pass
        recent_date = _datetime_to_imessage_ns(datetime.now(timezone.utc) - timedelta(days=1))
        conn.execute("INSERT INTO message VALUES (2, 'recent', ?, 1, 0)", (recent_date,))
        conn.execute("INSERT INTO chat_message_join VALUES (1, 2)")

        conn.commit()
        conn.close()

        msgs = read_messages(db_path, sender=sender, after_rowid=0, first_run=True)
        assert len(msgs) == 1
        assert msgs[0].text == "recent"

    def test_reader_first_run_false_gets_all(self, tmp_path):
        sender = "+15551234567"
        db_path = tmp_path / "chat.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT)")
        conn.execute("CREATE TABLE message (ROWID INTEGER PRIMARY KEY, text TEXT, date INTEGER, handle_id INTEGER, is_from_me INTEGER)")
        conn.execute("CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, chat_identifier TEXT)")
        conn.execute("CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER)")
        conn.execute("CREATE TABLE chat_handle_join (chat_id INTEGER, handle_id INTEGER)")

        conn.execute("INSERT INTO handle VALUES (1, ?)", (sender,))
        conn.execute("INSERT INTO chat VALUES (1, ?)", (sender,))
        conn.execute("INSERT INTO chat_handle_join VALUES (1, 1)")

        old_date = _datetime_to_imessage_ns(datetime.now(timezone.utc) - timedelta(days=5))
        conn.execute("INSERT INTO message VALUES (1, 'very old', ?, 1, 0)", (old_date,))
        conn.execute("INSERT INTO chat_message_join VALUES (1, 1)")

        conn.commit()
        conn.close()

        # first_run=False: no date filter, gets everything after rowid 0
        msgs = read_messages(db_path, sender=sender, after_rowid=0, first_run=False)
        assert len(msgs) == 1
        assert msgs[0].text == "very old"


# ===========================================================================
# Layer 3: fetcher URL extraction + actionable content detection
# ===========================================================================

class TestFetcherIntegration:
    """Fetcher correctly identifies URLs and actionable content together."""

    def test_message_with_url_and_actionable_json(self):
        text = 'Check this out https://example.com/plugin {"key": "value"}'
        urls = extract_urls(text)
        assert urls == ["https://example.com/plugin"]
        assert has_actionable_content(text) is True

    def test_message_with_url_no_actionable(self):
        text = "Look at https://example.com/article"
        urls = extract_urls(text)
        assert len(urls) == 1
        assert has_actionable_content(text) is False

    def test_message_no_url_with_code_block(self):
        text = "Try this:\n```python\nprint('hello')\n```"
        urls = extract_urls(text)
        assert urls == []
        assert has_actionable_content(text) is True

    def test_plain_text_no_url_no_actionable(self):
        text = "Hey, just checking in!"
        urls = extract_urls(text)
        assert urls == []
        assert has_actionable_content(text) is False


# ===========================================================================
# Layer 4: classifier parse + confidence logic
# ===========================================================================

class TestClassifierParseIntegration:
    """Classifier parsing + confidence gating work together."""

    def test_high_confidence_bookmark(self):
        raw = json.dumps({
            "type": "bookmark",
            "confidence": 0.9,
            "summary": "Great article",
            "action_detail": {"title": "AI News", "summary": "Latest trends"},
        })
        result = _parse_response(raw, "https://example.com")
        assert result.type == "bookmark"
        assert result.confidence == 0.9
        assert result.action_detail["title"] == "AI News"

    def test_low_confidence_downgrades_to_note(self):
        raw = json.dumps({
            "type": "plugin_install",
            "confidence": 0.3,
            "summary": "Maybe a plugin?",
            "action_detail": {"repo_url": "https://github.com/x/y"},
        })
        result = _parse_response(raw, "https://github.com/x/y")
        assert result.type == "note"  # downgraded

    def test_unknown_type_defaults_to_note(self):
        raw = json.dumps({
            "type": "banana",
            "confidence": 0.9,
            "summary": "Invalid type",
        })
        result = _parse_response(raw, "https://example.com")
        assert result.type == "note"

    def test_unparseable_json_returns_note(self):
        result = _parse_response("not json at all", "https://example.com")
        assert result.type == "note"
        assert result.confidence == 0.0

    @patch("hi_sweetheart.classifier.subprocess.run")
    def test_classify_calls_claude_and_parses(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "type": "bookmark",
                "confidence": 0.85,
                "summary": "A cool tool",
                "action_detail": {"title": "Tool", "summary": "Does stuff"},
            }),
        )
        import asyncio
        result = asyncio.run(classify(
            message_text="check this",
            fetched_content="content here",
            url="https://example.com",
        ))
        assert result.type == "bookmark"
        assert mock_run.called

    @patch("hi_sweetheart.classifier.subprocess.run")
    @patch("hi_sweetheart.classifier.time.sleep")
    def test_classify_retries_on_failure(self, mock_sleep, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=1, stderr="timeout"),
            MagicMock(returncode=1, stderr="timeout"),
            MagicMock(returncode=1, stderr="timeout"),
        ]
        import asyncio
        with pytest.raises(ClassifyAPIError):
            asyncio.run(classify(
                message_text="test",
                fetched_content="content",
                url="https://example.com",
            ))
        assert mock_run.call_count == 3


# ===========================================================================
# Layer 5: actions with real filesystem
# ===========================================================================

class TestActionsFilesystemIntegration:
    """Actions write to real files, queue/approve/reject with real JSON."""

    def test_bookmark_creates_reading_list(self, tmp_path):
        config = _make_config(tmp_path)
        c = Classification(
            type="bookmark", confidence=0.9, summary="Good read",
            action_detail={"title": "AI Paper", "summary": "Transformers are neat"},
        )
        result = execute_action(c, config)
        assert "Executed" in result
        content = config.reading_list_path.read_text()
        assert "AI Paper" in content
        assert "Transformers are neat" in content

    def test_note_appends_to_existing(self, tmp_path):
        config = _make_config(tmp_path)
        config.notes_path.write_text("# Notes\n\n## Old note\n\nOld content\n")

        c = Classification(
            type="note", confidence=0.8, summary="Tip about caching",
            action_detail={"content": "Use Redis for ephemeral state"},
        )
        execute_action(c, config)

        content = config.notes_path.read_text()
        assert "Old note" in content
        assert "Tip about caching" in content
        assert "Redis" in content

    def test_config_update_merges_and_backs_up(self, tmp_path):
        config = _make_config(tmp_path)
        config.claude_settings_path.write_text(json.dumps({"theme": "dark", "plugins": ["a"]}))

        c = Classification(
            type="config_update", confidence=0.9, summary="Add plugin b",
            action_detail={"settings": {"plugins": ["b"], "new_key": True}},
        )
        execute_action(c, config)

        # Backup exists
        assert config.claude_settings_path.with_suffix(".json.bak").exists()

        merged = json.loads(config.claude_settings_path.read_text())
        assert merged["theme"] == "dark"
        assert merged["plugins"] == ["a", "b"]  # lists concatenated
        assert merged["new_key"] is True

    def test_tiered_mode_queues_risky_actions(self, tmp_path):
        config = _make_config(tmp_path)
        config.mode = "tiered"

        c = Classification(
            type="plugin_install", confidence=0.9, summary="Install cool plugin",
            action_detail={"repo_url": "https://github.com/x/y", "plugin_name": "cool", "install_steps": ["echo hi"]},
        )
        result = execute_action(c, config)
        assert "Queued" in result

        pending = load_pending(config)
        assert len(pending) == 1
        assert pending[0]["classification"]["type"] == "plugin_install"

    def test_tiered_mode_executes_safe_actions(self, tmp_path):
        config = _make_config(tmp_path)
        config.mode = "tiered"

        c = Classification(
            type="bookmark", confidence=0.9, summary="Safe bookmark",
            action_detail={"title": "Article", "summary": "Content"},
        )
        result = execute_action(c, config)
        assert "Executed" in result

    def test_propose_mode_queues_everything(self, tmp_path):
        config = _make_config(tmp_path)
        config.mode = "propose"

        c = Classification(
            type="bookmark", confidence=0.9, summary="Even bookmarks queued",
            action_detail={"title": "Article", "summary": "Content"},
        )
        result = execute_action(c, config)
        assert "Queued" in result

    def test_approve_executes_and_removes_from_queue(self, tmp_path):
        config = _make_config(tmp_path)
        config.mode = "propose"

        c = Classification(
            type="note", confidence=0.9, summary="A note to approve",
            action_detail={"content": "Important info"},
        )
        execute_action(c, config)

        pending = load_pending(config)
        action_id = pending[0]["id"]

        approve_action(action_id, config)

        # Queue is now empty
        assert load_pending(config) == []
        # Note was written
        assert config.notes_path.exists()
        assert "Important info" in config.notes_path.read_text()

    def test_reject_removes_from_queue_no_side_effects(self, tmp_path):
        config = _make_config(tmp_path)
        config.mode = "propose"

        c = Classification(
            type="bookmark", confidence=0.9, summary="Reject me",
            action_detail={"title": "Nope", "summary": "Don't want"},
        )
        execute_action(c, config)

        pending = load_pending(config)
        action_id = pending[0]["id"]

        reject_action(action_id, config)

        assert load_pending(config) == []
        # Reading list was NOT created
        assert not config.reading_list_path.exists()

    def test_ignore_does_nothing(self, tmp_path):
        config = _make_config(tmp_path)
        c = Classification(type="ignore", confidence=0.95, summary="Not relevant")
        result = execute_action(c, config)
        assert result == "Ignored"


# ===========================================================================
# Layer 6: reader -> classifier -> actions (multi-layer)
# ===========================================================================

class TestReaderClassifierActionsIntegration:
    """Messages flow from DB through classification to action execution."""

    @patch("hi_sweetheart.classifier.subprocess.run")
    def test_message_to_bookmark_end_to_end(self, mock_claude, tmp_path):
        sender = "+15551234567"
        db_path = _make_db(tmp_path / "chat.db", sender, [
            ("Check out https://example.com/cool-article", 1),
        ])
        config = _make_config(tmp_path)

        # Step 1: read messages
        msgs = read_messages(db_path, sender=sender, after_rowid=0)
        assert len(msgs) == 1

        # Step 2: extract URLs
        urls = extract_urls(msgs[0].text)
        assert urls == ["https://example.com/cool-article"]

        # Step 3: classify (mock claude -p)
        mock_claude.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "type": "bookmark",
                "confidence": 0.9,
                "summary": "Cool article about AI",
                "action_detail": {"title": "Cool Article", "summary": "AI trends 2026"},
            }),
        )
        import asyncio
        classification = asyncio.run(classify(
            message_text=msgs[0].text,
            fetched_content="fetched page content",
            url=urls[0],
        ))
        assert classification.type == "bookmark"

        # Step 4: execute action
        result = execute_action(classification, config)
        assert "Executed" in result
        assert "Cool Article" in config.reading_list_path.read_text()

    @patch("hi_sweetheart.classifier.subprocess.run")
    def test_low_confidence_becomes_note(self, mock_claude, tmp_path):
        sender = "+15551234567"
        db_path = _make_db(tmp_path / "chat.db", sender, [
            ("Look at https://example.com/ambiguous", 1),
        ])
        config = _make_config(tmp_path)

        msgs = read_messages(db_path, sender=sender, after_rowid=0)
        urls = extract_urls(msgs[0].text)

        mock_claude.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "type": "plugin_install",
                "confidence": 0.3,
                "summary": "Maybe a plugin",
                "action_detail": {"repo_url": urls[0]},
            }),
        )

        import asyncio
        classification = asyncio.run(classify(
            message_text=msgs[0].text,
            fetched_content="ambiguous content",
            url=urls[0],
        ))
        # Downgraded to note due to low confidence
        assert classification.type == "note"

        result = execute_action(classification, config)
        assert "Executed" in result
        assert config.notes_path.exists()


# ===========================================================================
# Layer 7: RunSummary integration with actions
# ===========================================================================

class TestSummaryActionsIntegration:
    """RunSummary correctly tracks action results and errors."""

    def test_summary_tracks_mixed_results(self, tmp_path):
        config = _make_config(tmp_path)
        summary = RunSummary()

        # Successful bookmark
        c1 = Classification(
            type="bookmark", confidence=0.9, summary="Good article",
            action_detail={"title": "AI News", "summary": "Trends"},
        )
        result = execute_action(c1, config)
        summary.add("bookmark", result)

        # Ignore
        c2 = Classification(type="ignore", confidence=0.95, summary="Spam")
        result = execute_action(c2, config)
        summary.add("ignore", result)

        # Simulate error
        summary.add_error("Fetch failed: https://broken.com")

        text = summary.format()
        assert "bookmark" in text
        assert "ignore" in text
        assert "1 error(s)" in text
        assert "broken.com" in text

    def test_empty_summary(self):
        summary = RunSummary()
        assert "No new messages" in summary.format()

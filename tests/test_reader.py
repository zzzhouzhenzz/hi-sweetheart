import sqlite3
import pytest
from pathlib import Path
from hi_sweetheart.reader import read_messages, Message


def _create_test_db(db_path: Path, messages: list[dict]) -> Path:
    """Create a minimal iMessage-like DB for testing."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT)")
    conn.execute("CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, chat_identifier TEXT)")
    conn.execute("CREATE TABLE chat_handle_join (chat_id INTEGER, handle_id INTEGER)")
    conn.execute("CREATE TABLE message (ROWID INTEGER PRIMARY KEY, text TEXT, handle_id INTEGER, date INTEGER, is_from_me INTEGER DEFAULT 0)")
    conn.execute("CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER)")

    conn.execute("INSERT INTO handle (ROWID, id) VALUES (1, '+15551234567')")
    conn.execute("INSERT INTO chat (ROWID, chat_identifier) VALUES (1, '+15551234567')")
    conn.execute("INSERT INTO chat_handle_join (chat_id, handle_id) VALUES (1, 1)")

    for msg in messages:
        conn.execute(
            "INSERT INTO message (ROWID, text, handle_id, date, is_from_me) VALUES (?, ?, 1, ?, 0)",
            (msg["rowid"], msg["text"], msg.get("date", 0)),
        )
        conn.execute(
            "INSERT INTO chat_message_join (chat_id, message_id) VALUES (1, ?)",
            (msg["rowid"],),
        )

    conn.commit()
    conn.close()
    return db_path


def test_read_messages_returns_new(tmp_path):
    db = _create_test_db(tmp_path / "chat.db", [
        {"rowid": 1, "text": "old message"},
        {"rowid": 2, "text": "check this out https://example.com"},
        {"rowid": 3, "text": "another one"},
    ])
    messages = read_messages(db, sender="+15551234567", after_rowid=1)
    assert len(messages) == 2
    assert messages[0].rowid == 2
    assert messages[1].rowid == 3


def test_read_messages_empty_when_no_new(tmp_path):
    db = _create_test_db(tmp_path / "chat.db", [
        {"rowid": 1, "text": "only message"},
    ])
    messages = read_messages(db, sender="+15551234567", after_rowid=1)
    assert len(messages) == 0


def test_read_messages_filters_by_sender(tmp_path):
    db = tmp_path / "chat.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT)")
    conn.execute("CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, chat_identifier TEXT)")
    conn.execute("CREATE TABLE chat_handle_join (chat_id INTEGER, handle_id INTEGER)")
    conn.execute("CREATE TABLE message (ROWID INTEGER PRIMARY KEY, text TEXT, handle_id INTEGER, date INTEGER, is_from_me INTEGER DEFAULT 0)")
    conn.execute("CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER)")

    conn.execute("INSERT INTO handle (ROWID, id) VALUES (1, '+15551234567')")
    conn.execute("INSERT INTO handle (ROWID, id) VALUES (2, '+15559999999')")
    conn.execute("INSERT INTO chat (ROWID, chat_identifier) VALUES (1, '+15551234567')")
    conn.execute("INSERT INTO chat (ROWID, chat_identifier) VALUES (2, '+15559999999')")
    conn.execute("INSERT INTO chat_handle_join (chat_id, handle_id) VALUES (1, 1)")
    conn.execute("INSERT INTO chat_handle_join (chat_id, handle_id) VALUES (2, 2)")
    conn.execute("INSERT INTO message (ROWID, text, handle_id, date, is_from_me) VALUES (1, 'from gf', 1, 0, 0)")
    conn.execute("INSERT INTO message (ROWID, text, handle_id, date, is_from_me) VALUES (2, 'from other', 2, 0, 0)")
    conn.execute("INSERT INTO chat_message_join (chat_id, message_id) VALUES (1, 1)")
    conn.execute("INSERT INTO chat_message_join (chat_id, message_id) VALUES (2, 2)")
    conn.commit()
    conn.close()

    messages = read_messages(db, sender="+15551234567", after_rowid=0)
    assert len(messages) == 1
    assert messages[0].text == "from gf"


def test_message_dataclass():
    msg = Message(rowid=1, text="hello", date=0)
    assert msg.rowid == 1
    assert msg.text == "hello"


def test_read_messages_skips_null_text(tmp_path):
    db = _create_test_db(tmp_path / "chat.db", [
        {"rowid": 1, "text": "real message"},
    ])
    # Add a message with NULL text (e.g. image attachment)
    conn = sqlite3.connect(str(db))
    conn.execute("INSERT INTO message (ROWID, text, handle_id, date, is_from_me) VALUES (2, NULL, 1, 0, 0)")
    conn.execute("INSERT INTO chat_message_join (chat_id, message_id) VALUES (1, 2)")
    conn.commit()
    conn.close()

    messages = read_messages(db, sender="+15551234567", after_rowid=0)
    assert len(messages) == 1
    assert messages[0].text == "real message"

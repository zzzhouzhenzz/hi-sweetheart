from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger("hi-sweetheart")

IMESSAGE_DB_PATH = Path.home() / "Library" / "Messages" / "chat.db"

MAX_RETRIES = 3
RETRY_DELAY = 0.5

# iMessage epoch: 2001-01-01 00:00:00 UTC (in nanoseconds)
IMESSAGE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


@dataclass
class Message:
    rowid: int
    text: str
    date: int


def _datetime_to_imessage_ns(dt: datetime) -> int:
    """Convert a datetime to iMessage nanosecond timestamp."""
    delta = dt - IMESSAGE_EPOCH
    return int(delta.total_seconds() * 1_000_000_000)


def read_messages(
    db_path: Path = IMESSAGE_DB_PATH,
    sender: str = "",
    after_rowid: int = 0,
    first_run: bool = False,
) -> list[Message]:
    uri = f"file:{db_path}?mode=ro"

    conn = None
    for attempt in range(MAX_RETRIES):
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=5)
            break
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and attempt < MAX_RETRIES - 1:
                logger.warning(f"DB locked, retrying ({attempt + 1}/{MAX_RETRIES})...")
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                raise

    if conn is None:
        raise sqlite3.OperationalError("Failed to connect to iMessage DB after retries")

    try:
        # Build query with optional date filter for first run
        query = """
            SELECT m.ROWID, m.text, m.date
            FROM message m
            JOIN handle h ON m.handle_id = h.ROWID
            JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
            JOIN chat c ON cmj.chat_id = c.ROWID
            JOIN chat_handle_join chj ON chj.chat_id = c.ROWID
            WHERE h.id = ?
              AND m.ROWID > ?
              AND m.is_from_me = 0
              AND c.chat_identifier = ?
        """
        params: list = [sender, after_rowid, sender]

        if first_run and after_rowid == 0:
            cutoff = _datetime_to_imessage_ns(datetime.now(timezone.utc) - timedelta(hours=24))
            query += "  AND m.date > ?\n"
            params.append(cutoff)

        query += "ORDER BY m.ROWID ASC"

        cursor = conn.execute(query, params)

        messages = []
        for row in cursor:
            text = row[1]
            if text is None:
                continue
            messages.append(Message(rowid=row[0], text=text, date=row[2]))
        return messages
    finally:
        conn.close()

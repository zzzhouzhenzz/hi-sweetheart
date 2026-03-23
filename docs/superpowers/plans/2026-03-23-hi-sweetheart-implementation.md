# hi-sweetheart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone Python agent that reads iMessages, classifies linked content via Claude API, and executes actions (install plugins, bookmark links, subscribe to podcasts, etc.) on a cron schedule.

**Architecture:** Pipeline of independent modules: reader (iMessage DB) → fetcher (URL content) → classifier (Claude API) → actions (execute) — all wrapped in cross-cutting logging/notification. State tracked via ROWID in a JSON file. Three execution modes (auto/tiered/propose) control which actions run immediately vs queue.

**Tech Stack:** Python 3.12+, anthropic SDK, httpx, beautifulsoup4, sqlite3, macOS osascript/launchd

**Spec:** `docs/superpowers/specs/2026-03-23-hi-sweetheart-design.md`

---

## File Map

| File | Responsibility |
|---|---|
| `pyproject.toml` | Package metadata, dependencies, CLI entry point |
| `config.json.example` | Example config with placeholder values |
| `.gitignore` | Ignore config.json, __pycache__, .venv |
| `src/hi_sweetheart/__init__.py` | Package init |
| `src/hi_sweetheart/config.py` | Load, validate, expand paths in config.json |
| `src/hi_sweetheart/state.py` | Read/write `~/.hi-sweetheart/state.json` (last ROWID, last run) |
| `src/hi_sweetheart/reader.py` | Query iMessage `chat.db` for new messages from sender |
| `src/hi_sweetheart/fetcher.py` | Extract URLs from text, fetch page content (httpx + bs4, GitHub API) |
| `src/hi_sweetheart/classifier.py` | Send fetched content to Claude API, return structured classification |
| `src/hi_sweetheart/actions.py` | Execute classified actions (plugin install, config update, bookmark, podcast, note, pending queue) |
| `src/hi_sweetheart/notify.py` | macOS notifications via osascript, structured logging setup |
| `src/hi_sweetheart/main.py` | CLI (argparse), orchestrator pipeline |
| `tests/test_config.py` | Config loading tests |
| `tests/test_state.py` | State read/write tests |
| `tests/test_reader.py` | iMessage DB query tests (mock sqlite) |
| `tests/test_fetcher.py` | URL extraction + content fetch tests |
| `tests/test_classifier.py` | Classification tests (mock API) |
| `tests/test_actions.py` | Action execution tests |
| `tests/test_main.py` | End-to-end pipeline tests |
| `com.hi-sweetheart.plist` | launchd schedule template |

---

### Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `config.json.example`
- Create: `.gitignore`
- Create: `src/hi_sweetheart/__init__.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "hi-sweetheart"
version = "0.1.0"
description = "Reads iMessages, classifies linked content via Claude API, executes actions"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.40.0",
    "httpx>=0.27.0",
    "beautifulsoup4>=4.12.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0.0"]

[project.scripts]
hi-sweetheart = "hi_sweetheart.main:main"

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2: Create config.json.example**

```json
{
  "sender": "+15551234567",
  "api_key_env": "ANTHROPIC_API_KEY",
  "mode": "auto",
  "reading_list_path": "~/Downloads/hi-sweetheart-reading-list.md",
  "notes_path": "~/.hi-sweetheart/notes.md",
  "claude_settings_path": "~/.claude/settings.json",
  "claude_plugins_path": "~/.claude/plugins",
  "log_path": "~/.hi-sweetheart/runs.log",
  "pending_actions_path": "~/.hi-sweetheart/pending.json"
}
```

- [ ] **Step 3: Create .gitignore**

```
config.json
__pycache__/
*.pyc
.venv/
*.egg-info/
dist/
build/
```

- [ ] **Step 4: Create src/hi_sweetheart/__init__.py**

```python
"""hi-sweetheart: iMessage reader + Claude-powered action agent."""
```

- [ ] **Step 5: Create venv and install in dev mode**

```bash
cd /home/zz/ml-workspace/hi-sweetheart
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml config.json.example .gitignore src/hi_sweetheart/__init__.py
git commit -m "scaffold: project structure, dependencies, config example"
```

---

### Task 2: Config Module

**Files:**
- Create: `src/hi_sweetheart/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing tests for config**

```python
# tests/test_config.py
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
    # Paths should be expanded
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_config.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'hi_sweetheart.config'`

- [ ] **Step 3: Implement config module**

```python
# src/hi_sweetheart/config.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_config.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/hi_sweetheart/config.py tests/test_config.py
git commit -m "feat: config loading with validation and path expansion"
```

---

### Task 3: State Module

**Files:**
- Create: `src/hi_sweetheart/state.py`
- Create: `tests/test_state.py`

- [ ] **Step 1: Write failing tests for state**

```python
# tests/test_state.py
import json
from pathlib import Path
from hi_sweetheart.state import State


def test_load_state_fresh(tmp_path):
    state_file = tmp_path / "state.json"
    state = State(state_file)
    assert state.last_message_rowid == 0
    assert state.last_run is None


def test_load_state_existing(tmp_path):
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({
        "last_message_rowid": 42,
        "last_run": "2026-03-23T09:00:00Z",
    }))
    state = State(state_file)
    assert state.last_message_rowid == 42
    assert state.last_run == "2026-03-23T09:00:00Z"


def test_save_state(tmp_path):
    state_file = tmp_path / "state.json"
    state = State(state_file)
    state.update(rowid=99)
    state.save()

    data = json.loads(state_file.read_text())
    assert data["last_message_rowid"] == 99
    assert "last_run" in data


def test_update_advances_rowid(tmp_path):
    state_file = tmp_path / "state.json"
    state = State(state_file)
    state.update(rowid=10)
    state.update(rowid=20)
    assert state.last_message_rowid == 20
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_state.py -v
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement state module**

```python
# src/hi_sweetheart/state.py
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class State:
    def __init__(self, path: Path):
        self.path = path
        self.last_message_rowid: int = 0
        self.last_run: str | None = None
        self._load()

    def _load(self):
        if self.path.exists():
            data = json.loads(self.path.read_text())
            self.last_message_rowid = data.get("last_message_rowid", 0)
            self.last_run = data.get("last_run")

    def update(self, rowid: int):
        self.last_message_rowid = rowid
        self.last_run = datetime.now(timezone.utc).isoformat()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({
            "last_message_rowid": self.last_message_rowid,
            "last_run": self.last_run,
        }, indent=2))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_state.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/hi_sweetheart/state.py tests/test_state.py
git commit -m "feat: state management with ROWID tracking"
```

---

### Task 4: Notify Module (Logger + macOS Notifications)

**Files:**
- Create: `src/hi_sweetheart/notify.py`
- Create: `tests/test_notify.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_notify.py
import logging
from unittest.mock import patch
from pathlib import Path
from hi_sweetheart.notify import setup_logging, send_notification, RunSummary


def test_setup_logging(tmp_path):
    log_path = tmp_path / "test.log"
    logger = setup_logging(log_path)
    logger.info("test message")
    assert log_path.exists()
    assert "test message" in log_path.read_text()


def test_run_summary_no_messages():
    summary = RunSummary()
    assert summary.format() == "hi-sweetheart: No new messages"


def test_run_summary_with_actions():
    summary = RunSummary()
    summary.add("bookmark", "Saved article about prompting")
    summary.add("plugin_install", "Installed superpowers plugin")
    summary.add_error("Failed to fetch https://example.com")
    text = summary.format()
    assert "bookmark" in text
    assert "plugin_install" in text
    assert "1 error" in text


@patch("hi_sweetheart.notify.subprocess")
def test_send_notification_calls_osascript(mock_subprocess):
    send_notification("Test Title", "Test Body")
    mock_subprocess.run.assert_called_once()
    cmd = mock_subprocess.run.call_args[0][0]
    assert "osascript" in cmd
    assert "Test Title" in " ".join(cmd)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_notify.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement notify module**

```python
# src/hi_sweetheart/notify.py
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


def setup_logging(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("hi-sweetheart")
    logger.setLevel(logging.INFO)
    # Clear existing handlers to avoid duplicates
    logger.handlers.clear()
    handler = logging.FileHandler(log_path)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(handler)
    # Also log to stderr for manual runs
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(console)
    return logger


@dataclass
class RunSummary:
    actions: list[tuple[str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def add(self, action_type: str, description: str):
        self.actions.append((action_type, description))

    def add_error(self, description: str):
        self.errors.append(description)

    def format(self) -> str:
        if not self.actions and not self.errors:
            return "hi-sweetheart: No new messages"

        lines = ["hi-sweetheart run summary:"]
        for action_type, desc in self.actions:
            lines.append(f"  [{action_type}] {desc}")
        if self.errors:
            lines.append(f"  {len(self.errors)} error(s):")
            for err in self.errors:
                lines.append(f"    - {err}")
        return "\n".join(lines)


def send_notification(title: str, body: str):
    try:
        subprocess.run([
            "osascript", "-e",
            f'display notification "{body}" with title "{title}"',
        ], capture_output=True, timeout=5)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        # Not on macOS or osascript unavailable — log only
        logging.getLogger("hi-sweetheart").warning(
            "Could not send macOS notification (osascript unavailable)"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_notify.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/hi_sweetheart/notify.py tests/test_notify.py
git commit -m "feat: logging setup and macOS notification support"
```

---

### Task 5: iMessage Reader

**Files:**
- Create: `src/hi_sweetheart/reader.py`
- Create: `tests/test_reader.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_reader.py
import sqlite3
import pytest
from pathlib import Path
from hi_sweetheart.reader import read_messages, Message


def _create_test_db(db_path: Path, messages: list[dict]) -> Path:
    """Create a minimal iMessage-like DB for testing."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE handle (
            ROWID INTEGER PRIMARY KEY,
            id TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE chat (
            ROWID INTEGER PRIMARY KEY,
            chat_identifier TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE chat_handle_join (
            chat_id INTEGER,
            handle_id INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE message (
            ROWID INTEGER PRIMARY KEY,
            text TEXT,
            handle_id INTEGER,
            date INTEGER,
            is_from_me INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE chat_message_join (
            chat_id INTEGER,
            message_id INTEGER
        )
    """)

    # Insert sender handle
    conn.execute("INSERT INTO handle (ROWID, id) VALUES (1, '+15551234567')")
    # Insert 1:1 chat
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

    # Two handles
    conn.execute("INSERT INTO handle (ROWID, id) VALUES (1, '+15551234567')")
    conn.execute("INSERT INTO handle (ROWID, id) VALUES (2, '+15559999999')")
    # Two 1:1 chats
    conn.execute("INSERT INTO chat (ROWID, chat_identifier) VALUES (1, '+15551234567')")
    conn.execute("INSERT INTO chat (ROWID, chat_identifier) VALUES (2, '+15559999999')")
    conn.execute("INSERT INTO chat_handle_join (chat_id, handle_id) VALUES (1, 1)")
    conn.execute("INSERT INTO chat_handle_join (chat_id, handle_id) VALUES (2, 2)")
    # Messages from different senders
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_reader.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement reader module**

```python
# src/hi_sweetheart/reader.py
from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("hi-sweetheart")

IMESSAGE_DB_PATH = Path.home() / "Library" / "Messages" / "chat.db"

MAX_RETRIES = 3
RETRY_DELAY = 0.5


@dataclass
class Message:
    rowid: int
    text: str
    date: int


def read_messages(
    db_path: Path = IMESSAGE_DB_PATH,
    sender: str = "",
    after_rowid: int = 0,
) -> list[Message]:
    uri = f"file:{db_path}?mode=ro"

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

    try:
        cursor = conn.execute("""
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
            ORDER BY m.ROWID ASC
        """, (sender, after_rowid, sender))

        messages = []
        for row in cursor:
            text = row[1]
            if text is None:
                continue
            messages.append(Message(rowid=row[0], text=text, date=row[2]))
        return messages
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_reader.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/hi_sweetheart/reader.py tests/test_reader.py
git commit -m "feat: iMessage DB reader with sender filtering and retry"
```

---

### Task 6: URL Fetcher

**Files:**
- Create: `src/hi_sweetheart/fetcher.py`
- Create: `tests/test_fetcher.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_fetcher.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from hi_sweetheart.fetcher import extract_urls, fetch_content, FetchResult


def test_extract_urls_from_text():
    text = "check this out https://example.com/page and also http://foo.bar/baz"
    urls = extract_urls(text)
    assert len(urls) == 2
    assert "https://example.com/page" in urls
    assert "http://foo.bar/baz" in urls


def test_extract_urls_no_urls():
    urls = extract_urls("just a regular message with no links")
    assert len(urls) == 0


def test_extract_urls_deduplicates():
    text = "see https://example.com and also https://example.com"
    urls = extract_urls(text)
    assert len(urls) == 1


def test_extract_urls_github():
    text = "check https://github.com/obra/superpowers"
    urls = extract_urls(text)
    assert len(urls) == 1
    assert "github.com/obra/superpowers" in urls[0]


def test_has_actionable_content_json():
    from hi_sweetheart.fetcher import has_actionable_content
    assert has_actionable_content('try this {"model": "opus"}')
    assert not has_actionable_content("lol ok")


@pytest.mark.asyncio
async def test_fetch_content_html():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "text/html"}
    mock_response.text = "<html><body><h1>Title</h1><p>Content here</p></body></html>"

    with patch("hi_sweetheart.fetcher.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        result = await fetch_content("https://example.com")
        assert isinstance(result, FetchResult)
        assert result.success
        assert "Content here" in result.text


@pytest.mark.asyncio
async def test_fetch_content_github_readme():
    """GitHub URLs should use the API to fetch README content."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json = MagicMock(return_value={
        "content": "IyBTdXBlcnBvd2Vycw==",  # base64 "# Superpowers"
        "encoding": "base64",
    })

    with patch("hi_sweetheart.fetcher.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        result = await fetch_content("https://github.com/obra/superpowers")
        assert result.success
        assert "Superpowers" in result.text


@pytest.mark.asyncio
async def test_fetch_content_failure():
    with patch("hi_sweetheart.fetcher.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("timeout"))
        mock_client_cls.return_value = mock_client

        result = await fetch_content("https://example.com")
        assert not result.success
        assert "timeout" in result.error
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_fetcher.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement fetcher module**

```python
# src/hi_sweetheart/fetcher.py
from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("hi-sweetheart")

URL_PATTERN = re.compile(r'https?://[^\s<>"\']+')
GITHUB_REPO_PATTERN = re.compile(r'https?://github\.com/([^/]+)/([^/\s#?]+)')
ACTIONABLE_PATTERNS = [re.compile(r'\{'), re.compile(r'```')]


def extract_urls(text: str) -> list[str]:
    urls = URL_PATTERN.findall(text)
    # Strip trailing punctuation that gets caught
    urls = [u.rstrip(".,;:)]}") for u in urls]
    return list(dict.fromkeys(urls))  # deduplicate, preserve order


def has_actionable_content(text: str) -> bool:
    return any(p.search(text) for p in ACTIONABLE_PATTERNS)


@dataclass
class FetchResult:
    url: str
    success: bool
    text: str = ""
    error: str = ""


async def fetch_content(url: str) -> FetchResult:
    try:
        github_match = GITHUB_REPO_PATTERN.match(url)
        if github_match:
            return await _fetch_github_readme(github_match.group(1), github_match.group(2))
        return await _fetch_html(url)
    except Exception as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return FetchResult(url=url, success=False, error=str(e))


async def _fetch_github_readme(owner: str, repo: str) -> FetchResult:
    url = f"https://github.com/{owner}/{repo}"
    api_url = f"https://api.github.com/repos/{owner}/{repo}/readme"
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(api_url, headers={"Accept": "application/vnd.github.v3+json"})
        if resp.status_code != 200:
            # Fallback to HTML
            return await _fetch_html(url)
        data = resp.json()
        if data.get("encoding") == "base64":
            content = base64.b64decode(data["content"]).decode("utf-8")
        else:
            content = data.get("content", "")
        return FetchResult(url=url, success=True, text=content)


async def _fetch_html(url: str) -> FetchResult:
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            return FetchResult(url=url, success=False, error=f"HTTP {resp.status_code}")
        soup = BeautifulSoup(resp.text, "html.parser")
        # Remove script/style tags
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        # Truncate to avoid blowing up context
        if len(text) > 10000:
            text = text[:10000] + "\n...[truncated]"
        return FetchResult(url=url, success=True, text=text)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_fetcher.py -v
```

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/hi_sweetheart/fetcher.py tests/test_fetcher.py
git commit -m "feat: URL extraction and content fetching (HTML + GitHub API)"
```

---

### Task 7: Classifier

**Files:**
- Create: `src/hi_sweetheart/classifier.py`
- Create: `tests/test_classifier.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_classifier.py
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from hi_sweetheart.classifier import classify, Classification, CLASSIFICATION_TYPES


def test_classification_types():
    assert "plugin_install" in CLASSIFICATION_TYPES
    assert "marketplace_install" in CLASSIFICATION_TYPES
    assert "config_update" in CLASSIFICATION_TYPES
    assert "bookmark" in CLASSIFICATION_TYPES
    assert "podcast" in CLASSIFICATION_TYPES
    assert "note" in CLASSIFICATION_TYPES
    assert "ignore" in CLASSIFICATION_TYPES


@pytest.mark.asyncio
async def test_classify_returns_structured_result():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "type": "bookmark",
        "confidence": 0.9,
        "summary": "Article about prompt engineering",
        "action_detail": {
            "title": "Prompt Engineering Guide",
            "summary": "Comprehensive guide to prompting",
        },
    }))]

    with patch("hi_sweetheart.classifier.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_client

        result = await classify(
            message_text="check this out",
            fetched_content="A comprehensive guide to prompt engineering...",
            url="https://example.com/prompting",
            api_key="test-key",
        )
        assert isinstance(result, Classification)
        assert result.type == "bookmark"
        assert result.confidence == 0.9


@pytest.mark.asyncio
async def test_classify_low_confidence_becomes_note():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "type": "plugin_install",
        "confidence": 0.3,
        "summary": "Maybe a plugin?",
        "action_detail": {},
    }))]

    with patch("hi_sweetheart.classifier.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_client

        result = await classify(
            message_text="hmm",
            fetched_content="unclear content",
            url="https://example.com",
            api_key="test-key",
        )
        assert result.type == "note"


@pytest.mark.asyncio
async def test_classify_invalid_json_returns_note():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="not valid json {{{")]

    with patch("hi_sweetheart.classifier.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_client

        result = await classify(
            message_text="test",
            fetched_content="test content",
            url="https://example.com",
            api_key="test-key",
        )
        assert result.type == "note"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_classifier.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement classifier module**

```python
# src/hi_sweetheart/classifier.py
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

import anthropic

logger = logging.getLogger("hi-sweetheart")

CLASSIFICATION_TYPES = (
    "plugin_install", "marketplace_install", "config_update",
    "bookmark", "podcast", "note", "ignore",
)

MODEL = "claude-sonnet-4-6"
CONFIDENCE_THRESHOLD = 0.5

SYSTEM_PROMPT = """You are a content classifier for a Claude Code automation tool.

Given the content of a URL that was shared via iMessage, classify it into one of these types:
- plugin_install: A Claude Code plugin repository (has package.json with plugin manifest, skills, hooks, etc.)
- marketplace_install: A Claude Code plugin marketplace repository (contains multiple plugins)
- config_update: Contains Claude Code settings, configuration snippets, or tips about config changes
- bookmark: An article, tutorial, documentation, or resource worth saving for later reading
- podcast: An Apple Podcasts link (contains podcasts.apple.com or is clearly a podcast)
- note: A discussion, tip, or anything worth noting but not directly actionable
- ignore: Not related to Claude Code, AI development, or programming

Respond with ONLY a JSON object (no markdown, no code fences):
{
  "type": "<one of the types above>",
  "confidence": <0.0-1.0>,
  "summary": "<one-line description>",
  "action_detail": {
    <type-specific fields>
  }
}

For plugin_install: include "repo_url", "plugin_name", "install_steps" (list of shell commands or instructions extracted from the repo's README)
For marketplace_install: include "repo_url", "marketplace_name", "install_steps"
For config_update: include "settings" (the JSON settings to merge)
For bookmark: include "title", "summary"
For podcast: include "podcast_url", "podcast_name"
For note: include "content" (the key takeaway)
For ignore: action_detail can be empty {}"""


@dataclass
class Classification:
    type: str
    confidence: float
    summary: str
    action_detail: dict = field(default_factory=dict)


async def classify(
    message_text: str,
    fetched_content: str,
    url: str,
    api_key: str,
) -> Classification:
    try:
        client = anthropic.AsyncAnthropic(api_key=api_key)
        response = await client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"URL: {url}\n\nMessage context: {message_text}\n\nFetched content:\n{fetched_content}",
            }],
        )
        raw = response.content[0].text
        data = json.loads(raw)
        classification = Classification(
            type=data.get("type", "note"),
            confidence=data.get("confidence", 0.0),
            summary=data.get("summary", ""),
            action_detail=data.get("action_detail", {}),
        )

        # Low confidence fallback
        if classification.confidence < CONFIDENCE_THRESHOLD and classification.type != "ignore":
            logger.info(
                f"Low confidence ({classification.confidence}) for {url}, "
                f"downgrading {classification.type} -> note"
            )
            classification.type = "note"

        # Validate type
        if classification.type not in CLASSIFICATION_TYPES:
            logger.warning(f"Unknown type '{classification.type}', defaulting to note")
            classification.type = "note"

        return classification

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse classifier response: {e}")
        return Classification(type="note", confidence=0.0, summary=f"Unparseable: {url}")
    except anthropic.APIError as e:
        logger.error(f"Claude API error: {e}")
        raise  # Let caller handle retries
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_classifier.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/hi_sweetheart/classifier.py tests/test_classifier.py
git commit -m "feat: LLM-driven content classifier with confidence threshold"
```

---

### Task 8: Actions Module

**Files:**
- Create: `src/hi_sweetheart/actions.py`
- Create: `tests/test_actions.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_actions.py
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
)
from hi_sweetheart.classifier import Classification
from hi_sweetheart.config import Config


def _make_config(tmp_path) -> Config:
    return Config(
        sender="+15551234567",
        api_key_env="ANTHROPIC_API_KEY",
        mode="auto",
        reading_list_path=tmp_path / "reading-list.md",
        notes_path=tmp_path / "notes.md",
        claude_settings_path=tmp_path / "settings.json",
        claude_plugins_path=tmp_path / "plugins",
        log_path=tmp_path / "runs.log",
        pending_actions_path=tmp_path / "pending.json",
    )


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
def test_action_podcast(mock_subprocess):
    c = Classification(
        type="podcast", confidence=0.95, summary="AI podcast",
        action_detail={"podcast_url": "https://podcasts.apple.com/us/podcast/id123", "podcast_name": "AI Show"},
    )
    action_podcast(c)
    mock_subprocess.run.assert_called_once()
    cmd = mock_subprocess.run.call_args[0][0]
    assert "open" in cmd
    assert "podcasts://" in cmd[1] or "podcasts.apple.com" in cmd[1]


def test_action_config_update(tmp_path):
    config = _make_config(tmp_path)
    # Write existing settings
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
    # Existing keys preserved
    assert settings["permissions"]["allow"] == ["Bash(git:*)"]
    # Backup created
    assert (config.claude_settings_path.with_suffix(".json.bak")).exists()


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

    with patch("hi_sweetheart.actions.action_bookmark") as mock_bm:
        approve_action(action_id, config)
        mock_bm.assert_called_once()

    # Pending list should be empty now
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_actions.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement actions module**

```python
# src/hi_sweetheart/actions.py
from __future__ import annotations

import json
import logging
import subprocess
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from hi_sweetheart.classifier import Classification
from hi_sweetheart.config import Config

logger = logging.getLogger("hi-sweetheart")

SAFE_ACTIONS = {"bookmark", "podcast", "note", "ignore"}
RISKY_ACTIONS = {"plugin_install", "marketplace_install", "config_update"}

ACTION_HANDLERS = {}


def _register(action_type: str):
    def decorator(func):
        ACTION_HANDLERS[action_type] = func
        return func
    return decorator


def execute_action(classification: Classification, config: Config) -> str:
    """Execute or queue an action based on mode. Returns description of what was done."""
    if classification.type == "ignore":
        return "Ignored"

    should_queue = False
    if config.mode == "propose":
        should_queue = True
    elif config.mode == "tiered" and classification.type in RISKY_ACTIONS:
        should_queue = True

    if should_queue:
        queue_pending(classification, config)
        return f"Queued for approval: {classification.summary}"

    return _run_action(classification, config)


def _run_action(classification: Classification, config: Config) -> str:
    handler = ACTION_HANDLERS.get(classification.type)
    if not handler:
        logger.warning(f"No handler for action type: {classification.type}")
        return f"No handler for: {classification.type}"

    try:
        # Some handlers need config, some don't
        if classification.type in ("bookmark", "note", "config_update",
                                    "plugin_install", "marketplace_install"):
            handler(classification, config)
        else:
            handler(classification)
        return f"Executed: {classification.summary}"
    except Exception as e:
        logger.error(f"Action failed ({classification.type}): {e}")
        raise


@_register("bookmark")
def action_bookmark(classification: Classification, config: Config):
    path = config.reading_list_path
    path.parent.mkdir(parents=True, exist_ok=True)
    detail = classification.action_detail
    entry = f"\n## {detail.get('title', 'Untitled')}\n\n{detail.get('summary', '')}\n"
    if path.exists():
        existing = path.read_text()
        path.write_text(existing + entry)
    else:
        path.write_text(f"# Reading List\n{entry}")
    logger.info(f"Bookmarked: {detail.get('title', 'unknown')}")


@_register("note")
def action_note(classification: Classification, config: Config):
    path = config.notes_path
    path.parent.mkdir(parents=True, exist_ok=True)
    detail = classification.action_detail
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    entry = f"\n## {timestamp} — {classification.summary}\n\n{detail.get('content', '')}\n"
    if path.exists():
        existing = path.read_text()
        path.write_text(existing + entry)
    else:
        path.write_text(f"# Notes\n{entry}")
    logger.info(f"Noted: {classification.summary}")


@_register("podcast")
def action_podcast(classification: Classification):
    detail = classification.action_detail
    url = detail.get("podcast_url", "")
    # Convert to podcasts:// scheme for subscribing
    if "podcasts.apple.com" in url:
        subscribe_url = url.replace("https://", "podcasts://")
    else:
        subscribe_url = url
    subprocess.run(["open", subscribe_url], capture_output=True, timeout=10)
    logger.info(f"Subscribed to podcast: {detail.get('podcast_name', 'unknown')}")


@_register("config_update")
def action_config_update(classification: Classification, config: Config):
    path = config.claude_settings_path
    if not path.exists():
        logger.error(f"Settings file not found: {path}")
        return

    # Backup before modifying
    backup = path.with_suffix(".json.bak")
    backup.write_text(path.read_text())
    logger.info(f"Backed up settings to {backup}")

    existing = json.loads(path.read_text())
    new_settings = classification.action_detail.get("settings", {})
    merged = _deep_merge(existing, new_settings)
    path.write_text(json.dumps(merged, indent=2) + "\n")
    logger.info(f"Updated settings: {list(new_settings.keys())}")


@_register("plugin_install")
def action_plugin_install(classification: Classification, config: Config):
    detail = classification.action_detail
    steps = detail.get("install_steps", [])
    if not steps:
        logger.warning("No install steps provided for plugin install")
        return
    for step in steps:
        logger.info(f"Running install step: {step}")
        result = subprocess.run(
            step, shell=True, capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            logger.error(f"Install step failed: {step}\nstderr: {result.stderr}")
            raise RuntimeError(f"Install step failed: {step}")
        logger.info(f"Step output: {result.stdout.strip()}")
    logger.info(f"Installed plugin: {detail.get('plugin_name', 'unknown')}")


@_register("marketplace_install")
def action_marketplace_install(classification: Classification, config: Config):
    # Same pattern as plugin_install — LLM provides the steps
    action_plugin_install(classification, config)


def _deep_merge(base: dict, override: dict) -> dict:
    result = deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        elif key in result and isinstance(result[key], list) and isinstance(value, list):
            result[key] = result[key] + value
        else:
            result[key] = value
    return result


# --- Pending actions queue ---

def queue_pending(classification: Classification, config: Config):
    pending = load_pending(config)
    entry = {
        "id": str(uuid.uuid4())[:8],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "classification": {
            "type": classification.type,
            "confidence": classification.confidence,
            "summary": classification.summary,
            "action_detail": classification.action_detail,
        },
    }
    pending.append(entry)
    _save_pending(pending, config)
    logger.info(f"Queued pending action: {entry['id']} ({classification.type})")


def load_pending(config: Config) -> list[dict]:
    path = config.pending_actions_path
    if not path.exists():
        return []
    return json.loads(path.read_text())


def approve_action(action_id: str, config: Config):
    pending = load_pending(config)
    action = None
    remaining = []
    for p in pending:
        if p["id"] == action_id:
            action = p
        else:
            remaining.append(p)

    if action is None:
        raise ValueError(f"Pending action not found: {action_id}")

    c = Classification(**action["classification"])
    # Force auto mode for execution
    original_mode = config.mode
    config.mode = "auto"
    try:
        _run_action(c, config)
    finally:
        config.mode = original_mode

    _save_pending(remaining, config)
    logger.info(f"Approved and executed action: {action_id}")


def reject_action(action_id: str, config: Config):
    pending = load_pending(config)
    remaining = [p for p in pending if p["id"] != action_id]
    if len(remaining) == len(pending):
        raise ValueError(f"Pending action not found: {action_id}")
    _save_pending(remaining, config)
    logger.info(f"Rejected action: {action_id}")


def _save_pending(pending: list[dict], config: Config):
    path = config.pending_actions_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pending, indent=2))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_actions.py -v
```

Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/hi_sweetheart/actions.py tests/test_actions.py
git commit -m "feat: action executors with pending queue and deep merge"
```

---

### Task 9: Main Orchestrator + CLI

**Files:**
- Create: `src/hi_sweetheart/main.py`
- Create: `tests/test_main.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_main.py
import asyncio
import json
import sqlite3
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock
from hi_sweetheart.main import run_pipeline, main


def _setup_environment(tmp_path) -> dict:
    """Create config, state dir, and mock iMessage DB."""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "sender": "+15551234567",
        "api_key_env": "TEST_API_KEY",
        "mode": "auto",
        "reading_list_path": str(tmp_path / "reading-list.md"),
        "notes_path": str(tmp_path / "notes.md"),
        "claude_settings_path": str(tmp_path / "settings.json"),
        "claude_plugins_path": str(tmp_path / "plugins"),
        "log_path": str(tmp_path / "runs.log"),
        "pending_actions_path": str(tmp_path / "pending.json"),
    }))

    state_path = tmp_path / "state.json"

    # Create mock iMessage DB
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
    conn.execute("INSERT INTO message (ROWID, text, handle_id, date, is_from_me) VALUES (1, 'check this https://example.com/article', 1, 0, 0)")
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
         patch("hi_sweetheart.main.send_notification"), \
         patch.dict("os.environ", {"TEST_API_KEY": "sk-test"}):

        await run_pipeline(
            config_path=env["config_path"],
            state_path=env["state_path"],
            db_path=env["db_path"],
        )

    # Reading list should have the bookmark
    reading_list = (tmp_path / "reading-list.md").read_text()
    assert "Prompting" in reading_list

    # State should be advanced
    state = json.loads(env["state_path"].read_text())
    assert state["last_message_rowid"] == 1


@pytest.mark.asyncio
async def test_run_pipeline_no_new_messages(tmp_path):
    env = _setup_environment(tmp_path)
    # Set state to already processed
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
        # Should still notify (no new messages)
        mock_notify.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_main.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement main module**

```python
# src/hi_sweetheart/main.py
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from hi_sweetheart.actions import (
    execute_action,
    load_pending,
    approve_action,
    reject_action,
)
from hi_sweetheart.classifier import classify
from hi_sweetheart.config import Config, ConfigError, load_config
from hi_sweetheart.fetcher import extract_urls, fetch_content, has_actionable_content
from hi_sweetheart.notify import RunSummary, send_notification, setup_logging
from hi_sweetheart.reader import IMESSAGE_DB_PATH, read_messages
from hi_sweetheart.state import State

logger = logging.getLogger("hi-sweetheart")

DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent / "config.json"
DEFAULT_STATE_PATH = Path.home() / ".hi-sweetheart" / "state.json"


async def run_pipeline(
    config_path: Path = DEFAULT_CONFIG_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    db_path: Path = IMESSAGE_DB_PATH,
    mode_override: str | None = None,
):
    config = load_config(config_path)
    if mode_override:
        config.mode = mode_override

    log = setup_logging(config.log_path)
    log.info("=== hi-sweetheart run started ===")

    state = State(state_path)
    summary = RunSummary()

    api_key = os.environ.get(config.api_key_env, "")
    if not api_key:
        log.error(f"API key not found in env var: {config.api_key_env}")
        send_notification("hi-sweetheart", f"ERROR: {config.api_key_env} not set")
        return

    try:
        messages = read_messages(db_path, sender=config.sender, after_rowid=state.last_message_rowid)
    except Exception as e:
        log.error(f"Failed to read iMessage DB: {e}")
        summary.add_error(f"DB read failed: {e}")
        send_notification("hi-sweetheart", summary.format())
        return

    log.info(f"Found {len(messages)} new messages")

    if not messages:
        send_notification("hi-sweetheart", summary.format())
        return

    for msg in messages:
        log.info(f"Processing message {msg.rowid}: {msg.text[:80]}...")
        try:
            urls = extract_urls(msg.text)

            if not urls and not has_actionable_content(msg.text):
                log.info(f"Message {msg.rowid}: no URLs or actionable content, skipping")
                state.update(msg.rowid)
                state.save()
                continue

            if urls:
                for url in urls:
                    log.info(f"Fetching: {url}")
                    fetch_result = await fetch_content(url)

                    if not fetch_result.success:
                        log.warning(f"Fetch failed for {url}: {fetch_result.error}")
                        summary.add_error(f"Fetch failed: {url}")
                        continue

                    log.info(f"Classifying content from {url}")
                    classification = await classify(
                        message_text=msg.text,
                        fetched_content=fetch_result.text,
                        url=url,
                        api_key=api_key,
                    )
                    log.info(f"Classified as: {classification.type} ({classification.confidence})")

                    result = execute_action(classification, config)
                    summary.add(classification.type, result)
            else:
                # Actionable text content without URL
                log.info(f"Classifying text content directly")
                classification = await classify(
                    message_text=msg.text,
                    fetched_content=msg.text,
                    url="(no url)",
                    api_key=api_key,
                )
                result = execute_action(classification, config)
                summary.add(classification.type, result)

            state.update(msg.rowid)
            state.save()

        except Exception as e:
            log.error(f"Failed to process message {msg.rowid}: {e}")
            summary.add_error(f"Message {msg.rowid}: {e}")
            # Still advance ROWID on error (per spec: action failures don't block)
            state.update(msg.rowid)
            state.save()

    log.info("=== Run complete ===")
    notification_text = summary.format()
    log.info(notification_text)
    send_notification("hi-sweetheart", notification_text)


def cmd_run(args):
    asyncio.run(run_pipeline(
        config_path=Path(args.config),
        state_path=Path(args.state).expanduser(),
        mode_override=args.mode,
    ))


def cmd_pending(args):
    config = load_config(Path(args.config))
    pending = load_pending(config)
    if not pending:
        print("No pending actions.")
        return
    for p in pending:
        c = p["classification"]
        print(f"  [{p['id']}] {c['type']} — {c['summary']} (confidence: {c['confidence']})")


def cmd_approve(args):
    config = load_config(Path(args.config))
    approve_action(args.id, config)
    print(f"Approved and executed: {args.id}")


def cmd_reject(args):
    config = load_config(Path(args.config))
    reject_action(args.id, config)
    print(f"Rejected: {args.id}")


def cmd_log(args):
    config = load_config(Path(args.config))
    if not config.log_path.exists():
        print("No log file found.")
        return
    # Show last 50 lines
    lines = config.log_path.read_text().splitlines()
    for line in lines[-50:]:
        print(line)


def main():
    parser = argparse.ArgumentParser(prog="hi-sweetheart", description="iMessage reader + Claude action agent")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config.json")
    parser.add_argument("--state", default=str(DEFAULT_STATE_PATH), help="Path to state.json")

    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Execute one pipeline run")
    run_parser.add_argument("--mode", choices=["auto", "tiered", "propose"], help="Override execution mode")
    run_parser.set_defaults(func=cmd_run)

    pending_parser = subparsers.add_parser("pending", help="List pending actions")
    pending_parser.set_defaults(func=cmd_pending)

    approve_parser = subparsers.add_parser("approve", help="Approve a pending action")
    approve_parser.add_argument("id", help="Action ID to approve")
    approve_parser.set_defaults(func=cmd_approve)

    reject_parser = subparsers.add_parser("reject", help="Reject a pending action")
    reject_parser.add_argument("id", help="Action ID to reject")
    reject_parser.set_defaults(func=cmd_reject)

    log_parser = subparsers.add_parser("log", help="Show recent run history")
    log_parser.set_defaults(func=cmd_log)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        args.func(args)
    except ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_main.py -v
```

Expected: 2 passed

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/ -v
```

Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add src/hi_sweetheart/main.py tests/test_main.py
git commit -m "feat: CLI orchestrator with run/pending/approve/reject/log commands"
```

---

### Task 10: launchd Plist + Final Wiring

**Files:**
- Create: `com.hi-sweetheart.plist`

- [ ] **Step 1: Create launchd plist template**

The plist needs the actual path to the Python venv on the target Mac. Use a placeholder that the user fills in.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.hi-sweetheart</string>
    <key>ProgramArguments</key>
    <array>
        <!-- UPDATE: path to your venv Python -->
        <string>/path/to/hi-sweetheart/.venv/bin/python</string>
        <string>-m</string>
        <string>hi_sweetheart.main</string>
        <string>run</string>
    </array>
    <key>WorkingDirectory</key>
    <!-- UPDATE: path to hi-sweetheart project -->
    <string>/path/to/hi-sweetheart</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>ANTHROPIC_API_KEY</key>
        <!-- UPDATE: your API key or use keychain -->
        <string>sk-ant-...</string>
    </dict>
    <key>StartCalendarInterval</key>
    <array>
        <dict>
            <key>Hour</key>
            <integer>9</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>19</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>23</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
    </array>
    <key>StandardOutPath</key>
    <string>/tmp/hi-sweetheart-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/hi-sweetheart-stderr.log</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
```

- [ ] **Step 2: Verify plist syntax**

```bash
plutil -lint com.hi-sweetheart.plist 2>/dev/null || echo "plutil not available (Linux) — will verify on Mac"
```

- [ ] **Step 3: Commit**

```bash
git add com.hi-sweetheart.plist
git commit -m "feat: launchd plist template for 9am/7pm/11pm schedule"
```

---

### Task 11: Integration Test + Manual Smoke Test

**Files:**
- Modify: `tests/test_main.py` (add integration test)

- [ ] **Step 1: Add integration test that runs full pipeline with mocks**

Add to `tests/test_main.py`:

```python
@pytest.mark.asyncio
async def test_full_pipeline_tiered_mode(tmp_path):
    """Integration test: tiered mode queues risky action, executes safe one."""
    env = _setup_environment(tmp_path)
    # Add a second message with a plugin link
    conn = sqlite3.connect(str(env["db_path"]))
    conn.execute("INSERT INTO message (ROWID, text, handle_id, date, is_from_me) VALUES (2, 'try this plugin https://github.com/foo/bar', 1, 0, 0)")
    conn.execute("INSERT INTO chat_message_join (chat_id, message_id) VALUES (1, 2)")
    conn.commit()
    conn.close()

    call_count = 0

    async def mock_classify(message_text, fetched_content, url, api_key):
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

    with patch("hi_sweetheart.main.fetch_content", mock_fetch), \
         patch("hi_sweetheart.main.classify", mock_classify), \
         patch("hi_sweetheart.main.send_notification"), \
         patch.dict("os.environ", {"TEST_API_KEY": "sk-test"}):

        # Override config to tiered mode
        config_data = json.loads(env["config_path"].read_text())
        config_data["mode"] = "tiered"
        env["config_path"].write_text(json.dumps(config_data))

        await run_pipeline(
            config_path=env["config_path"],
            state_path=env["state_path"],
            db_path=env["db_path"],
        )

    # Bookmark should have been auto-executed
    assert (tmp_path / "reading-list.md").exists()

    # Plugin install should be queued
    pending = json.loads((tmp_path / "pending.json").read_text())
    assert len(pending) == 1
    assert pending[0]["classification"]["type"] == "plugin_install"
```

- [ ] **Step 2: Run full test suite**

```bash
pytest tests/ -v
```

Expected: All tests pass

- [ ] **Step 3: Manual smoke test**

```bash
source .venv/bin/activate
hi-sweetheart --help
hi-sweetheart run --help
hi-sweetheart pending --config config.json.example 2>&1 || echo "Expected: config error or no pending"
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_main.py
git commit -m "test: integration test for tiered mode pipeline"
```

---

## Execution Order Summary

| Task | Component | Dependencies |
|---|---|---|
| 1 | Project scaffold | None |
| 2 | Config | Task 1 |
| 3 | State | Task 1 |
| 4 | Notify | Task 1 |
| 5 | Reader | Task 1 |
| 6 | Fetcher | Task 1 |
| 7 | Classifier | Task 1 |
| 8 | Actions | Tasks 2, 7 |
| 9 | Main orchestrator | Tasks 2-8 |
| 10 | launchd plist | Task 9 |
| 11 | Integration tests | Task 9 |

Tasks 2-7 can be implemented in parallel (they only depend on Task 1). Tasks 8-11 are sequential.

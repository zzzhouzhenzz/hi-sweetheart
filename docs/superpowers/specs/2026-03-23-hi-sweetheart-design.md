# hi-sweetheart Design Spec

## Overview

Standalone Python agent running as a macOS launchd cron job (9am, 7pm, 11pm daily). Reads iMessages from a configured sender, fetches linked content, uses Claude API to classify intent, and executes actions automatically.

**Prerequisites:** macOS Full Disk Access must be granted to the terminal/Python process running hi-sweetheart, otherwise `chat.db` reads will fail with a permission error.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Logger + Notifier                      │
│                                                          │
│  ┌─────────────┐    ┌──────────┐    ┌──────────────┐    │
│  │ iMessage DB │───▶│ URL      │───▶│ Claude       │    │
│  │ Reader      │    │ Fetcher  │    │ Classifier   │    │
│  └─────────────┘    └──────────┘    └──────────────┘    │
│                                           │              │
│                                           ▼              │
│                                     ┌──────────┐        │
│                                     │ Action   │        │
│                                     │ Runner   │        │
│                                     └──────────┘        │
└──────────────────────────────────────────────────────────┘
```

Logger + Notifier is cross-cutting — every step logs what it's doing and surfaces errors immediately. Final macOS notification summarizes the full run.

## Pipeline

1. Open `~/Library/Messages/chat.db` (read-only, `?mode=ro` URI)
2. Query new messages from configured sender since last processed ROWID
3. Extract URLs from messages
4. Fetch URL content (pages, READMEs, etc.)
5. Send fetched content to Claude API for classification
6. Execute actions based on classification and execution mode
7. Update state ROWID (per-message, not per-batch — see Error Handling)
8. Log results + send macOS notification

## iMessage DB Query

Match sender by `handle.id` against the configured phone number/Apple ID. Filter to **1:1 chats only** — group chat messages from the sender are ignored.

Open with `sqlite3.connect("file:...?mode=ro", uri=True)` and handle `SQLITE_BUSY` with a short retry (WAL mode contention from active iMessage writes).

## Action Types

Classification is LLM-driven based on **fetched link content**, not message text.

| Type | What the link points to | Action |
|---|---|---|
| `plugin_install` | A Claude Code plugin repo | LLM reads the repo's README/install docs, extracts the recommended installation steps, and executes them (may involve marketplace add, git clone, build commands, config changes — whatever the repo recommends) |
| `marketplace_install` | A plugin marketplace repo | LLM reads the marketplace repo docs, adds to `extraKnownMarketplaces` in `settings.json`, then follows the repo's instructions to install and enable available plugins |
| `config_update` | Settings snippet, blog post with config tips | Deep merge into `~/.claude/settings.json`. New keys added, existing scalar values overwritten, arrays appended, objects merged recursively. Backup created before write. |
| `bookmark` | Article, doc, tutorial | Save URL + LLM summary to configurable reading list path |
| `podcast` | Apple Podcasts link | Subscribe via `open "podcasts://"` URL scheme (triggers Apple Podcasts to add/subscribe) |
| `note` | Discussion thread, tip, anything worth remembering | Save to notes file |
| `ignore` | Not Claude-related | Skip |

Messages without links are sent to the classifier only if they contain patterns suggesting actionable content (JSON-like braces, code blocks). Otherwise `ignore` without an API call.

## Classification Contract

Model: `claude-sonnet-4-6` (cost-efficient for classification, runs 3x/day).

Prompt sends the fetched content and asks for a JSON response:

```json
{
  "type": "plugin_install | marketplace_install | config_update | bookmark | podcast | note | ignore",
  "confidence": 0.0-1.0,
  "summary": "One-line description of what this is",
  "action_detail": {
    // type-specific fields, e.g.:
    // plugin_install: {"repo_url": "...", "plugin_name": "...", "install_steps": ["step1", "step2"]}
    // marketplace_install: {"repo_url": "...", "marketplace_name": "...", "install_steps": ["step1", "step2"]}
    // config_update: {"settings": {...}}
    // bookmark: {"title": "...", "summary": "..."}
    // podcast: {"podcast_url": "...", "podcast_name": "..."}
  }
}
```

Low confidence (<0.5) items are classified as `note` regardless of detected type — safe fallback.

## Error Handling

- **Per-message processing:** Each message is processed independently. A failed URL fetch or action does not block other messages.
- **ROWID advances per message:** After each message is successfully processed (or explicitly skipped due to error), the ROWID advances. Failed messages are logged with full context for manual review.
- **URL fetch failures:** 404, timeout, auth-required → log the error, classify message as `note` with the raw URL for manual review.
- **Claude API failures:** Rate limit / 500 / network error → retry up to 3 times with exponential backoff. If still failing, abort the run (don't advance ROWID for unprocessed messages). Next run picks up where this one stopped.
- **Action execution failures:** Log the error, send a notification, continue to next message. The message is considered processed (ROWID advances) but the failed action is logged.

## Execution Modes

Three modes, configurable, default `auto`:

- **`auto`** — LLM decides and executes all actions. Review the log later.
- **`tiered`** — auto-execute safe actions (bookmark, podcast, note), queue risky ones (plugin_install, marketplace_install, config_update) to `pending_actions_path` for approval.
- **`propose`** — everything queues for approval, nothing auto-executes.

## CLI

- `hi-sweetheart run` — execute one pipeline run (same as cron)
- `hi-sweetheart run --mode propose` — override mode for this run
- `hi-sweetheart pending` — list pending actions (from tiered/propose mode)
- `hi-sweetheart approve <id>` — approve and execute a pending action
- `hi-sweetheart reject <id>` — reject and remove a pending action
- `hi-sweetheart log` — show recent run history

## Config

`hi-sweetheart/config.json` (gitignored, `.example` checked in):

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

All paths support `~` expansion.

## State Management

`~/.hi-sweetheart/state.json`:

```json
{
  "last_message_rowid": 12345,
  "last_run": "2026-03-23T09:00:00Z"
}
```

- ROWID advances per-message after successful processing
- On first run (no state file), processes messages from the last 24 hours only

## Scheduling

macOS launchd plist at `~/Library/LaunchAgents/com.hi-sweetheart.plist`:

- Runs at 09:00, 19:00, 23:00 daily
- Launches Python script from project venv
- `StandardOutPath` / `StandardErrorPath` to log dir
- `RunAtLoad: false`

Installation: `launchctl load ~/Library/LaunchAgents/com.hi-sweetheart.plist`

Manual run: `hi-sweetheart run`

## Project Structure

```
hi-sweetheart/
├── config.json.example
├── pyproject.toml
├── src/hi_sweetheart/
│   ├── __init__.py
│   ├── main.py              # CLI entry point, orchestrator
│   ├── reader.py             # iMessage DB queries
│   ├── fetcher.py            # URL extraction + content fetching
│   ├── classifier.py         # Claude API classification
│   ├── actions.py            # Action executors (plugin, config, podcast, etc.)
│   ├── notify.py             # macOS notifications + logging
│   └── state.py              # State management (last_message_rowid)
├── tests/
├── com.hi-sweetheart.plist   # launchd template
└── docs/
```

## Dependencies

- `anthropic` — Claude API client
- `httpx` — URL fetching
- `beautifulsoup4` — HTML content extraction
- Python stdlib: `sqlite3`, `subprocess`, `json`, `pathlib`, `logging`

## Known Limitations

- **JavaScript-heavy pages:** `httpx` + `bs4` only works for server-rendered content. For GitHub repos, use the GitHub API to fetch README content directly.
- **Apple Podcasts subscription:** Uses `open "podcasts://"` URL scheme which triggers the app to open and subscribe. No programmatic confirmation that subscription succeeded.
- **chat.db locking:** SQLite WAL mode means occasional `SQLITE_BUSY` — handled with retry.

# Hi Sweetheart

Reads iMessages from a specific sender, classifies links using Claude, and presents them in a dashboard UI.

## How it works

1. Reads new messages from iMessage database
2. Extracts URLs (messages without links are skipped)
3. Fetches page content and classifies each URL via `claude -p`
4. Writes items to `~/.hi-sweetheart/items.md` — a single markdown file that serves as the database
5. Podcast links are saved to Apple Podcasts via JXA automation and marked done automatically

## Item types

| Emoji | Type | Status |
|-------|------|--------|
| 🔖 | bookmark | pending |
| 🎧 | podcast | done (auto-saved) |
| 📝 | note | pending |
| 🔌 | plugin_install | pending |
| 🏪 | marketplace_install | pending |
| ⚙️ | config_update | pending |

## Usage

```bash
# Process new messages
hi-sweetheart run

# Preview without side effects
hi-sweetheart run --dry-run

# Clear state and items, next run loads last 3 days
hi-sweetheart reset

# Show recent log
hi-sweetheart log

# Open the dashboard UI
python -m hi_sweetheart.server
```

## Dashboard

Dark-themed web UI at `http://localhost:8788` with:
- Two views: **By Time** and **By Type**
- One line per item: emoji + linked title + summary
- Done/undo buttons for each item
- All state persisted in `items.md`

## Items file format

```markdown
# Hi Sweetheart

* 🔖 [Article Title](https://url) | summary | bookmark | 2026-03-24 12:00 | pending
* 🎧 [Podcast Episode](https://url) | description | podcast | 2026-03-24 11:00 | done
```

## Configuration

`config.json` (gitignored):

```json
{
  "sender": "+1234567890",
  "mode": "auto",
  "items_path": "~/.hi-sweetheart/items.md",
  "log_path": "~/.hi-sweetheart/runs.log",
  "pending_actions_path": "~/.hi-sweetheart/pending.json"
}
```

`items_path` is optional — defaults to `~/.hi-sweetheart/items.md`.

## Setup

```bash
pip install -e .
```

Requires macOS (iMessage database access) and [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code).

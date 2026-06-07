# Hi Sweetheart Agent Guide

## Purpose

Hi Sweetheart reads links from iMessage, classifies them, records actionable
items in Markdown, and presents them in a local dashboard. It runs on macOS
because it accesses the iMessage database and Apple Podcasts automation.

## Architecture

- Python package configured by `pyproject.toml`.
- `~/.hi-sweetheart/items.md` is the persistent item store.
- The local dashboard runs at `http://localhost:8788`.
- `config.json` contains local sender and path configuration and must remain
  untracked.

The current classifier invokes Claude CLI. Treat that as a provider boundary:
when migrating to Codex, preserve classification behavior and make the provider
explicit and testable rather than scattering CLI assumptions through the code.

## Critical Product Rule

For podcast links, perform the Apple Podcasts bookmark/save action only. Never
subscribe to or follow a show or episode. Bookmarking and subscribing are
different actions, and subscribing is not an acceptable fallback.

## Development

```bash
source .venv/bin/activate
pip install -e .
pytest
```

Use `hi-sweetheart run --dry-run` to validate processing without side effects.
Keep macOS automation covered by focused tests or explicit dry-run verification.

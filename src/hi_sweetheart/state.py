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

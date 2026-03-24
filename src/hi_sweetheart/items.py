"""Items markdown database — single file stores all hi-sweetheart items.

Format (one line per item):
  * EMOJI [Title](url) | summary | type | 2026-03-24 12:00 | status

Status: pending | done
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

EMOJI_MAP = {
    "bookmark": "\U0001f516",
    "podcast": "\U0001f3a7",
    "note": "\U0001f4dd",
    "config_update": "\u2699\ufe0f",
    "plugin_install": "\U0001f50c",
    "marketplace_install": "\U0001f3ea",
}

AUTO_DONE_TYPES = {"podcast"}


@dataclass
class Item:
    emoji: str
    title: str
    url: str
    summary: str
    action_type: str
    timestamp: str
    status: str


_ITEM_RE = re.compile(
    r"\*\s+(\S+)\s+\[(.+?)\]\((.+?)\)\s*\|\s*(.+?)\s*\|\s*([\w_]+)\s*\|\s*([\d-]+ [\d:]+)\s*\|\s*(\w+)"
)


def parse_item(line: str) -> Item | None:
    m = _ITEM_RE.match(line.strip())
    if not m:
        return None
    return Item(
        emoji=m.group(1),
        title=m.group(2),
        url=m.group(3),
        summary=m.group(4).strip(),
        action_type=m.group(5),
        timestamp=m.group(6),
        status=m.group(7),
    )


def format_item(item: Item) -> str:
    return (
        f"* {item.emoji} [{item.title}]({item.url}) "
        f"| {item.summary} | {item.action_type} | {item.timestamp} | {item.status}"
    )


def read_items(path: Path) -> list[Item]:
    if not path.exists():
        return []
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("* "):
            item = parse_item(line)
            if item:
                items.append(item)
    return items


def write_items(path: Path, items: list[Item]):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Hi Sweetheart\n\n"]
    for item in items:
        lines.append(format_item(item) + "\n")
    path.write_text("".join(lines), encoding="utf-8")


def add_item(path: Path, item: Item):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("# Hi Sweetheart\n\n", encoding="utf-8")
    with open(path, "a", encoding="utf-8") as f:
        f.write(format_item(item) + "\n")


def mark_done(path: Path, index: int):
    items = read_items(path)
    if 0 <= index < len(items):
        items[index].status = "done"
        write_items(path, items)


def mark_undone(path: Path, index: int):
    items = read_items(path)
    if 0 <= index < len(items):
        items[index].status = "pending"
        write_items(path, items)


def make_item(
    action_type: str,
    title: str,
    url: str,
    summary: str,
    auto_done: bool = False,
) -> Item:
    emoji = EMOJI_MAP.get(action_type, "\U0001f4cc")
    status = "done" if (auto_done or action_type in AUTO_DONE_TYPES) else "pending"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    return Item(
        emoji=emoji, title=title, url=url, summary=summary,
        action_type=action_type, timestamp=timestamp, status=status,
    )


def to_dicts(items: list[Item]) -> list[dict]:
    return [asdict(i) for i in items]

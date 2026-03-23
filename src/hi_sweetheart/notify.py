from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


def setup_logging(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("hi-sweetheart")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    handler = logging.FileHandler(log_path)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(handler)
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
    # Escape quotes for osascript to prevent injection
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
    safe_body = body.replace("\\", "\\\\").replace('"', '\\"')
    try:
        subprocess.run([
            "osascript", "-e",
            f'display notification "{safe_body}" with title "{safe_title}"',
        ], capture_output=True, timeout=5)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        logging.getLogger("hi-sweetheart").warning(
            "Could not send macOS notification (osascript unavailable)"
        )

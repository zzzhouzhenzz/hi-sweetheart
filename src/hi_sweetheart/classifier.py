from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass, field

logger = logging.getLogger("hi-sweetheart")

CLASSIFICATION_TYPES = (
    "plugin_install", "marketplace_install", "config_update",
    "bookmark", "podcast", "note", "ignore",
)

CONFIDENCE_THRESHOLD = 0.5
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 1.0

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


class ClassifyAPIError(Exception):
    """Raised when claude -p fails after all retries."""
    pass


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
    api_key: str = "",  # kept for interface compat, unused with claude -p
) -> Classification:
    prompt = f"URL: {url}\n\nMessage context: {message_text}\n\nFetched content:\n{fetched_content}"

    for attempt in range(MAX_RETRIES):
        try:
            result = subprocess.run(
                [
                    "claude", "-p",
                    "--model", "sonnet",
                    "--output-format", "text",
                    "--system-prompt", SYSTEM_PROMPT,
                    "--dangerously-skip-permissions",
                ],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                raise RuntimeError(f"claude -p exited {result.returncode}: {result.stderr.strip()}")

            raw = result.stdout.strip()
            return _parse_response(raw, url)

        except (RuntimeError, subprocess.TimeoutExpired, FileNotFoundError) as e:
            if attempt < MAX_RETRIES - 1:
                delay = INITIAL_RETRY_DELAY * (2 ** attempt)
                logger.warning(f"claude -p error (attempt {attempt + 1}/{MAX_RETRIES}): {e}. Retrying in {delay}s...")
                time.sleep(delay)
            else:
                logger.error(f"claude -p failed after {MAX_RETRIES} attempts: {e}")
                raise ClassifyAPIError(f"claude -p failed after {MAX_RETRIES} retries: {e}") from e


def _parse_response(raw: str, url: str) -> Classification:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse classifier response: {e}")
        return Classification(type="note", confidence=0.0, summary=f"Unparseable response for: {url}")

    classification = Classification(
        type=data.get("type", "note"),
        confidence=data.get("confidence", 0.0),
        summary=data.get("summary", ""),
        action_detail=data.get("action_detail", {}),
    )

    if classification.confidence < CONFIDENCE_THRESHOLD and classification.type != "ignore":
        logger.info(
            f"Low confidence ({classification.confidence}) for {url}, "
            f"downgrading {classification.type} -> note"
        )
        classification.type = "note"

    if classification.type not in CLASSIFICATION_TYPES:
        logger.warning(f"Unknown type '{classification.type}', defaulting to note")
        classification.type = "note"

    return classification

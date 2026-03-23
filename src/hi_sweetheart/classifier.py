from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass, field

logger = logging.getLogger("hi-sweetheart")

CLASSIFICATION_TYPES = (
    "podcast", "note", "ignore",
)

CONFIDENCE_THRESHOLD = 0.5
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 1.0
MAX_CONTENT_CHARS = 4000  # Cap content to avoid truncated classifier output

SYSTEM_PROMPT = """You are a content classifier for a personal iMessage link curator.

Given the content of a URL shared via iMessage, classify it into one of these types:
- podcast: An Apple Podcasts link (contains podcasts.apple.com or is clearly a podcast)
- note: Anything worth saving — articles, tools, repos, tips, tutorials, discussions, config advice, etc.
- ignore: Not related to tech, AI, programming, or anything the user would find useful

Respond with ONLY a JSON object (no markdown, no code fences):
{
  "type": "<one of the types above>",
  "confidence": <0.0-1.0>,
  "summary": "<one-line description>",
  "action_detail": {
    <type-specific fields>
  }
}

For podcast: include "podcast_url", "podcast_name"
For note: include "content" (the key takeaway — be specific and informative)
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
) -> Classification:
    return await _classify_with_claude_cli(message_text, fetched_content, url)


async def _classify_with_claude_cli(
    message_text: str,
    fetched_content: str,
    url: str,
) -> Classification:
    """Classify using claude -p CLI (text-only, fast, low cost)."""
    content = fetched_content[:MAX_CONTENT_CHARS]
    prompt = f"URL: {url}\n\nMessage context: {message_text}\n\nFetched content:\n{content}"

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



def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences (```json ... ```) from response."""
    text = text.strip()
    if text.startswith("```"):
        # Remove opening fence (```json or ```)
        first_newline = text.index("\n")
        text = text[first_newline + 1:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _extract_first_json(text: str) -> dict | None:
    """Extract the first valid JSON object from text that may have trailing content."""
    # Find the first '{' and try progressively larger slices
    start = text.find("{")
    if start == -1:
        return None
    # Walk backwards from the end, finding each '}' to try parsing
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    continue
    return None


def _parse_response(raw: str, url: str) -> Classification:
    cleaned = _strip_code_fences(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try extracting first JSON object (handles trailing text, extra data)
        data = _extract_first_json(cleaned)
        if data is None:
            logger.error(f"Failed to parse classifier response for {url}: {raw[:200]}")
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

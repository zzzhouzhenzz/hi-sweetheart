from __future__ import annotations

import json
import logging
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

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
    images: list[bytes] | None = None,
) -> Classification:
    # Use Anthropic SDK with vision when images are available
    if images:
        return await _classify_with_vision(message_text, fetched_content, url, images)

    return await _classify_with_claude_cli(message_text, fetched_content, url)


async def _classify_with_claude_cli(
    message_text: str,
    fetched_content: str,
    url: str,
) -> Classification:
    """Classify using claude -p CLI (text-only, fast, low cost)."""
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


async def _classify_with_vision(
    message_text: str,
    fetched_content: str,
    url: str,
    images: list[bytes],
) -> Classification:
    """Classify using claude -p with images saved as temp files.

    claude -p can read local image files referenced by path in the prompt.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        image_paths = []
        for i, img_bytes in enumerate(images):
            path = Path(tmpdir) / f"image_{i}.jpg"
            path.write_bytes(img_bytes)
            image_paths.append(str(path))

        image_refs = "\n".join(f"- {p}" for p in image_paths)
        prompt = (
            f"URL: {url}\n\n"
            f"Message context: {message_text}\n\n"
            f"Page metadata:\n{fetched_content}\n\n"
            f"The post contains these images with text content. "
            f"Read the text in each image to understand the full post:\n{image_refs}"
        )

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
                    timeout=120,
                )

                if result.returncode != 0:
                    raise RuntimeError(f"claude -p exited {result.returncode}: {result.stderr.strip()}")

                raw = result.stdout.strip()
                logger.info(f"Vision classifier response for {url}: {raw[:100]}...")
                return _parse_response(raw, url)

            except (RuntimeError, subprocess.TimeoutExpired, FileNotFoundError) as e:
                if attempt < MAX_RETRIES - 1:
                    delay = INITIAL_RETRY_DELAY * (2 ** attempt)
                    logger.warning(f"Vision classify error (attempt {attempt + 1}/{MAX_RETRIES}): {e}. Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    logger.error(f"Vision classify failed after {MAX_RETRIES} attempts: {e}")
                    raise ClassifyAPIError(f"Vision classify failed after {MAX_RETRIES} retries: {e}") from e


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


def _parse_response(raw: str, url: str) -> Classification:
    try:
        data = json.loads(_strip_code_fences(raw))
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

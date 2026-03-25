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
MAX_CONTENT_CHARS = 4000  # Cap content to avoid truncated classifier output
BATCH_SIZE = 10

_CLASSIFICATION_INSTRUCTIONS = """Classify into one of these types:
- plugin_install: A Claude Code plugin repository (has package.json with plugin manifest, skills, hooks, etc.)
- marketplace_install: A Claude Code plugin marketplace repository (contains multiple plugins)
- config_update: Contains Claude Code settings, configuration snippets, or tips about config changes
- bookmark: An article, tutorial, documentation, or resource worth saving for later reading
- podcast: An Apple Podcasts link (contains podcasts.apple.com or is clearly a podcast)
- note: A discussion, tip, or anything worth noting but not directly actionable
- ignore: Not related to Claude Code, AI development, or programming

Type-specific action_detail fields:
- plugin_install: "repo_url", "plugin_name", "install_steps" (list of shell commands)
- marketplace_install: "repo_url", "marketplace_name", "install_steps"
- config_update: "settings" (the JSON settings to merge)
- bookmark: "title", "summary"
- podcast: "podcast_url", "podcast_name"
- note: "content" (the key takeaway)
- ignore: empty {}

IMPORTANT: Preserve the original language of the content. If the content is in Chinese, write the summary, title, and action_detail fields in Chinese. Do NOT translate to English."""

SYSTEM_PROMPT = f"""You are a content classifier for a Claude Code automation tool.

Given the content of a URL that was shared via iMessage, classify it.

{_CLASSIFICATION_INSTRUCTIONS}

Respond with ONLY a JSON object (no markdown, no code fences):
{{"type": "<type>", "confidence": <0.0-1.0>, "summary": "<one-line description>", "action_detail": {{...}}}}"""

BATCH_SYSTEM_PROMPT = f"""You are a content classifier for a Claude Code automation tool.

You will receive multiple URLs with their content, each labeled with an index (e.g. [0], [1], ...).
Classify each one independently.

{_CLASSIFICATION_INSTRUCTIONS}

Respond with ONLY a JSON array (no markdown, no code fences). Each element must include the "index" field matching the input:
[{{"index": 0, "type": "<type>", "confidence": <0.0-1.0>, "summary": "...", "action_detail": {{...}}}}, ...]"""


class ClassifyAPIError(Exception):
    """Raised when claude -p fails after all retries."""
    pass


@dataclass
class Classification:
    type: str
    confidence: float
    summary: str
    action_detail: dict = field(default_factory=dict)


@dataclass
class ClassifyInput:
    url: str
    message_text: str
    fetched_content: str


async def classify_batch(inputs: list[ClassifyInput]) -> list[Classification]:
    """Classify multiple URLs in batched claude -p calls (up to BATCH_SIZE per call).

    Returns classifications in the same order as inputs.
    """
    if not inputs:
        return []

    results: list[Classification] = [None] * len(inputs)  # type: ignore[list-item]

    for batch_start in range(0, len(inputs), BATCH_SIZE):
        batch = inputs[batch_start:batch_start + BATCH_SIZE]
        batch_results = await _classify_batch_cli(batch)
        for i, classification in enumerate(batch_results):
            results[batch_start + i] = classification

    return results


def _extract_text_from_stream(stdout: str) -> str:
    """Extract assistant text from claude -p --output-format stream-json output.

    Workaround for claude-code 2.1.83 bug where --output-format text returns
    empty results despite the model producing output.
    """
    text_parts = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "text":
                    text_parts.append(block["text"])
    return "".join(text_parts)


async def _classify_batch_cli(batch: list[ClassifyInput]) -> list[Classification]:
    """Send a batch of inputs to claude -p and parse array response."""
    # Build prompt with indexed items
    parts = []
    for i, inp in enumerate(batch):
        content = inp.fetched_content[:MAX_CONTENT_CHARS]
        parts.append(
            f"[{i}] URL: {inp.url}\n"
            f"Message context: {inp.message_text}\n"
            f"Fetched content:\n{content}"
        )
    prompt = "\n\n---\n\n".join(parts)

    system_prompt = BATCH_SYSTEM_PROMPT if len(batch) > 1 else SYSTEM_PROMPT

    for attempt in range(MAX_RETRIES):
        try:
            result = subprocess.run(
                [
                    "claude", "-p",
                    "--model", "sonnet",
                    "--output-format", "stream-json",
                    "--verbose",
                    "--system-prompt", system_prompt,
                    "--dangerously-skip-permissions",
                ],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode != 0:
                raise RuntimeError(f"claude -p exited {result.returncode}: {result.stderr.strip()}")

            raw = _extract_text_from_stream(result.stdout)
            if not raw:
                raise RuntimeError("claude -p returned empty response")

            if len(batch) == 1:
                return [_parse_response(raw, batch[0].url)]

            return _parse_batch_response(raw, batch)

        except (RuntimeError, subprocess.TimeoutExpired, FileNotFoundError) as e:
            if attempt < MAX_RETRIES - 1:
                delay = INITIAL_RETRY_DELAY * (2 ** attempt)
                logger.warning(f"claude -p batch error (attempt {attempt + 1}/{MAX_RETRIES}): {e}. Retrying in {delay}s...")
                time.sleep(delay)
            else:
                logger.error(f"claude -p batch failed after {MAX_RETRIES} attempts: {e}")
                raise ClassifyAPIError(f"claude -p batch failed after {MAX_RETRIES} retries: {e}") from e

    # unreachable, but keeps type checker happy
    raise ClassifyAPIError("classify batch: unreachable")



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


def _extract_first_json(text: str, open_char: str = "{", close_char: str = "}") -> dict | list | None:
    """Extract the first valid JSON object or array from text."""
    start = text.find(open_char)
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == open_char:
            depth += 1
        elif text[i] == close_char:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    continue
    return None


def _dict_to_classification(data: dict, url: str) -> Classification:
    """Convert a parsed dict to a Classification with validation."""
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


def _parse_response(raw: str, url: str) -> Classification:
    cleaned = _strip_code_fences(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        data = _extract_first_json(cleaned)
        if data is None:
            logger.error(f"Failed to parse classifier response for {url}: {raw[:200]}")
            return Classification(type="note", confidence=0.0, summary=f"Unparseable response for: {url}")

    return _dict_to_classification(data, url)


def _parse_batch_response(raw: str, batch: list[ClassifyInput]) -> list[Classification]:
    """Parse a JSON array response, matching each element back by index."""
    cleaned = _strip_code_fences(raw)

    items = None
    try:
        items = json.loads(cleaned)
    except json.JSONDecodeError:
        items = _extract_first_json(cleaned, open_char="[", close_char="]")

    if not isinstance(items, list):
        logger.error(f"Batch response not a list, falling back: {raw[:200]}")
        return [
            Classification(type="note", confidence=0.0, summary=f"Batch parse failed: {inp.url}")
            for inp in batch
        ]

    # Build index -> data mapping
    by_index: dict[int, dict] = {}
    for item in items:
        if isinstance(item, dict) and "index" in item:
            by_index[item["index"]] = item

    results = []
    for i, inp in enumerate(batch):
        if i in by_index:
            results.append(_dict_to_classification(by_index[i], inp.url))
        else:
            logger.warning(f"Batch response missing index {i} for {inp.url}")
            results.append(Classification(
                type="note", confidence=0.0,
                summary=f"Missing from batch response: {inp.url}",
            ))

    return results

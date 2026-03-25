import json
import subprocess
import pytest
from unittest.mock import patch, MagicMock
from hi_sweetheart.classifier import (
    classify_batch, ClassifyInput, Classification, ClassifyAPIError,
    CLASSIFICATION_TYPES, _parse_batch_response,
)


def test_classification_types():
    assert "plugin_install" in CLASSIFICATION_TYPES
    assert "marketplace_install" in CLASSIFICATION_TYPES
    assert "config_update" in CLASSIFICATION_TYPES
    assert "bookmark" in CLASSIFICATION_TYPES
    assert "podcast" in CLASSIFICATION_TYPES
    assert "note" in CLASSIFICATION_TYPES
    assert "ignore" in CLASSIFICATION_TYPES


def _make_input(url="https://example.com", msg="check this", content="some content"):
    return ClassifyInput(url=url, message_text=msg, fetched_content=content)


def _wrap_stream_json(text: str) -> str:
    """Wrap raw text in a stream-json assistant event, matching claude -p output."""
    event = {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}
    return json.dumps(event)


@pytest.mark.asyncio
async def test_classify_batch_single_item():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = _wrap_stream_json(json.dumps({
        "type": "bookmark",
        "confidence": 0.9,
        "summary": "Article about prompt engineering",
        "action_detail": {
            "title": "Prompt Engineering Guide",
            "summary": "Comprehensive guide to prompting",
        },
    }))

    with patch("hi_sweetheart.classifier.subprocess.run", return_value=mock_result):
        results = await classify_batch([_make_input(url="https://example.com/prompting")])
        assert len(results) == 1
        assert results[0].type == "bookmark"
        assert results[0].confidence == 0.9


@pytest.mark.asyncio
async def test_classify_batch_multiple_items():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = _wrap_stream_json(json.dumps([
        {"index": 0, "type": "bookmark", "confidence": 0.9, "summary": "Article", "action_detail": {"title": "A", "summary": "B"}},
        {"index": 1, "type": "note", "confidence": 0.8, "summary": "A tip", "action_detail": {"content": "Use X"}},
        {"index": 2, "type": "ignore", "confidence": 0.95, "summary": "Irrelevant", "action_detail": {}},
    ]))

    inputs = [
        _make_input(url="https://a.com"),
        _make_input(url="https://b.com"),
        _make_input(url="https://c.com"),
    ]
    with patch("hi_sweetheart.classifier.subprocess.run", return_value=mock_result):
        results = await classify_batch(inputs)
        assert len(results) == 3
        assert results[0].type == "bookmark"
        assert results[1].type == "note"
        assert results[2].type == "ignore"


@pytest.mark.asyncio
async def test_classify_batch_low_confidence_becomes_note():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = _wrap_stream_json(json.dumps({
        "type": "plugin_install",
        "confidence": 0.3,
        "summary": "Maybe a plugin?",
        "action_detail": {},
    }))

    with patch("hi_sweetheart.classifier.subprocess.run", return_value=mock_result):
        results = await classify_batch([_make_input()])
        assert results[0].type == "note"


@pytest.mark.asyncio
async def test_classify_batch_invalid_json_returns_note():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = _wrap_stream_json("not valid json {{{")

    with patch("hi_sweetheart.classifier.subprocess.run", return_value=mock_result):
        results = await classify_batch([_make_input()])
        assert results[0].type == "note"


@pytest.mark.asyncio
async def test_classify_batch_error_retries_and_raises():
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "Server error"

    with patch("hi_sweetheart.classifier.subprocess.run", return_value=mock_result):
        with patch("hi_sweetheart.classifier.time.sleep"):
            with pytest.raises(ClassifyAPIError, match="claude -p batch failed after 3 retries"):
                await classify_batch([_make_input()])


@pytest.mark.asyncio
async def test_classify_batch_timeout_retries():
    with patch("hi_sweetheart.classifier.subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 60)):
        with patch("hi_sweetheart.classifier.time.sleep"):
            with pytest.raises(ClassifyAPIError, match="claude -p batch failed after 3 retries"):
                await classify_batch([_make_input()])


@pytest.mark.asyncio
async def test_classify_batch_empty_returns_empty():
    results = await classify_batch([])
    assert results == []


def test_parse_batch_response_missing_index():
    """When batch response is missing an index, that item gets a fallback note."""
    batch = [_make_input(url="https://a.com"), _make_input(url="https://b.com")]
    raw = json.dumps([
        {"index": 0, "type": "bookmark", "confidence": 0.9, "summary": "Found", "action_detail": {"title": "A", "summary": "B"}},
        # index 1 is missing
    ])
    results = _parse_batch_response(raw, batch)
    assert len(results) == 2
    assert results[0].type == "bookmark"
    assert results[1].type == "note"
    assert "Missing" in results[1].summary


def test_parse_batch_response_with_code_fences():
    """Batch response wrapped in code fences should still parse."""
    batch = [_make_input(url="https://a.com")]
    raw = '```json\n[{"index": 0, "type": "note", "confidence": 0.8, "summary": "tip", "action_detail": {"content": "x"}}]\n```'
    results = _parse_batch_response(raw, batch)
    assert len(results) == 1
    assert results[0].type == "note"

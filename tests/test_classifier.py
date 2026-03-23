import json
import subprocess
import pytest
from unittest.mock import patch, MagicMock
from hi_sweetheart.classifier import classify, Classification, ClassifyAPIError, CLASSIFICATION_TYPES


def test_classification_types():
    assert "plugin_install" in CLASSIFICATION_TYPES
    assert "marketplace_install" in CLASSIFICATION_TYPES
    assert "config_update" in CLASSIFICATION_TYPES
    assert "bookmark" in CLASSIFICATION_TYPES
    assert "podcast" in CLASSIFICATION_TYPES
    assert "note" in CLASSIFICATION_TYPES
    assert "ignore" in CLASSIFICATION_TYPES


@pytest.mark.asyncio
async def test_classify_returns_structured_result():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({
        "type": "bookmark",
        "confidence": 0.9,
        "summary": "Article about prompt engineering",
        "action_detail": {
            "title": "Prompt Engineering Guide",
            "summary": "Comprehensive guide to prompting",
        },
    })

    with patch("hi_sweetheart.classifier.subprocess.run", return_value=mock_result):
        result = await classify(
            message_text="check this out",
            fetched_content="A comprehensive guide to prompt engineering...",
            url="https://example.com/prompting",
        )
        assert isinstance(result, Classification)
        assert result.type == "bookmark"
        assert result.confidence == 0.9


@pytest.mark.asyncio
async def test_classify_low_confidence_becomes_note():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({
        "type": "plugin_install",
        "confidence": 0.3,
        "summary": "Maybe a plugin?",
        "action_detail": {},
    })

    with patch("hi_sweetheart.classifier.subprocess.run", return_value=mock_result):
        result = await classify(
            message_text="hmm",
            fetched_content="unclear content",
            url="https://example.com",
        )
        assert result.type == "note"


@pytest.mark.asyncio
async def test_classify_invalid_json_returns_note():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "not valid json {{{"

    with patch("hi_sweetheart.classifier.subprocess.run", return_value=mock_result):
        result = await classify(
            message_text="test",
            fetched_content="test content",
            url="https://example.com",
        )
        assert result.type == "note"


@pytest.mark.asyncio
async def test_classify_claude_error_retries_and_raises():
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "Server error"

    with patch("hi_sweetheart.classifier.subprocess.run", return_value=mock_result):
        with patch("hi_sweetheart.classifier.time.sleep"):
            with pytest.raises(ClassifyAPIError, match="claude -p failed after 3 retries"):
                await classify(
                    message_text="test",
                    fetched_content="test",
                    url="https://example.com",
                )


@pytest.mark.asyncio
async def test_classify_timeout_retries():
    with patch("hi_sweetheart.classifier.subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 60)):
        with patch("hi_sweetheart.classifier.time.sleep"):
            with pytest.raises(ClassifyAPIError, match="claude -p failed after 3 retries"):
                await classify(
                    message_text="test",
                    fetched_content="test",
                    url="https://example.com",
                )

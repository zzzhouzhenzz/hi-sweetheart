import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import anthropic
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
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "type": "bookmark",
        "confidence": 0.9,
        "summary": "Article about prompt engineering",
        "action_detail": {
            "title": "Prompt Engineering Guide",
            "summary": "Comprehensive guide to prompting",
        },
    }))]

    with patch("hi_sweetheart.classifier.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_client

        result = await classify(
            message_text="check this out",
            fetched_content="A comprehensive guide to prompt engineering...",
            url="https://example.com/prompting",
            api_key="test-key",
        )
        assert isinstance(result, Classification)
        assert result.type == "bookmark"
        assert result.confidence == 0.9


@pytest.mark.asyncio
async def test_classify_low_confidence_becomes_note():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "type": "plugin_install",
        "confidence": 0.3,
        "summary": "Maybe a plugin?",
        "action_detail": {},
    }))]

    with patch("hi_sweetheart.classifier.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_client

        result = await classify(
            message_text="hmm",
            fetched_content="unclear content",
            url="https://example.com",
            api_key="test-key",
        )
        assert result.type == "note"


@pytest.mark.asyncio
async def test_classify_invalid_json_returns_note():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="not valid json {{{")]

    with patch("hi_sweetheart.classifier.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_client

        result = await classify(
            message_text="test",
            fetched_content="test content",
            url="https://example.com",
            api_key="test-key",
        )
        assert result.type == "note"


@pytest.mark.asyncio
async def test_classify_api_error_retries_and_raises():
    with patch("hi_sweetheart.classifier.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            side_effect=anthropic.APIStatusError(
                message="Server error",
                response=MagicMock(status_code=500),
                body=None,
            )
        )
        mock_cls.return_value = mock_client

        with patch("hi_sweetheart.classifier.time.sleep"):  # skip actual delay
            with pytest.raises(ClassifyAPIError, match="API failed after 3 retries"):
                await classify(
                    message_text="test",
                    fetched_content="test",
                    url="https://example.com",
                    api_key="test-key",
                )

        # Should have tried 3 times
        assert mock_client.messages.create.call_count == 3

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from hi_sweetheart.fetcher import extract_urls, fetch_content, FetchResult, has_actionable_content


def test_extract_urls_from_text():
    text = "check this out https://example.com/page and also http://foo.bar/baz"
    urls = extract_urls(text)
    assert len(urls) == 2
    assert "https://example.com/page" in urls
    assert "http://foo.bar/baz" in urls


def test_extract_urls_no_urls():
    urls = extract_urls("just a regular message with no links")
    assert len(urls) == 0


def test_extract_urls_deduplicates():
    text = "see https://example.com and also https://example.com"
    urls = extract_urls(text)
    assert len(urls) == 1


def test_extract_urls_github():
    text = "check https://github.com/obra/superpowers"
    urls = extract_urls(text)
    assert len(urls) == 1
    assert "github.com/obra/superpowers" in urls[0]


def test_has_actionable_content_json():
    assert has_actionable_content('try this {"model": "opus"}')
    assert not has_actionable_content("lol ok")


def test_has_actionable_content_code_block():
    assert has_actionable_content("try this:\n```json\n{}\n```")


@pytest.mark.asyncio
async def test_fetch_content_html():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "text/html"}
    mock_response.text = "<html><body><h1>Title</h1><p>Content here</p></body></html>"

    with patch("hi_sweetheart.fetcher.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        result = await fetch_content("https://example.com")
        assert isinstance(result, FetchResult)
        assert result.success
        assert "Content here" in result.text


@pytest.mark.asyncio
async def test_fetch_content_github_readme():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json = MagicMock(return_value={
        "content": "IyBTdXBlcnBvd2Vycw==",  # base64 "# Superpowers"
        "encoding": "base64",
    })

    with patch("hi_sweetheart.fetcher.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        result = await fetch_content("https://github.com/obra/superpowers")
        assert result.success
        assert "Superpowers" in result.text


@pytest.mark.asyncio
async def test_fetch_content_failure():
    with patch("hi_sweetheart.fetcher.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("timeout"))
        mock_client_cls.return_value = mock_client

        result = await fetch_content("https://example.com")
        assert not result.success
        assert "timeout" in result.error

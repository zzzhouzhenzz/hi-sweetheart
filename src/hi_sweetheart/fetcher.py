from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("hi-sweetheart")

URL_PATTERN = re.compile(r'https?://[^\s<>"\']+')
GITHUB_REPO_PATTERN = re.compile(r'https?://github\.com/([^/]+)/([^/\s#?]+)')
ACTIONABLE_PATTERNS = [re.compile(r'\{'), re.compile(r'```')]


def extract_urls(text: str) -> list[str]:
    urls = URL_PATTERN.findall(text)
    urls = [u.rstrip(".,;:)]}") for u in urls]
    return list(dict.fromkeys(urls))  # deduplicate, preserve order


def has_actionable_content(text: str) -> bool:
    return any(p.search(text) for p in ACTIONABLE_PATTERNS)


@dataclass
class FetchResult:
    url: str
    success: bool
    text: str = ""
    error: str = ""


async def fetch_content(url: str) -> FetchResult:
    try:
        github_match = GITHUB_REPO_PATTERN.match(url)
        if github_match:
            return await _fetch_github_readme(github_match.group(1), github_match.group(2))
        return await _fetch_html(url)
    except Exception as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return FetchResult(url=url, success=False, error=str(e))


async def _fetch_github_readme(owner: str, repo: str) -> FetchResult:
    url = f"https://github.com/{owner}/{repo}"
    api_url = f"https://api.github.com/repos/{owner}/{repo}/readme"
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(api_url, headers={"Accept": "application/vnd.github.v3+json"})
        if resp.status_code != 200:
            return await _fetch_html(url)
        data = resp.json()
        if data.get("encoding") == "base64":
            content = base64.b64decode(data["content"]).decode("utf-8")
        else:
            content = data.get("content", "")
        return FetchResult(url=url, success=True, text=content)


async def _fetch_html(url: str) -> FetchResult:
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            return FetchResult(url=url, success=False, error=f"HTTP {resp.status_code}")
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        if len(text) > 10000:
            text = text[:10000] + "\n...[truncated]"
        return FetchResult(url=url, success=True, text=text)

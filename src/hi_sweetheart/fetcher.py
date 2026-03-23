from __future__ import annotations

import asyncio
import base64
import logging
import re
import subprocess
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("hi-sweetheart")

URL_PATTERN = re.compile(r'https?://[^\s<>"\']+')
GITHUB_REPO_PATTERN = re.compile(r'https?://github\.com/([^/]+)/([^/\s#?]+)')
ACTIONABLE_PATTERNS = [re.compile(r'\{'), re.compile(r'```')]

# Domains that block programmatic access — use local curl with browser UA
CURL_DOMAINS = re.compile(r'(xhslink\.com|xiaohongshu\.com|instagram\.com|instagr\.am)')

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

# Boilerplate markers — if the fetched text contains these, it's likely a
# JS-rendered page that returned only shell HTML (login walls, legal footers).
BOILERPLATE_MARKERS = [
    "沪ICP备",          # Xiaohongshu legal footer
    "营业执照",          # Chinese business license text
    "Log in to see",    # Instagram login wall
    "Something went wrong",  # Instagram error
]


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


async def fetch_content(url: str, message_text: str = "") -> FetchResult:
    try:
        github_match = GITHUB_REPO_PATTERN.match(url)
        if github_match:
            return await _fetch_github_readme(github_match.group(1), github_match.group(2))

        # Try httpx first (fast, low overhead)
        result = await _fetch_html(url)
        if result.success and _has_useful_content(result.text):
            return result

        # httpx got garbage or failed — try curl for domains that need browser UA
        if CURL_DOMAINS.search(url):
            logger.info(f"httpx not useful for {url}, trying curl")
            curl_result = await _fetch_with_curl(url)
            if curl_result.success and _has_useful_content(curl_result.text):
                return curl_result

        # Both failed — fall back to message text as content
        if message_text:
            logger.info(f"Fetch not useful for {url}, using message text as content")
            return FetchResult(url=url, success=True, text=message_text)

        return result
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


def _has_useful_content(text: str) -> bool:
    """Check if fetched text has real content vs boilerplate/login walls."""
    if len(text) < 100:
        return False
    return not any(marker in text for marker in BOILERPLATE_MARKERS)


async def _fetch_with_curl(url: str) -> FetchResult:
    """Fetch URL using local curl with browser user-agent.

    Used for sites that block programmatic HTTP clients (Xiaohongshu, Instagram).
    curl handles redirects and cookies natively on macOS.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "curl", "-sL",
            "-A", BROWSER_UA,
            "-H", "Accept: text/html,application/xhtml+xml",
            "-H", "Accept-Language: en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            "--max-time", "15",
            "--max-redirs", "5",
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            error_msg = stderr.decode().strip() or f"curl exited {proc.returncode}"
            logger.warning(f"curl failed for {url}: {error_msg}")
            return FetchResult(url=url, success=False, error=error_msg)

        html = stdout.decode("utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        if len(text) > 10000:
            text = text[:10000] + "\n...[truncated]"

        logger.info(f"curl fetched {len(text)} chars from {url}")
        return FetchResult(url=url, success=True, text=text)

    except Exception as e:
        logger.error(f"curl fetch error for {url}: {e}")
        return FetchResult(url=url, success=False, error=str(e))


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

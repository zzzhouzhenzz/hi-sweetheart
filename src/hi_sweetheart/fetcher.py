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
    images: list[bytes] | None = None  # raw image bytes for vision classification


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

            # Text content is garbage — try extracting og:image for vision classification
            raw_html = await _fetch_raw_html(url)
            if raw_html:
                image_urls = _extract_og_images(raw_html)
                if image_urls:
                    images = await _download_images(image_urls)
                    if images:
                        og_meta = _extract_og_meta(raw_html)
                        logger.info(f"Downloaded {len(images)} images from {url}")
                        return FetchResult(
                            url=url, success=True,
                            text=og_meta or message_text,
                            images=images,
                        )

        # All methods failed — fall back to message text as content
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


async def _fetch_raw_html(url: str) -> str | None:
    """Fetch raw HTML via curl (for parsing og:image, not text content)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "curl", "-sL",
            "-A", BROWSER_UA,
            "--max-time", "10",
            "--max-redirs", "5",
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            return stdout.decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"Failed to fetch raw HTML for {url}: {e}")
    return None


def _find_og_meta(soup: BeautifulSoup, og_prop: str) -> list[str]:
    """Find og: meta tags by either property= or name= attribute."""
    values = []
    for meta in soup.find_all("meta"):
        attr_val = meta.get("property", "") or meta.get("name", "")
        if attr_val == og_prop:
            content = meta.get("content", "")
            if content:
                values.append(content)
    return values


def _extract_og_images(html: str) -> list[str]:
    """Extract og:image URLs from HTML meta tags."""
    soup = BeautifulSoup(html, "html.parser")
    return _find_og_meta(soup, "og:image")


def _extract_og_meta(html: str) -> str:
    """Extract og:title + og:description as text context."""
    soup = BeautifulSoup(html, "html.parser")
    parts = []
    for prop in ("og:title", "og:description"):
        values = _find_og_meta(soup, prop)
        if values:
            parts.append(values[0])
    return "\n".join(parts) if parts else ""


async def _download_images(urls: list[str], max_images: int = 5) -> list[bytes]:
    """Download images concurrently using curl. Returns list of raw bytes."""
    async def _download_one(url: str) -> bytes | None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "curl", "-sL",
                "-A", BROWSER_UA,
                "--max-time", "10",
                url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0 and len(stdout) > 1000:  # skip tiny/broken images
                return stdout
        except Exception as e:
            logger.warning(f"Failed to download image {url}: {e}")
        return None

    tasks = [_download_one(url) for url in urls[:max_images]]
    results = await asyncio.gather(*tasks)
    return [img for img in results if img is not None]

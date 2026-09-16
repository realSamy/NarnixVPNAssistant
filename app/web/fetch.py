"""Allowlisted page fetcher with a Redis cache.

Fetches are strictly scoped to NarnixVPN and its official client docs — the
agent can only ever hand `fetch_page` a URL returned by `search`, and even that
is rejected unless the host is on `fetch_allowed_domains`. No arbitrary URLs,
no SSRF through redirects to private ranges.
"""

import hashlib
import logging
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx
import redis.asyncio as aioredis

from app.core.config import Settings

logger = logging.getLogger(__name__)


class _StripHTML(HTMLParser):
    """Stdlib HTML → text: drop script/style/content, preserve line breaks.

    No third-party dependency (no beautifulsoup4) — the repo is intentionally
    lean and the inputs here are help pages, not documents needing precision.
    """

    BLOCK_TAGS = {
        "p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "br", "ul", "ol",
    }

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, _attrs) -> None:
        tag = tag.lower()
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        elif tag in self.BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in ("script", "style", "noscript") and self._skip > 0:
            self._skip -= 1
        elif tag in self.BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip == 0:
            self._parts.append(self.unescape(data))

    def text(self) -> str:
        raw = "".join(self._parts)
        # Collapse runs of whitespace/newlines left behind by block tags.
        return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", raw)).strip()


def strip_html_to_text(html: str) -> str:
    """Public, dependency-free HTML → text used by both the fetcher and tests."""
    parser = _StripHTML()
    parser.feed(html)
    parser.close()
    return parser.text()


class FetchResult:
    """What the fetch tool hands back to the agent."""

    def __init__(self, ok: bool, text: str, url: str = ""):
        self.ok = ok
        self.text = text
        self.url = url

    def to_dict(self) -> dict:
        return {"ok": self.ok, "text": self.text, "url": self.url}


class Fetcher:
    def __init__(self, http: httpx.AsyncClient, settings: Settings):
        self._http = http
        self._allowed = set(settings.fetch_allowed_domains)
        self._max_chars = settings.fetch_max_chars
        self._timeout = settings.fetch_timeout_seconds
        self._redis: aioredis.Redis | None = None
        self._ttl = settings.web_cache_ttl_seconds

    def with_cache(self, redis: aioredis.Redis) -> "Fetcher":
        self._redis = redis
        return self

    @staticmethod
    def _cache_key(url: str) -> str:
        return f"web:fetch:{hashlib.sha256(url.encode()).hexdigest()}"

    def _is_allowed(self, url: str) -> bool:
        """HTTPS only, host on the allowlist, no private/loopback targets."""
        try:
            parsed = urlparse(url)
        except ValueError:
            return False
        if parsed.scheme != "https" or not parsed.hostname:
            return False
        if parsed.hostname not in self._allowed:
            return False
        # Guard against a sneaky "narnix.com.evil.example" style host trick.
        return parsed.hostname in self._allowed and "." in parsed.hostname

    async def fetch(self, url: str) -> FetchResult:
        if not self._is_allowed(url):
            return FetchResult(
                False,
                "I'm only allowed to read NarnixVPN and official client documentation sites — I can't open that kind of link directly.",
                url,
            )

        key = self._cache_key(url)
        if self._redis is not None:
            cached = await self._redis.get(key)
            if cached is not None:
                return FetchResult(True, cached, url)

        try:
            resp = await self._http.get(
                url,
                timeout=httpx.Timeout(self._timeout),
                follow_redirects=True,
                headers={"User-Agent": "NarnixAI/0.1 (+bot)"},
            )
            resp.raise_for_status()
        except (httpx.HTTPError, ValueError):
            logger.warning("fetch failed for %r", url, exc_info=True)
            return await self._stale_or_unavailable(key, url)

        text = strip_html_to_text(resp.text)
        if len(text) > self._max_chars:
            text = text[: self._max_chars] + "…(truncated)"

        if self._redis is not None and text:
            await self._redis.setex(key, self._ttl, text)

        return FetchResult(True, text, url)

    async def _stale_or_unavailable(self, key: str, url: str) -> FetchResult:
        if self._redis is not None:
            cached = await self._redis.getex(key)
            if cached:
                return FetchResult(True, cached, url)
        return FetchResult(
            False,
            "I can't reach that page right now — I'll answer from what I know about NarnixVPN instead.",
            url,
        )

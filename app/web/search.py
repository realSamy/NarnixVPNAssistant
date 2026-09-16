"""SearXNG client with a Redis cache.

SearXNG is self-hostable, has no upstream API key, and no free-tier quota —
that is why it lives in `docker-compose.yml` as a private service. The client
is deliberately small: one `search` method, cache-first, stale-on-error.
"""

import hashlib
import json
import logging

import httpx
import redis.asyncio as aioredis

from app.core.config import Settings

logger = logging.getLogger(__name__)


class SearchResult:
    """One search result, normalized across engines so the agent need not care
    which backend produced it."""

    def __init__(self, title: str, url: str, content: str):
        self.title = title
        self.url = url
        self.content = content

    def to_dict(self) -> dict:
        return {"title": self.title, "url": self.url, "content": self.content}


class SearxngClient:
    def __init__(self, http: httpx.AsyncClient, settings: Settings):
        self._http = http
        self._base = settings.searxng_url.rstrip("/")
        self._results = settings.search_results
        self._redis: aioredis.Redis | None = None
        self._ttl = settings.web_cache_ttl_seconds

    def with_cache(self, redis: aioredis.Redis) -> "SearxngClient":
        """Attach the shared Redis instance. Called from `create_app`."""
        self._redis = redis
        return self

    @staticmethod
    def _cache_key(query: str) -> str:
        return f"web:search:{hashlib.sha256(query.encode()).hexdigest()}"

    async def search(self, query: str) -> list[SearchResult]:
        if not self._base:
            return [SearchResult("", "", "search is unavailable — no search engine is configured.")]

        key = self._cache_key(query)

        if self._redis is not None:
            cached = await self._redis.get(key)
            if cached is not None:
                return [SearchResult(**item) for item in json.loads(cached)]

        results: list[SearchResult] = []
        try:
            resp = await self._http.get(
                f"{self._base}/search",
                params={"q": query, "format": "json", "safesearch": 1},
                timeout=15,
            )
            resp.raise_for_status()
            raw = resp.json()
        except (httpx.HTTPError, ValueError):
            logger.warning("searxng lookup failed for %r", query, exc_info=True)
            # Serve a stale cache if one exists; otherwise report unavailable.
            return await self._stale_or_unavailable(key, query)

        for item in raw[: self._results]:
            content = (item.get("content") or item.get("title") or "").strip()
            results.append(SearchResult(item.get("title", ""), item.get("url", ""), content))

        if not results:
            results = [SearchResult("", "", "I didn't find anything I can cite for that. I can open a support ticket if you'd like a human to look.")]

        if self._redis is not None and results:
            await self._redis.setex(key, self._ttl, json.dumps([r.to_dict() for r in results]))

        return results

    async def _stale_or_unavailable(self, key: str, query: str) -> list[SearchResult]:
        if self._redis is not None:
            # `getex` fetches without refreshing the TTL, so staleness is honest.
            cached = await self._redis.getex(key)
            if cached:
                return [SearchResult(**item) for item in json.loads(cached)]
        return [SearchResult("", "", "the web search service is temporarily unavailable — I'll answer from my knowledge of NarnixVPN instead.")]

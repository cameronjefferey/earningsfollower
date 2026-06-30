"""Thin httpx wrapper over ApeWisdom's free, no-auth mentions API.

ApeWisdom crawls the retail subreddits for us and publishes, per ticker, how
many times it was mentioned, its upvotes, and — crucially — the same numbers as
of 24h ago, which gives a ready-made acceleration (velocity) signal. No app, no
OAuth, no datacenter-IP blocking, so it's the dependable discovery + velocity
source for the Reddit strategy. Direction/sentiment is layered on separately
(Reddit text via OAuth when available, else price momentum).

Endpoint shape (https://apewisdom.io/api/v1.0/filter/<filter>/page/<n>):
    {"count", "pages", "current_page",
     "results": [{"rank", "ticker", "name", "mentions", "upvotes",
                  "rank_24h_ago", "mentions_24h_ago"}, ...]}

Filters include "all-stocks" (stocks only, all subreddits) and per-subreddit
names like "wallstreetbets". Best-effort: any failure returns [] and is logged.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://apewisdom.io/api/v1.0"


class ApeWisdomClient:
    def __init__(self, timeout: float = 20.0) -> None:
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "earningsfollower/0.1 (apewisdom mentions)"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ApeWisdomClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _page(self, filter_: str, page: int) -> dict[str, Any] | None:
        try:
            resp = self._client.get(f"{_BASE}/filter/{filter_}/page/{page}")
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("ApeWisdom %s page %d failed: %s", filter_, page, exc)
            return None

    def rankings(self, filter_: str = "all-stocks", pages: int = 1) -> list[dict[str, Any]]:
        """Return the ranked mention rows across the first ``pages`` pages.

        Each row carries ticker, mentions, upvotes, and mentions_24h_ago. Stops
        early if a page is missing or we've passed the last page."""
        out: list[dict[str, Any]] = []
        for p in range(1, max(1, pages) + 1):
            data = self._page(filter_, p)
            if not data:
                break
            results = data.get("results") or []
            out.extend(r for r in results if isinstance(r, dict))
            if p >= int(data.get("pages") or 1):
                break
        return out

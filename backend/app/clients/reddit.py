"""Thin httpx wrapper over Reddit's read API for the social-sentiment strategy.

Two modes, picked automatically:

  - **Authenticated** (preferred): if a Reddit app credential is configured
    (``reddit_client_id`` + ``reddit_client_secret``) we fetch an OAuth
    *app-only* token (client-credentials grant) and read from
    ``oauth.reddit.com`` with a 600 req / 10 min budget.
  - **Public fallback**: otherwise we hit the public ``www.reddit.com/*.json``
    endpoints with a descriptive User-Agent. This works with no credentials but
    is rate-limited harder and can be throttled on cloud IPs.

Scoped to what the strategy needs: pull a subreddit listing (hot/rising/new) and
optionally the top-level comments on a post. Everything degrades gracefully — a
failed call returns an empty list and is logged, never raised into the trader.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_OAUTH_BASE = "https://oauth.reddit.com"
_PUBLIC_BASE = "https://www.reddit.com"


class RedditClient:
    def __init__(self, timeout: float = 20.0) -> None:
        s = get_settings()
        self.client_id = s.reddit_client_id
        self.client_secret = s.reddit_client_secret
        self.user_agent = s.reddit_user_agent or "earningsfollower/0.1"
        self._client = httpx.Client(
            timeout=timeout, headers={"User-Agent": self.user_agent}
        )
        self._token: str | None = None
        self._token_expiry: float = 0.0

    @property
    def authenticated(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "RedditClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- auth ----------------------------------------------------------------

    def _ensure_token(self) -> str | None:
        if not self.authenticated:
            return None
        if self._token and time.time() < self._token_expiry - 30:
            return self._token
        try:
            resp = self._client.post(
                _TOKEN_URL,
                auth=(self.client_id, self.client_secret),
                data={"grant_type": "client_credentials"},
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Reddit token fetch failed: %s", exc)
            return None
        self._token = data.get("access_token")
        self._token_expiry = time.time() + float(data.get("expires_in", 3600))
        return self._token

    # --- low level -----------------------------------------------------------

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        token = self._ensure_token()
        if token:
            base, headers = _OAUTH_BASE, {"Authorization": f"Bearer {token}"}
        else:
            base, headers = _PUBLIC_BASE, {}
        try:
            resp = self._client.get(f"{base}{path}", params=params, headers=headers)
            if resp.status_code == 429:
                logger.warning("Reddit rate limit hit (429) on %s", path)
                return None
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Reddit GET %s failed: %s", path, exc)
            return None

    # --- reads ---------------------------------------------------------------

    def listing(
        self, subreddit: str, kind: str = "hot", limit: int = 50
    ) -> list[dict[str, Any]]:
        """Return the post objects (data dicts) for a subreddit listing.

        ``kind`` is one of hot|rising|new|top. Each item carries title, selftext,
        score, num_comments, permalink, id, created_utc, etc.
        """
        data = self._get(
            f"/r/{subreddit}/{kind}.json",
            params={"limit": max(1, min(limit, 100)), "raw_json": 1},
        )
        children = (((data or {}).get("data") or {}).get("children")) or []
        return [c.get("data", {}) for c in children if isinstance(c, dict)]

    def comments(
        self, subreddit: str, post_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Return top-level comment data dicts for a post (best-effort)."""
        data = self._get(
            f"/r/{subreddit}/comments/{post_id}.json",
            params={"limit": max(1, min(limit, 100)), "depth": 1, "raw_json": 1},
        )
        # Comments listing is the 2nd element of the returned array.
        if not isinstance(data, list) or len(data) < 2:
            return []
        children = (((data[1] or {}).get("data") or {}).get("children")) or []
        out: list[dict[str, Any]] = []
        for c in children:
            if isinstance(c, dict) and c.get("kind") == "t1":
                out.append(c.get("data", {}))
        return out

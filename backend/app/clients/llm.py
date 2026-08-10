"""Optional LLM client for scoring Reddit chatter into a structured verdict.

Talks to any OpenAI-compatible ``/chat/completions`` endpoint. It's *optional*
by design: if no ``llm_api_key`` is configured, ``enabled`` is False and callers
fall back to a transparent keyword heuristic, so the social strategy still runs
end-to-end without an LLM bill. JSON is requested via response_format and parsed
defensively - any failure returns None rather than raising into the trader.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self, timeout: float = 40.0) -> None:
        s = get_settings()
        self.api_key = s.llm_api_key
        self.base_url = (s.llm_base_url or "").rstrip("/")
        self.model = s.llm_model
        self._client = httpx.Client(timeout=timeout)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "LLMClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def score_json(
        self, system: str, user: str, max_tokens: int = 600
    ) -> dict[str, Any] | None:
        """Send a system+user prompt and parse the JSON object the model returns.

        Returns the parsed dict, or None on any error (caller should fall back)."""
        if not self.enabled:
            return None
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        try:
            resp = self._client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            logger.warning("LLM scoring failed: %s", exc)
            return None

"""Thin httpx wrapper over Alpaca's Trading + Options Market Data APIs.

Scoped to what the paper earnings-trader needs: account equity, option-contract
discovery, latest option quotes (for mid-price limits), multi-leg (Level 3)
order submission, and position/order lookup.

Degrades gracefully when no key pair is configured: `enabled` is False and the
executor skips its run instead of crashing.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class AlpacaError(RuntimeError):
    pass


class AlpacaClient:
    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        s = get_settings()
        self.api_key = api_key if api_key is not None else s.alpaca_api_key
        self.api_secret = api_secret if api_secret is not None else s.alpaca_api_secret
        self.trading_base = s.alpaca_trading_base
        self.data_base = s.alpaca_data_base
        self.data_feed = (s.alpaca_data_feed or "iex").lower()
        self._client = httpx.Client(timeout=timeout, headers=self._headers())

    def _headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
            "accept": "application/json",
        }

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "AlpacaClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- low level -----------------------------------------------------------

    def _request(
        self,
        method: str,
        base: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        if not self.enabled:
            raise AlpacaError("Alpaca credentials not configured.")
        resp = self._client.request(method, f"{base}{path}", params=params, json=json)
        if resp.status_code == 401:
            raise AlpacaError("Alpaca rejected the credentials (401).")
        if resp.status_code == 403:
            raise AlpacaError(f"Alpaca forbidden (403): {resp.text[:300]}")
        if resp.status_code == 422:
            raise AlpacaError(f"Alpaca rejected the request (422): {resp.text[:500]}")
        if resp.status_code == 429:
            raise AlpacaError("Alpaca rate limit hit (429).")
        resp.raise_for_status()
        if resp.text:
            return resp.json()
        return None

    # --- account -------------------------------------------------------------

    def account(self) -> dict[str, Any]:
        return self._request("GET", self.trading_base, "/v2/account") or {}

    def clock(self) -> dict[str, Any]:
        """Market clock: {is_open, next_open, next_close, timestamp}."""
        return self._request("GET", self.trading_base, "/v2/clock") or {}

    def is_market_open(self) -> bool:
        """Whether the US equity/options market is open right now. Fails open
        (returns False) on any error so we never place orders into a closed or
        unknown market."""
        try:
            return bool(self.clock().get("is_open"))
        except AlpacaError:
            return False

    def equity(self) -> float:
        acct = self.account()
        try:
            return float(acct.get("equity") or acct.get("cash") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    # --- option contracts ----------------------------------------------------

    def option_contracts(
        self,
        underlying: str,
        *,
        expiration_gte: str | None = None,
        expiration_lte: str | None = None,
        option_type: str | None = None,
        strike_gte: float | None = None,
        strike_lte: float | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """List active option contracts for an underlying, optionally filtered by
        expiration window, call/put, and strike range. Returns the raw contract
        dicts (symbol, strike_price, expiration_date, type, ...)."""
        params: dict[str, Any] = {
            "underlying_symbols": underlying.upper(),
            "status": "active",
            "limit": limit,
        }
        if expiration_gte:
            params["expiration_date_gte"] = expiration_gte
        if expiration_lte:
            params["expiration_date_lte"] = expiration_lte
        if option_type:
            params["type"] = option_type
        if strike_gte is not None:
            params["strike_price_gte"] = f"{strike_gte:.2f}"
        if strike_lte is not None:
            params["strike_price_lte"] = f"{strike_lte:.2f}"
        data = self._request(
            "GET", self.trading_base, "/v2/options/contracts", params=params
        )
        return (data or {}).get("option_contracts", []) if isinstance(data, dict) else []

    def stock_price(self, symbol: str) -> float | None:
        """Latest trade price for an underlying (intraday).

        Uses the configured feed (``sip`` = real-time consolidated tape with a
        paid market-data sub; ``iex`` = free, IEX-only). If the chosen feed isn't
        entitled, falls back to iex so a missing subscription never breaks the
        price lookup.
        """
        feeds: list[str] = []
        for f in (self.data_feed, "iex"):
            if f and f not in feeds:
                feeds.append(f)
        for feed in feeds:
            try:
                data = self._request(
                    "GET",
                    self.data_base,
                    f"/v2/stocks/{symbol.upper()}/trades/latest",
                    params={"feed": feed},
                )
            except AlpacaError as exc:
                # Not entitled for this feed (403) or bad param (422): try iex.
                if feed != "iex" and ("403" in str(exc) or "422" in str(exc)):
                    continue
                raise
            try:
                px = (data or {}).get("trade", {}).get("p")
                if px:
                    return float(px)
            except (TypeError, ValueError):
                return None
        return None

    def option_quotes(self, symbols: list[str]) -> dict[str, dict[str, float]]:
        """Latest bid/ask/mid for a list of OCC option symbols."""
        if not symbols:
            return {}
        data = self._request(
            "GET",
            self.data_base,
            "/v1beta1/options/quotes/latest",
            params={"symbols": ",".join(symbols)},
        )
        out: dict[str, dict[str, float]] = {}
        for sym, q in (data or {}).get("quotes", {}).items():
            bid = float(q.get("bp") or 0.0)
            ask = float(q.get("ap") or 0.0)
            mid = (bid + ask) / 2 if (bid and ask) else (ask or bid)
            out[sym] = {"bid": bid, "ask": ask, "mid": round(mid, 2)}
        return out

    # --- orders / positions --------------------------------------------------

    def submit_mleg(
        self,
        legs: list[dict[str, Any]],
        qty: int,
        limit_price: float,
        time_in_force: str = "day",
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        """Submit a multi-leg (Level 3) options order. `legs` items must each have
        symbol, ratio_qty, side, position_intent."""
        body: dict[str, Any] = {
            "order_class": "mleg",
            "qty": str(qty),
            "type": "limit",
            "limit_price": f"{limit_price:.2f}",
            "time_in_force": time_in_force,
            "legs": legs,
        }
        if client_order_id:
            body["client_order_id"] = client_order_id
        return self._request("POST", self.trading_base, "/v2/orders", json=body) or {}

    def submit_option_order(
        self,
        symbol: str,
        qty: int,
        side: str,                 # "buy" | "sell"
        position_intent: str,      # "buy_to_open" | "sell_to_close"
        limit_price: float,
        time_in_force: str = "day",
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        """Submit a single-leg option order (used for directional wave trades)."""
        body: dict[str, Any] = {
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "type": "limit",
            "limit_price": f"{limit_price:.2f}",
            "time_in_force": time_in_force,
            "position_intent": position_intent,
        }
        if client_order_id:
            body["client_order_id"] = client_order_id
        return self._request("POST", self.trading_base, "/v2/orders", json=body) or {}

    def submit_stock_order(
        self,
        symbol: str,
        qty: int,
        side: str,                 # "buy" (open long / close short) | "sell" (open short / close long)
        time_in_force: str = "day",
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        """Submit a plain equity market order. Used for the Reddit equity twin —
        stocks are liquid so a market order fills at a fair NBBO price (no wide
        option spread to cross). A ``sell`` with no long position opens a short;
        a ``buy`` closes it (Alpaca nets against the existing position)."""
        body: dict[str, Any] = {
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "type": "market",
            "time_in_force": time_in_force,
        }
        if client_order_id:
            body["client_order_id"] = client_order_id
        return self._request("POST", self.trading_base, "/v2/orders", json=body) or {}

    def get_order(self, order_id: str) -> dict[str, Any]:
        return (
            self._request("GET", self.trading_base, f"/v2/orders/{order_id}") or {}
        )

    def cancel_order(self, order_id: str) -> None:
        """Cancel a working order. A 404/422 (already filled or gone) is not an
        error for our purposes -- the walk-limit just moves on."""
        try:
            self._request("DELETE", self.trading_base, f"/v2/orders/{order_id}")
        except (AlpacaError, httpx.HTTPError):
            pass

    def list_positions(self) -> list[dict[str, Any]]:
        return self._request("GET", self.trading_base, "/v2/positions") or []

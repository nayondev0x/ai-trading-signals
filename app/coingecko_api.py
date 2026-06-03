"""CoinGecko data provider — free, no API key, not geo-blocked.

Provides the dashboard with:
  * live price + 24h % change  (one batched /coins/markets call)
  * a multi-indicator BUY/SELL/NEUTRAL signal derived **strictly from live
    closing prices** (/market_chart) via the shared signal engine — same
    multi-indicator voting approach used by TradingView.

This is a fully-working live source even when the RapidAPI hosts are blocked.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from . import signal_engine

BASE = "https://api.coingecko.com/api/v3"

# Map dashboard symbols -> CoinGecko ids + display names.
SYMBOL_MAP = {
    "BTCUSDT": ("bitcoin", "Bitcoin", "BTC"),
    "ETHUSDT": ("ethereum", "Ethereum", "ETH"),
    "SOLUSDT": ("solana", "Solana", "SOL"),
    "BNBUSDT": ("binancecoin", "BNB", "BNB"),
    "XRPUSDT": ("ripple", "Ripple", "XRP"),
    "ADAUSDT": ("cardano", "Cardano", "ADA"),
    "DOGEUSDT": ("dogecoin", "Dogecoin", "DOGE"),
    "AVAXUSDT": ("avalanche-2", "Avalanche", "AVAX"),
}

# RSI math now lives in signal_engine; re-exported for backwards compatibility.
compute_rsi = signal_engine.compute_rsi


def _round_price(p: float) -> float:
    return round(p, 6 if p < 1 else 4 if p < 5 else 2)


# --- Simple in-process TTL cache to stay under CoinGecko's free rate limit ---
CACHE_TTL_SECONDS = 60
_cache: Dict[str, Any] = {}          # key -> result dict
_cache_at: Dict[str, float] = {}     # key -> unix timestamp


async def _get(client: httpx.AsyncClient, path: str, params: dict) -> Any:
    resp = await client.get(f"{BASE}{path}", params=params)
    resp.raise_for_status()
    return resp.json()


async def _get_with_retry(client: httpx.AsyncClient, path: str,
                          params: dict, retries: int = 2) -> Any:
    """GET with backoff on 429 (rate limit)."""
    for attempt in range(retries + 1):
        try:
            return await _get(client, path, params)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429 and attempt < retries:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            raise


# Indicators are computed from DAILY candles, so they change slowly — cache the
# closing-price SERIES per-coin (15 min). This spreads requests across refreshes
# instead of firing many market_chart calls at once and tripping the rate limit.
SERIES_TTL_SECONDS = 900
_series_cache: Dict[str, List[float]] = {}
_series_at: Dict[str, float] = {}
_RSI_SEMAPHORE = asyncio.Semaphore(2)

# Max number of *fresh* history fetches per get_rows() call. Others use cache.
# Kept small to stay under CoinGecko's free-tier limit; the rest fill in over
# subsequent refresh cycles.
SERIES_FETCH_BUDGET = 2

# We need enough candles for SMA50 etc. — pull ~90 days of daily closes.
HISTORY_DAYS = "90"


async def _series_for(client: httpx.AsyncClient,
                      coin_id: str) -> Optional[List[float]]:
    """Fetch the daily closing-price series, with gentle retries on 429."""
    async with _RSI_SEMAPHORE:
        for attempt in range(3):
            try:
                data = await _get(
                    client, f"/coins/{coin_id}/market_chart",
                    {"vs_currency": "usd", "days": HISTORY_DAYS,
                     "interval": "daily"},
                )
                closes = [pt[1] for pt in data.get("prices", [])]
                if closes:
                    _series_cache[coin_id] = closes
                    _series_at[coin_id] = time.time()
                return closes or None
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429 and attempt < 2:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                break
            except Exception:  # noqa: BLE001 — best-effort
                break
    # Fall back to any cached series we have (even if a bit stale).
    return _series_cache.get(coin_id)


async def _series_batch(client: httpx.AsyncClient,
                        coin_ids: List[str]) -> Dict[str, Optional[List[float]]]:
    """Resolve close-series for many coins: fresh cache first, then fetch a few."""
    now_ts = time.time()
    out: Dict[str, Optional[List[float]]] = {}
    need: List[str] = []
    for cid in coin_ids:
        if cid in _series_cache and now_ts - _series_at.get(cid, 0) < SERIES_TTL_SECONDS:
            out[cid] = _series_cache[cid]
        else:
            need.append(cid)

    # Only fetch up to the budget this round; the rest reuse stale cache and are
    # refreshed on subsequent calls.
    to_fetch = need[:SERIES_FETCH_BUDGET]
    results = await asyncio.gather(*[_series_for(client, cid) for cid in to_fetch])
    for cid, series in zip(to_fetch, results):
        out[cid] = series
    for cid in need[SERIES_FETCH_BUDGET:]:
        out[cid] = _series_cache.get(cid)  # whatever we have (maybe None for now)
    return out


async def get_rows(symbols: Optional[List[str]] = None) -> Dict[str, Any]:
    """Fetch rows for the requested symbols from CoinGecko (cached ~60s)."""
    symbols = symbols or list(SYMBOL_MAP.keys())
    # Keep only symbols we know how to map.
    known = [(s.upper(), *SYMBOL_MAP[s.upper()]) for s in symbols
             if s.upper() in SYMBOL_MAP]
    if not known:
        return {"rows": [], "meta": {"using_mock": False,
                "updated": _now(), "note": "No known symbols.", "count": 0,
                "provider": "coingecko"}}

    # Serve from cache if fresh — keeps us well under the free rate limit.
    cache_key = ",".join(sorted(k[0] for k in known))
    now_ts = time.time()
    if cache_key in _cache and now_ts - _cache_at.get(cache_key, 0) < CACHE_TTL_SECONDS:
        cached = dict(_cache[cache_key])
        cached["meta"] = {**cached["meta"], "cached": True}
        return cached

    ids = ",".join(k[1] for k in known)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            markets = await _get_with_retry(client, "/coins/markets", {
                "vs_currency": "usd",
                "ids": ids,
                "price_change_percentage": "24h",
            })
            by_id = {m["id"]: m for m in markets}

            # Resolve close-series using per-coin cache + a small fetch budget.
            series_by_id = await _series_batch(client, [k[1] for k in known])

        rows: List[Dict[str, Any]] = []
        for (sym, coin_id, name, ticker) in known:
            m = by_id.get(coin_id, {})
            price = m.get("current_price")
            change = m.get("price_change_percentage_24h_in_currency")
            if change is None:
                change = m.get("price_change_percentage_24h", 0.0)

            # Generate the BUY/SELL/NEUTRAL signal strictly from live closes.
            closes = series_by_id.get(coin_id) or []
            # Append the freshest tick so the latest price feeds the indicators.
            if price is not None:
                closes = closes + [price]
            ta = signal_engine.analyze(closes) if len(closes) >= 15 else None

            rows.append({
                "symbol": sym,
                "name": name,
                "kind": "crypto",
                "pair": f"{ticker} / USD",
                "price": _round_price(price) if price is not None else None,
                "change": round(change, 2) if change is not None else 0.0,
                "signal": ta["signal"] if ta else "NEUTRAL",
                "recommendation": ta["recommendation"] if ta else None,
                "rsi": ta["rsi"] if ta else None,
                "strength": ta["strength"] if ta else 50,
                "votes": ta["votes"] if ta else None,
                "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
                "source": "live",
            })

        result = {"rows": rows, "meta": {
            "using_mock": False, "updated": _now(),
            "note": None, "count": len(rows), "provider": "coingecko",
            "cached": False}}
        _cache[cache_key] = result
        _cache_at[cache_key] = now_ts
        return result

    except Exception as exc:  # noqa: BLE001
        # If we have any (even stale) cached real data, prefer it over mock.
        if cache_key in _cache:
            stale = dict(_cache[cache_key])
            stale["meta"] = {**stale["meta"], "cached": True, "stale": True,
                             "note": f"Serving cached data ({exc})."}
            return stale
        # Otherwise surface the error; caller falls back to mock.
        raise RuntimeError(f"CoinGecko error: {exc}") from exc


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

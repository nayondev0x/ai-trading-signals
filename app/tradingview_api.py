"""TradingView technical-analysis provider (via RapidAPI).

Endpoint:
  GET /get_analysis_from_symbol?symbol=&exchange=&screener=&interval=

This is the most reliable source we tested — it returns a real TradingView
recommendation (STRONG_BUY..STRONG_SELL) plus indicators (RSI, close, etc.)
for both crypto and stocks. We collapse the 5-level recommendation to
BUY / SELL / NEUTRAL to match the dashboard design.

Key is read from the same .env used by the other providers.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from . import config

HOST = "tradingview-ta-api-technical-analysis.p.rapidapi.com"
BASE = f"https://{HOST}"
DEFAULT_INTERVAL = "1d"

# symbol -> (tv_symbol, exchange, screener, display_name, ticker, kind)
SYMBOL_MAP: Dict[str, Tuple[str, str, str, str, str, str]] = {
    # --- Crypto (BINANCE / crypto screener) ---
    "BTCUSDT": ("BTCUSDT", "BINANCE", "crypto", "Bitcoin", "BTC", "crypto"),
    "ETHUSDT": ("ETHUSDT", "BINANCE", "crypto", "Ethereum", "ETH", "crypto"),
    "SOLUSDT": ("SOLUSDT", "BINANCE", "crypto", "Solana", "SOL", "crypto"),
    "BNBUSDT": ("BNBUSDT", "BINANCE", "crypto", "BNB", "BNB", "crypto"),
    "XRPUSDT": ("XRPUSDT", "BINANCE", "crypto", "Ripple", "XRP", "crypto"),
    "ADAUSDT": ("ADAUSDT", "BINANCE", "crypto", "Cardano", "ADA", "crypto"),
    "DOGEUSDT": ("DOGEUSDT", "BINANCE", "crypto", "Dogecoin", "DOGE", "crypto"),
    "AVAXUSDT": ("AVAXUSDT", "BINANCE", "crypto", "Avalanche", "AVAX", "crypto"),
    # --- US stocks (america screener) ---
    "AAPL": ("AAPL", "NASDAQ", "america", "Apple", "AAPL", "stock"),
    "MSFT": ("MSFT", "NASDAQ", "america", "Microsoft", "MSFT", "stock"),
    "NVDA": ("NVDA", "NASDAQ", "america", "NVIDIA", "NVDA", "stock"),
    "TSLA": ("TSLA", "NASDAQ", "america", "Tesla", "TSLA", "stock"),
    "AMZN": ("AMZN", "NASDAQ", "america", "Amazon", "AMZN", "stock"),
    "META": ("META", "NASDAQ", "america", "Meta Platforms", "META", "stock"),
    "GOOGL": ("GOOGL", "NASDAQ", "america", "Alphabet", "GOOGL", "stock"),
    "AMD": ("AMD", "NASDAQ", "america", "AMD", "AMD", "stock"),
}


def _headers() -> Dict[str, str]:
    return {
        "x-rapidapi-key": config.RAPIDAPI_KEY,
        "x-rapidapi-host": HOST,
        "Content-Type": "application/json",
    }


def _collapse_recommendation(rec: Optional[str]) -> str:
    """Map TradingView's 5-level recommendation to 3 states."""
    r = (rec or "").upper()
    if "BUY" in r:      # STRONG_BUY or BUY
        return "BUY"
    if "SELL" in r:     # STRONG_SELL or SELL
        return "SELL"
    return "NEUTRAL"


def _round_price(p: Optional[float]) -> Optional[float]:
    if p is None:
        return None
    return round(p, 6 if p < 1 else 4 if p < 5 else 2)


# --- TTL cache (the API is fine but we still avoid needless calls) -----------
CACHE_TTL_SECONDS = 60
_cache: Dict[str, Any] = {}
_cache_at: Dict[str, float] = {}
_SEMAPHORE = asyncio.Semaphore(4)


async def _analyze(client: httpx.AsyncClient, sym: str,
                   interval: str) -> Dict[str, Any]:
    """Fetch + normalize one symbol's analysis into a dashboard row."""
    tv_symbol, exchange, screener, name, ticker, kind = SYMBOL_MAP[sym]
    params = {
        "symbol": tv_symbol,
        "exchange": exchange,
        "screener": screener,
        "interval": interval,
    }
    async with _SEMAPHORE:
        resp = await client.get(f"{BASE}/get_analysis_from_symbol",
                                headers=_headers(), params=params)
    resp.raise_for_status()
    data = resp.json()
    # The API returns {"message": "..."} for unknown symbols / transient errors.
    if not isinstance(data, dict) or "summary" not in data or data.get("summary") is None:
        msg = data.get("message") if isinstance(data, dict) else str(data)
        raise RuntimeError(f"No analysis for {sym}: {str(msg)[:120]}")

    summary = data.get("summary", {})
    ind = data.get("indicators", {})
    rec_raw = summary.get("RECOMMENDATION")
    rsi = ind.get("RSI")
    close = ind.get("close")

    # Strength 0-100 from the BUY/SELL/NEUTRAL vote split.
    buy = summary.get("BUY", 0) or 0
    sell = summary.get("SELL", 0) or 0
    neutral = summary.get("NEUTRAL", 0) or 0
    total_votes = buy + sell + neutral
    collapsed = _collapse_recommendation(rec_raw)
    if total_votes and collapsed != "NEUTRAL":
        dominant = buy if collapsed == "BUY" else sell
        strength = round(dominant / total_votes * 100)
    else:
        strength = 50

    pair = f"{ticker} / USDT" if kind == "crypto" else f"{exchange}:{ticker}"
    return {
        "symbol": sym,
        "name": name,
        "kind": kind,
        "pair": pair,
        "price": _round_price(close),
        # 24h change isn't in this endpoint; left at 0 (see note in README).
        "change": 0.0,
        "signal": collapsed,
        "recommendation": rec_raw,      # full 5-level value, kept for reference
        "rsi": round(rsi, 1) if isinstance(rsi, (int, float)) else None,
        "strength": strength,
        "votes": {"buy": buy, "neutral": neutral, "sell": sell},
        "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
        "source": "live",
    }


async def get_rows(symbols: Optional[List[str]] = None,
                   interval: str = DEFAULT_INTERVAL) -> Dict[str, Any]:
    """Fetch rows for the requested symbols from TradingView (cached ~60s)."""
    symbols = symbols or list(SYMBOL_MAP.keys())
    known = [s.upper() for s in symbols if s.upper() in SYMBOL_MAP]
    if not known:
        return {"rows": [], "meta": {"using_mock": False, "updated": _now(),
                "note": "No known symbols.", "count": 0,
                "provider": "tradingview", "interval": interval}}

    cache_key = f"{interval}:" + ",".join(sorted(known))
    now_ts = time.time()
    if cache_key in _cache and now_ts - _cache_at.get(cache_key, 0) < CACHE_TTL_SECONDS:
        cached = dict(_cache[cache_key])
        cached["meta"] = {**cached["meta"], "cached": True}
        return cached

    async with httpx.AsyncClient(timeout=15.0) as client:
        results = await asyncio.gather(
            *[_analyze(client, s, interval) for s in known],
            return_exceptions=True,
        )

    rows: List[Dict[str, Any]] = []
    errors: List[str] = []
    for sym, res in zip(known, results):
        if isinstance(res, Exception):
            errors.append(f"{sym}: {res}")
        else:
            rows.append(res)

    if not rows:
        # Total failure — let the caller fall back.
        raise RuntimeError("TradingView returned no rows. " + "; ".join(errors))

    result = {"rows": rows, "meta": {
        "using_mock": False, "updated": _now(), "cached": False,
        "note": ("; ".join(errors) if errors else None),
        "count": len(rows), "provider": "tradingview", "interval": interval}}
    _cache[cache_key] = result
    _cache_at[cache_key] = now_ts
    return result


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

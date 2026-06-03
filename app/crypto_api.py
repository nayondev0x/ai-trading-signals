"""Client for the crypto-signal-api (RapidAPI), with graceful mock fallback.

The upstream API proxies Binance. In some regions Binance returns
HTTP 451 ("Unavailable For Legal Reasons"), which the API surfaces as
``{"error": "Binance API error: 451 ..."}``. When that (or any other
failure) happens and USE_MOCK_FALLBACK is on, we return realistic mock
data so the dashboard stays functional. The moment the upstream works,
real data flows through automatically — no code change needed.
"""
from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from . import config

# --- Friendly display names for known symbols --------------------------------
_NAMES = {
    "BTCUSDT": "Bitcoin", "ETHUSDT": "Ethereum", "SOLUSDT": "Solana",
    "BNBUSDT": "BNB", "XRPUSDT": "Ripple", "ADAUSDT": "Cardano",
    "DOGEUSDT": "Dogecoin", "AVAXUSDT": "Avalanche",
}

# Rough reference prices used only for generating mock data.
_MOCK_BASE = {
    "BTCUSDT": 64000, "ETHUSDT": 3380, "SOLUSDT": 152, "BNBUSDT": 598,
    "XRPUSDT": 0.52, "ADAUSDT": 0.45, "DOGEUSDT": 0.12, "AVAXUSDT": 37,
}


def _headers() -> Dict[str, str]:
    return {
        "x-rapidapi-key": config.RAPIDAPI_KEY,
        "x-rapidapi-host": config.RAPIDAPI_HOST,
        "Content-Type": "application/json",
    }


def pretty_name(symbol: str) -> str:
    return _NAMES.get(symbol.upper(), symbol.replace("USDT", ""))


def display_pair(symbol: str) -> str:
    s = symbol.upper()
    return f"{s[:-4]} / USDT" if s.endswith("USDT") else s


# -----------------------------------------------------------------------------
# Low-level request helpers
# -----------------------------------------------------------------------------
async def _get(path: str) -> Dict[str, Any]:
    """GET a path. Returns parsed JSON or raises for an upstream error."""
    url = f"{config.BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=12.0) as client:
        resp = await client.get(url, headers=_headers())
    resp.raise_for_status()
    data = resp.json()
    # The API returns 200 with an {"error": ...} body for upstream failures.
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(data["error"])
    return data


async def health() -> Dict[str, Any]:
    try:
        return await _get("/health")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


# -----------------------------------------------------------------------------
# Normalisation: turn whatever the API returns into our dashboard row shape
# -----------------------------------------------------------------------------
def _norm_signal_word(value: Any) -> str:
    s = str(value).upper()
    if "BUY" in s or "LONG" in s or "BULL" in s:
        return "BUY"
    if "SELL" in s or "SHORT" in s or "BEAR" in s:
        return "SELL"
    return "NEUTRAL"


def _pick(d: Dict[str, Any], *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] is not None:
            return d[k]
    return default


def _normalize_row(symbol: str, signal: Dict[str, Any],
                   indicators: Dict[str, Any]) -> Dict[str, Any]:
    """Map raw API payloads into the row our dashboard renders.

    Defensive: tries several common field names since we couldn't observe a
    live success response. Adjust keys here once you see real output.
    """
    price = _pick(signal, "price", "lastPrice", "close", "current_price")
    if price is None:
        price = _pick(indicators, "price", "close")
    change = _pick(signal, "change", "changePercent", "priceChangePercent",
                   "change_24h", default=0.0)
    sig = _norm_signal_word(_pick(signal, "signal", "action",
                                  "recommendation", default="NEUTRAL"))
    rsi = _pick(indicators, "rsi", "RSI", "rsi14")
    if isinstance(rsi, dict):
        rsi = _pick(rsi, "value", "rsi", "rsi14")

    return {
        "symbol": symbol.upper(),
        "name": pretty_name(symbol),
        "pair": display_pair(symbol),
        "price": _to_float(price),
        "change": _to_float(change),
        "signal": sig,
        "rsi": _to_float(rsi),
        "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
        "source": "live",
    }


def _to_float(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# -----------------------------------------------------------------------------
# Mock generator (used on fallback)
# -----------------------------------------------------------------------------
def _mock_row(symbol: str) -> Dict[str, Any]:
    base = _MOCK_BASE.get(symbol.upper(), 100.0)
    price = round(base * random.uniform(0.985, 1.015),
                  4 if base < 5 else 2)
    change = round(random.uniform(-6, 6), 2)
    rsi = round(random.uniform(20, 80), 1)
    sig = "BUY" if rsi >= 60 else "SELL" if rsi <= 35 else "NEUTRAL"
    return {
        "symbol": symbol.upper(),
        "name": pretty_name(symbol),
        "pair": display_pair(symbol),
        "price": price,
        "change": change,
        "signal": sig,
        "rsi": rsi,
        "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
        "source": "mock",
    }


# -----------------------------------------------------------------------------
# Public: fetch one + many
# -----------------------------------------------------------------------------
async def get_symbol_row(symbol: str) -> Dict[str, Any]:
    """Fetch signal + indicators for one symbol, normalized to a row."""
    try:
        signal = await _get(f"/api/v1/signal/{symbol}")
        try:
            indicators = await _get(f"/api/v1/indicators/{symbol}")
        except Exception:  # noqa: BLE001 — indicators optional
            indicators = {}
        return _normalize_row(symbol, signal or {}, indicators or {})
    except Exception as exc:  # noqa: BLE001
        if config.USE_MOCK_FALLBACK:
            row = _mock_row(symbol)
            row["error"] = str(exc)
            return row
        raise


async def get_rows(symbols: Optional[List[str]] = None) -> Dict[str, Any]:
    """Fetch rows for all configured symbols. Returns rows + meta."""
    symbols = symbols or config.SYMBOLS
    rows: List[Dict[str, Any]] = []
    for sym in symbols:
        rows.append(await get_symbol_row(sym))

    using_mock = any(r.get("source") == "mock" for r in rows)
    first_error = next((r.get("error") for r in rows if r.get("error")), None)
    return {
        "rows": rows,
        "meta": {
            "using_mock": using_mock,
            "updated": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
            "note": first_error,
            "count": len(rows),
        },
    }

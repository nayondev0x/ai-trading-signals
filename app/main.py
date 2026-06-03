"""FastAPI application entry point for the Trading Signal Website."""
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import coingecko_api, crypto_api, signal_engine, store, tradingview_api
from .models import Signal, SignalCreate, SignalType

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Trading Signals API", version="1.0.0")

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


# ---------------------------------------------------------------------------
# Frontend (server-rendered HTML)
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def home(request: Request, filter: Optional[SignalType] = None):
    signals = store.list_signals(filter)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "signals": signals,
            "stats": store.stats(),
            "active_filter": filter.value if filter else "ALL",
        },
    )


@app.post("/signals/create")
def create_from_form(
    symbol: str = Form(...),
    signal: SignalType = Form(...),
    entry: float = Form(...),
    target: float = Form(...),
    stop_loss: float = Form(...),
    confidence: int = Form(50),
    note: str = Form(""),
):
    store.add_signal(SignalCreate(
        symbol=symbol.upper(), signal=signal, entry=entry, target=target,
        stop_loss=stop_loss, confidence=confidence, note=note or None,
    ))
    return RedirectResponse(url="/", status_code=303)


@app.post("/signals/{signal_id}/delete")
def delete_from_form(signal_id: int):
    store.delete_signal(signal_id)
    return RedirectResponse(url="/", status_code=303)


# ---------------------------------------------------------------------------
# Live market dashboard (crypto-signal-api integration)
# ---------------------------------------------------------------------------
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    """Server-rendered shell; rows are loaded live via /api/market."""
    return templates.TemplateResponse(request, "dashboard.html", {})


async def _enrich_change_from_coingecko(rows: list) -> None:
    """Fill in 24h % change for rows missing it, using CoinGecko (best-effort).

    The TradingView endpoint doesn't return 24h change, so we backfill it.
    """
    need = [r["symbol"] for r in rows if not r.get("change")]
    if not need:
        return
    try:
        cg = await coingecko_api.get_rows(need)
        change_by_sym = {r["symbol"]: r.get("change") for r in cg.get("rows", [])}
        for r in rows:
            if not r.get("change") and change_by_sym.get(r["symbol"]) is not None:
                r["change"] = change_by_sym[r["symbol"]]
    except Exception:  # noqa: BLE001 — change is a nice-to-have
        pass


def _default_symbols() -> list:
    """The full default watchlist (crypto + US stocks) in display order."""
    return list(tradingview_api.SYMBOL_MAP.keys())


@app.get("/api/symbols")
def api_symbols():
    """List the symbols the dashboard can show, grouped by kind."""
    crypto, stocks = [], []
    for sym, meta in tradingview_api.SYMBOL_MAP.items():
        entry = {"symbol": sym, "name": meta[3], "ticker": meta[4]}
        (crypto if meta[5] == "crypto" else stocks).append(entry)
    return {"crypto": crypto, "stocks": stocks}


@app.get("/api/market")
async def api_market(symbols: Optional[str] = None,
                     provider: str = "tradingview",
                     interval: str = "1d",
                     kind: Optional[str] = None):
    """Return live signal rows for the dashboard.

    Providers (in order of reliability, best first):
      * tradingview (default) — real TradingView recommendation + RSI (RapidAPI)
      * coingecko             — free, no key, live prices + locally computed RSI
      * rapidapi              — crypto-signal-api (geo-blocked upstream; mock)

    Coverage is merged across providers: any symbol TradingView can't deliver
    (e.g. a transient stock outage) is backfilled from CoinGecko, then mock —
    so the dashboard never goes blank. Query params:
      ?symbols=BTCUSDT,AAPL  override watchlist
      ?interval=4h           1m,5m,15m,30m,1h,2h,4h,1d,1W,1M
      ?kind=crypto|stock     filter the default watchlist
      ?provider=coingecko    force a single provider
    """
    if symbols:
        requested = [s.strip().upper() for s in symbols.split(",")]
    else:
        requested = _default_symbols()
        if kind in ("crypto", "stock"):
            requested = [s for s in requested
                         if tradingview_api.SYMBOL_MAP[s][5] == kind]

    # Forced single-provider modes (no merging).
    if provider == "rapidapi":
        return await crypto_api.get_rows(requested)
    if provider == "coingecko":
        try:
            return await coingecko_api.get_rows(requested)
        except Exception as exc:  # noqa: BLE001
            data = await crypto_api.get_rows(requested)
            data["meta"]["note"] = f"CoinGecko failed ({exc}); fallback data."
            return data

    # Default: TradingView, with per-symbol backfill from CoinGecko -> mock.
    rows_by_sym: dict = {}
    notes: list = []

    try:
        tv = await tradingview_api.get_rows(requested, interval=interval)
        await _enrich_change_from_coingecko(tv["rows"])
        for r in tv["rows"]:
            rows_by_sym[r["symbol"]] = r
        if tv["meta"].get("note"):
            notes.append(tv["meta"]["note"])
    except Exception as tv_exc:  # noqa: BLE001
        notes.append(f"TradingView unavailable ({tv_exc}).")

    # Backfill anything TradingView didn't return (e.g. crypto during a stock
    # outage) using CoinGecko — but only for symbols it knows (crypto).
    missing = [s for s in requested if s not in rows_by_sym]
    if missing:
        try:
            cg = await coingecko_api.get_rows(missing)
            for r in cg["rows"]:
                rows_by_sym[r["symbol"]] = r
        except Exception as cg_exc:  # noqa: BLE001
            notes.append(f"CoinGecko backfill failed ({cg_exc}).")

    # Last resort: mock for anything still missing (keeps the table populated).
    still_missing = [s for s in requested if s not in rows_by_sym]
    using_mock = False
    if still_missing:
        mock = await crypto_api.get_rows(still_missing)
        for r in mock["rows"]:
            # Stamp correct metadata (name/pair/kind) from our symbol map so
            # mock stock rows still render & filter correctly.
            meta = tradingview_api.SYMBOL_MAP.get(r["symbol"])
            if meta:
                _tv, exch, _scr, name, ticker, k = meta
                r["name"] = name
                r["kind"] = k
                r["pair"] = (f"{ticker} / USDT" if k == "crypto"
                             else f"{exch}:{ticker}")
            else:
                r.setdefault("kind", "crypto")
            r.setdefault("strength", 50)
            rows_by_sym[r["symbol"]] = r
        using_mock = True

    rows = [rows_by_sym[s] for s in requested if s in rows_by_sym]
    return {
        "rows": rows,
        "meta": {
            "provider": "merged",
            "interval": interval,
            "count": len(rows),
            "using_mock": using_mock,
            "updated": tradingview_api._now(),
            "note": "; ".join(notes) or None,
        },
    }


@app.get("/api/market/health")
async def api_market_health():
    """Proxy the upstream crypto-signal-api /health endpoint."""
    return await crypto_api.health()


@app.get("/api/signal-explain/{symbol}")
async def api_signal_explain(symbol: str):
    """Transparency: show the indicator breakdown behind a generated signal.

    Recomputes the BUY/SELL/NEUTRAL decision from live closing prices using
    the shared signal engine and returns every contributing indicator + vote.
    """
    sym = symbol.upper()
    cg_map = getattr(coingecko_api, "SYMBOL_MAP", {})
    if sym not in cg_map:
        raise HTTPException(status_code=404,
                            detail=f"Unknown symbol '{sym}'.")
    coin_id = cg_map[sym][0]
    async with httpx.AsyncClient(timeout=15.0) as client:
        closes = await coingecko_api._series_for(client, coin_id) or []
    if len(closes) < 15:
        raise HTTPException(status_code=503,
                            detail="Not enough live history to analyze yet.")
    result = signal_engine.analyze(closes)
    return {"symbol": sym, "candles_used": len(closes), **result}


# ---------------------------------------------------------------------------
# JSON REST API (use this for a SPA / mobile client)
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/stats")
def api_stats():
    return store.stats()


@app.get("/api/signals", response_model=list[Signal])
def api_list(signal_type: Optional[SignalType] = None):
    return store.list_signals(signal_type)


@app.get("/api/signals/{signal_id}", response_model=Signal)
def api_get(signal_id: int):
    signal = store.get_signal(signal_id)
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    return signal


@app.post("/api/signals", response_model=Signal, status_code=201)
def api_create(payload: SignalCreate):
    return store.add_signal(payload)


@app.delete("/api/signals/{signal_id}", status_code=204)
def api_delete(signal_id: int):
    if not store.delete_signal(signal_id):
        raise HTTPException(status_code=404, detail="Signal not found")
    return None

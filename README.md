# 📈 TradeSignal — FastAPI + Tailwind Starter

A simple, responsive Trading Signal website. **FastAPI** backend (server-rendered
pages **and** a JSON REST API) with a **Tailwind CSS** frontend.

> ⚠️ Educational starter only — not financial advice.

## Project structure

```
trading-signals/
├── requirements.txt
├── README.md
└── app/
    ├── __init__.py
    ├── main.py            # FastAPI app: HTML routes + JSON API
    ├── models.py          # Pydantic models (Signal, SignalCreate, enums)
    ├── store.py           # In-memory data store (swap for a real DB later)
    ├── static/            # Your CSS/JS/images go here
    └── templates/
        └── index.html     # Tailwind UI (dashboard + add-signal form)
```

## Quick start

```bash
cd trading-signals

# 1. Create & activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the dev server
uvicorn app.main:app --reload
```

Then open:
- **http://127.0.0.1:8000** — the website
- **http://127.0.0.1:8000/docs** — interactive Swagger API docs

## Features

- Responsive dashboard with stats cards (mobile → desktop)
- Filter signals by BUY / SELL / HOLD
- Add & delete signals via a form
- Confidence bar with gradient
- Full JSON REST API alongside the HTML site

## API endpoints

| Method | Path                     | Description              |
|--------|--------------------------|--------------------------|
| GET    | `/api/health`            | Health check             |
| GET    | `/api/stats`             | Aggregate stats          |
| GET    | `/api/signals`           | List signals (`?signal_type=BUY`) |
| GET    | `/api/signals/{id}`      | Get one signal           |
| POST   | `/api/signals`           | Create a signal (JSON)   |
| DELETE | `/api/signals/{id}`      | Delete a signal          |

### Example: create a signal
```bash
curl -X POST http://127.0.0.1:8000/api/signals \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTC/USDT","signal":"BUY","entry":64000,"target":68000,"stop_loss":62000,"confidence":80,"note":"Breakout"}'
```

## Live market dashboard

Open **http://127.0.0.1:8000/dashboard** for a live, auto-refreshing
(every 30s) trading-signals table with columns:
**Asset Name · Current Price · Signal · Indicator Value (RSI) · Time**.

### Data source: TradingView (default)
Configured in `app/tradingview_api.py` using the RapidAPI
`tradingview-ta-api-technical-analysis` endpoint
`/get_analysis_from_symbol`. For each symbol it returns:
- a real **TradingView recommendation** (STRONG_BUY..STRONG_SELL), which we
  collapse to **BUY / SELL / NEUTRAL**, keeping the full label as a sub-line;
- **RSI** and **close price** from the indicators block;
- a **strength %** derived from the BUY/NEUTRAL/SELL vote split.

24h % change isn't in that endpoint, so it's **backfilled from CoinGecko**
(best-effort). Results are cached ~60s.

### How signals are generated (strictly from live data)
The backend **never hard-codes** a BUY/SELL/NEUTRAL — every signal is derived
from live market data of the connected hosts:

- **TradingView host** (`tradingview_api.py`): uses TradingView's own
  `summary.RECOMMENDATION` (a vote across ~26 indicators), collapsed to
  BUY / SELL / NEUTRAL.
- **CoinGecko host** (`coingecko_api.py`): pulls ~90 daily closes and runs the
  shared **signal engine** (`signal_engine.py`), which votes across:
  RSI(14), SMA20-vs-SMA50 trend, EMA12-vs-EMA26 (MACD sign), and price-vs-SMA20.
  The averaged vote → STRONG_BUY..STRONG_SELL, collapsed to 3 states.

Both produce a `signal`, a 5-level `recommendation`, an RSI value, a
`strength` %, and the underlying `votes` — all from live prices.

**Transparency endpoint:** `GET /api/signal-explain/{symbol}` recomputes the
decision from live closes and returns every indicator value + individual vote,
e.g. `{"signal":"SELL","recommendation":"STRONG_SELL","score":-1.0,
"vote_detail":{"RSI":-1,"SMA20/50":-1,"EMA12/26":-1,"Price/SMA20":-1}}`.

### Provider fallback chain (the dashboard never breaks)
`tradingview → coingecko → crypto-signal-api (mock)`

- **tradingview** (default) — richest, real recommendations.
- **coingecko** — free, no key; live prices + locally computed RSI(14).
- **crypto-signal-api** — was geo-blocked (HTTP 451); falls back to mock.

### Watchlist: crypto + US stocks
The default watchlist covers **8 cryptos** (BINANCE / crypto screener) and
**8 US stocks** (NASDAQ / america screener): AAPL, MSFT, NVDA, TSLA, AMZN,
META, GOOGL, AMD. The dashboard tags each row CRYPTO/STOCK and lets you filter
by asset type, signal, and timeframe.

### Merged coverage (no blank rows)
`/api/market` merges providers per-symbol: TradingView first, then any symbol
it can't deliver (e.g. crypto during a stock-feed outage) is backfilled from
CoinGecko, then mock. So a partial host outage never blanks the table.

Endpoints:
- `GET /api/market` — merged live rows for the default watchlist.
- `GET /api/symbols` — list available symbols grouped by kind.
- `GET /api/market?symbols=BTCUSDT,AAPL` — override symbols.
- `GET /api/market?kind=crypto` (or `stock`) — filter default watchlist.
- `GET /api/market?interval=4h` — timeframe (1m,5m,15m,30m,1h,2h,4h,1d,1W,1M).
- `GET /api/market?provider=coingecko` — force a single provider.

### Dashboard controls
- **Asset-type filter:** All / Crypto / Stocks
- **Timeframe selector:** 15m · 1h · 4h · 1D · 1W · 1M (refetches live)
- **Signal filter:** All / Buy / Sell / Neutral
- **Strength column:** a meter + % showing how lopsided the indicator vote is

### About the other RapidAPI sources tried
`real-time-future-price-api` returned **429 (quota exceeded)** and
`ai-trading-signal-api` returned **403 (not subscribed)**, so they aren't wired
in. The TradingView API worked reliably and became the default.

> ⚠️ Keep your RapidAPI key in `.env` (gitignored). If a key is ever exposed,
> regenerate it in the RapidAPI dashboard.

## Next steps / where to grow

1. **Real database** — replace `app/store.py` with SQLAlchemy + SQLite/Postgres.
2. **Auth** — add login (e.g. `fastapi-users` or JWT) so only admins post signals.
3. **Live prices** — pull market data from an exchange/API and auto-evaluate hits.
4. **Build Tailwind locally** — the page uses the Tailwind CDN for simplicity;
   for production, install Tailwind via npm and compile a `static/styles.css`.
5. **WebSockets** — push new signals to clients in real time.

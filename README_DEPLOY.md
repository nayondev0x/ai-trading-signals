# 📱 Get the dashboard on your phone

You have **two ways** to view it. Option A works right now; Option B gives you a real live link.

---

## ✅ Option A — Instant preview (no server, works now)

Open **`preview.html`** in the workspace file preview on your phone.

- It's a self-contained snapshot of **real live data** (16 assets: 8 crypto + 8 US stocks) captured from TradingView.
- The **asset filter** (All / Crypto / Stocks), **signal filter**, and **strength column** are fully interactive.
- ⚠️ It's a *snapshot* — prices don't auto-refresh and the timeframe selector is fixed to 1D (it's static). For live, use Option B.

---

## 🚀 Option B — Free public link via Render (live, auto-refreshing)

This gives you a real `https://your-app.onrender.com/dashboard` URL you can open on any phone. ~5–10 minutes, all doable from a phone browser.

### What you need
- A free **GitHub** account (to hold the code)
- A free **Render** account (https://render.com) — sign in with GitHub

### Step 1 — Put the code on GitHub
The whole `trading-signals/` folder needs to be in a GitHub repo. Easiest from a phone:
1. Go to **github.com** → **+** → **New repository** → name it `tradesignal` → **Create**.
2. Use GitHub's **"uploading an existing file"** link and upload the project files
   (or, from a computer later: `git init && git add . && git commit -m "init" && git push`).

> The repo must include: `app/`, `requirements.txt`, `render.yaml`, `Procfile`, `runtime.txt`.
> Do **NOT** upload your real `.env` (it's gitignored) — you'll set the key in Render instead.

### Step 2 — Create the service on Render
1. Go to **dashboard.render.com** → **New +** → **Blueprint**.
2. Connect your GitHub and pick the `tradesignal` repo.
3. Render reads **`render.yaml`** automatically and shows a service called
   `tradesignal-dashboard`. Click **Apply**.

### Step 3 — Add your API key (important)
Render will prompt for the env var `RAPIDAPI_KEY` (because the blueprint marks it `sync:false`).
1. Paste your RapidAPI key value when prompted (or later: service → **Environment** → **Add** → `RAPIDAPI_KEY`).
2. Save. Render redeploys automatically.

> 🔒 **Regenerate your RapidAPI key first** if it was ever pasted in chat, then use the new one here.

### Step 4 — Open it on your phone
After the build finishes (watch the **Logs** tab until it says `Uvicorn running`), Render gives you a URL like:

```
https://tradesignal-dashboard.onrender.com
```

Open **`https://tradesignal-dashboard.onrender.com/dashboard`** on your phone. 🎉

---

## Notes & tips
- **Free tier sleeps:** Render's free web service spins down after ~15 min idle; the first request after that takes ~30–50 s to wake. Normal for free tier.
- **No key? It still runs.** Without `RAPIDAPI_KEY`, TradingView calls fail and the app automatically falls back to **CoinGecko (free, no key)** for crypto + mock for stocks — so the dashboard still loads.
- **Other hosts:** the included `Procfile` also works on **Railway** (railway.app → New Project → Deploy from GitHub) and similar PaaS. The start command is:
  `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **Custom watchlist:** add `?symbols=BTCUSDT,AAPL,TSLA` or `?kind=crypto` to the `/dashboard`’s `/api/market` calls, or edit `app/tradingview_api.py`.

## Files added for deployment
| File | Purpose |
|------|---------|
| `render.yaml` | One-click Render Blueprint config |
| `Procfile` | Start command for Render/Railway/Heroku-likes |
| `runtime.txt` | Pins Python version |
| `preview.html` | Offline static snapshot for instant mobile viewing |

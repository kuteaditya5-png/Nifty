# NIFTY AI V8 — Vercel Package

This package is based on the latest `main.py` supplied on 18 Aug 2026 and keeps the existing FastAPI/NSE/yfinance dashboard while applying the V8 UI and prediction changes.

## V8 changes

- Removed the left F&O side drawer / hamburger option.
- F&O CE / PE / WAIT setup stays on the main dashboard.
- Added a completed-candle multi-timeframe confirmation layer using:
  - 5-minute EMA structure
  - reconstructed completed 15-minute EMA structure
  - ADX / directional movement
  - VWAP when valid volume is available
  - one-hour local breakout / breakdown structure
- Rebalanced live model weights so price action is an independent confirmation layer.
- Added a consensus adjustment so one extreme input is less likely to create false confidence.
- Added a clear reason under the current F&O setup, especially for WAIT.
- Added `WAIT since ...` / `Changed from WAIT at ...` timestamp under F&O Setup.
- Added browser notification + sound + in-page toast when:
  - WAIT changes to CE WATCH
  - WAIT changes to PE WATCH
  - CE changes directly to PE
  - PE changes directly to CE
- Added Recent Signal Changes on the main dashboard.
- Added CE / PE / WAIT markers directly to the NIFTY candlestick chart. The marker also includes the latest recognized completed-candle pattern when available.
- Signal history/timestamps are stored in browser `localStorage`, so they survive refreshes in that browser.
- Model version is now `8.0`.

## Important alert behavior

Click **Enable Alerts** once in the dashboard and allow browser notifications.

The dashboard checks `/prediction` every 60 seconds. A change is detected on the next successful refresh. Browser/system alerts require the dashboard to remain open; if the browser/device is closed, this client-side version cannot detect the change.

The timestamp shown is the time that this browser detected the new signal. Signal history is browser-specific and is not yet a server/database audit trail.

## Files

- `app.py` — Vercel FastAPI entrypoint and full dashboard.
- `main.py` — identical copy kept for continuity with the current project filename.
- `requirements.txt` — runtime dependencies.
- `pyproject.toml` — Python/project metadata and matching dependency constraints.
- `vercel.json` — 60-second maximum function duration for `app.py`.
- `.env.example` — environment variable template.
- `.gitignore` — excludes local secrets and Python caches.

## Vercel deployment

1. Replace the old project files with the files from this package.
2. Keep your real `NEWS_API_KEY` only in Vercel **Project Settings → Environment Variables**. Do not commit it.
3. Redeploy.
4. Open `/health`; it should report version `8.0`.
5. Test `/prediction` and then `/dashboard`.
6. On the dashboard click **Enable Alerts** and allow notifications.

Modern Vercel FastAPI deployment detects a root `app.py` containing a FastAPI `app` instance, which is why `app.py` is the deployment entrypoint in this package. `main.py` is included only as a same-code project copy.

## Main endpoints

- `/dashboard`
- `/prediction`
- `/chart-data?interval=5m`
- `/candlestick-analysis`
- `/option-chain`
- `/market-breadth`
- `/futures-analysis`
- `/premarket-analysis`
- `/institutional-flow`
- `/global-analysis`
- `/fno-alerts`
- `/backtest?period=2y`
- `/health`

## Accuracy note

V8 adds stronger confirmation logic, but this does **not** prove that live accuracy is higher. Use the existing backtest endpoint where applicable and, more importantly, collect forward/live signal history before changing real-money risk based on the new model.

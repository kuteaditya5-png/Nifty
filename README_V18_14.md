# NIFTY AI v18.14: completed-candle breakouts and journal

The previous journal only saved observations while a browser was open. This version adds an authenticated server collector and exports missing snapshots separately from WAIT. Live prediction now uses completed five-minute candles.

## Breakout evidence

Reference reviewed: https://github.com/kuteaditya5-png/Stocklens/blob/098c43aae37768479fc155138fe97aa685b39a01/lib/nifty-index.js (MIT notice included).

- Opening range requires the exact 09:15, 09:20 and 09:25 IST candles. Levels become available from 09:30.
- Rolling levels use six preceding consecutive candles in the same session.
- A new completed close beyond a level by max(1 point, 10% of mean prior range) is a crossing. Wick-only rejection is shown separately.
- Confirmation also requires a directional body of at least 50% of candle range, close in the outer 30%, and EMA9/EMA21 agreement with at least 21 bars of warm-up.
- Confirmed fresh evidence can adjust the existing combined model score by at most 0.05. Agreement increases conviction; opposition reduces it. Correlated ORB and rolling evidence receive a single adjustment. Existing option/coverage/direction thresholds remain in place.
- Signal strength is a heuristic score, not a calibrated probability or measured accuracy. The adjustment is not validated as an improvement in profitability.
- Five-minute charts show opening-range and rolling levels, confirmed/unconfirmed crossings, rejections and data-quality markers. Other intervals clear these overlays.
- Zero-range bars and suspicious closing spikes are flagged without altering provider prices. A flagged/stale/latest out-of-session candle blocks live WATCH and option BUY/WATCH alerts. Index volume is not fabricated.

## Collection setup

Server environment:
- DATABASE_URL: existing PostgreSQL connection; schema creation permission is needed for nifty_server_decisions.
- NIFTY_MONITOR_SECRET: long random private value for collection. Never commit it.
- SIGNAL_EXPORT_KEY: existing export key remains required.

GitHub Actions repository secrets:
- NIFTY_SITE_URL: deployed HTTPS site origin.
- NIFTY_MONITOR_SECRET: same value as server environment.

The existing .github/workflows/nifty-monitor.yml now calls POST /api/signal-journal/collect. It runs at five-minute intervals, offset one minute from candle boundaries, and is usable through workflow_dispatch. GitHub schedules run from the default branch and may be delayed; a draft branch alone does not activate collection.

For continuous collection on an always-on host, set NIFTY_SITE_URL and NIFTY_MONITOR_SECRET and run `python monitor_worker.py` under a service supervisor. It polls every 30 seconds; PostgreSQL locking and per-candle uniqueness prevent duplicate snapshots. This worker must run separately from Vercel, whose request process is not an always-on scheduler.

The collector records only current live inputs. It does NOT reconstruct historical option chains, news or decisions after downtime. Missing elapsed buckets are marked MISSING on the next successful same-day collection, never converted to WAIT. Entire sessions with no successful collection do not appear; check scheduler run history as well as coverage. Sessions are inferred from fresh provider candles, not a hardcoded exchange holiday calendar. Capture delay is exported. No browser is required while the collector is running.

## Export and replay

Download calls Excel now includes Server Decisions, Collection Coverage, Dashboard Observations and Read Me. Server rows include live WATCH, separate CE/PE alert states, shadow decision, failed WATCH gates, option availability, alert warnings, score adjustment and quality flags. Browser observations remain intact in the old table. No executed trades are claimed.

Candle export retains raw prices and adds Data Quality Flags and Candle Quality Eligible. Existing descriptive breakout labels are retained for comparison, even on flagged rows; consumers must honor the quality flag.

Shadow replay preserves prior-session warm-up when filtering a requested date, excludes forming bars and flags suspicious source candles. Directional outcomes do not cross session boundaries or flagged future candles. Shadow decisions do not override live option gates.

## Validation and rollout

Run `python -m pytest -q tests/test_v1814.py` after installing requirements.txt and pytest/httpx. Tests cover incomplete/duplicate bars, missing opening candles, look-ahead independence, rejection, score bounds, session reset, source anomalies, monitor authorization, duplicate suppression, missing-vs-WAIT export behavior, JSON serialization and API responses with mocked providers. All 14 Python tests and the Node chart-renderer test passed locally. Run `node tests/chart_v1814.test.cjs` to check marker generation and interval cleanup. Database unit checks mock the connection; a real PostgreSQL integration check remains necessary on deployment. Dashboard scripts parsed successfully; visual browser verification could not run because the browser download was unavailable.

The supplied 2 November candle file was used locally: the 15:20 zero-range bar and 15:25 closing spike are flagged. The file is not committed. This one-day review is not an accuracy backtest and cannot validate option-premium targets.

After deployment, trigger the workflow during market hours, confirm a CAPTURED row and capture delay, close the dashboard, then verify later server rows and coverage. An invalid secret must return HTTP 403. Keep paper validation active while measuring results across multiple sessions.

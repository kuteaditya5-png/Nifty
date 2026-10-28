NIFTY AI v18.11 - ready-to-upload changed files

Replace main.py and requirements.txt in GitHub repository root. Add signal_tracker.py in root. Do NOT upload this README unless desired. Vercel redeploys from main.

Vercel environment: DATABASE_URL must point to PostgreSQL; add SIGNAL_EXPORT_KEY (long random private value), redeploy. Do not publish this key.

Dashboard: /dashboard. Buttons: Download chart PNG, Download chart candles Excel (OHLCV), Download calls Excel.

IMPORTANT: Journal records browser-observed signals only when dashboard is open, not autonomous signals. 5/10/15/30m follow-up performance tracking is NOT implemented in this build. NIFTY candle Excel fetches ^NSEI data from Yahoo at download time, which may differ from dashboard source. Option premium not tracked. Chart PNG requires Lightweight Charts chart instance to be available.

Keep existing Vercel config and other repo files unchanged. Test exports and Vercel logs after deployment.

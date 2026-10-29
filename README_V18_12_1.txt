NIFTY AI v18.12.1 - Prediction Shadow + Export Quality Fixes

Upload main.py, prediction_v1812.py, signal_tracker.py and requirements.txt to GitHub root. Preserve other repo files and Vercel settings.

Prediction engine remains SHADOW mode; it does NOT replace production BUY/WAIT decisions.

Export improvements:
- Capture NIFTY spot price from latestPrediction.price when available (previous exports had blank price).
- Record only during regular IST market hours; logging remains browser-dependent.
- Label WAIT candidate options as NOT executable trades.
- Display unavailable NIFTY index volume as blank, not misleading zero.
- Keep export key in browser tab session only; re-prompt after a 403.
- Add Read Me sheet describing observational limitations.
- Older database rows with missing spot price cannot be recovered automatically.

Set DATABASE_URL and a UNIQUE private SIGNAL_EXPORT_KEY in Vercel. Never reuse an Upstox API token as an export key. Redeploy without build cache if dependencies were changed.

Tomorrow: compare /api/v18-12/shadow with the existing prediction during 09:15-15:15 IST, then review historical replay; do not judge accuracy from a single day.

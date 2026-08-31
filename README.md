# NIFTY AI V9 – Vercel Deployment

This package is built from the latest uploaded V8 `main.py`.

## Visible dashboard
- Unified NIFTY prediction
- CE / PE / WAIT state with timestamp and browser alert
- One ranked suggested NIFTY option contract
- Entry zone, stop-loss, Target 1, Target 2
- Prediction markers and a heuristic 15-minute projected level on the candlestick chart
- Recent signal-change history

All detailed signal engines continue to run in the backend.

## V9 model additions
- 5m + 15m + 30m completed-candle price-action confirmation
- ADX/DI, optional VWAP and relative-volume confirmation
- conflict detector between major signal layers
- market-hours / stale-data gate for live BUY signals
- expiry-aware option selection
- nearby strike ranking using moneyness, OI, change in OI, volume, bid/ask spread when available, IV and estimated delta

## Deploy
1. Upload all files in this folder to the Vercel project root.
2. Keep `app.py` at the root.
3. In Vercel Environment Variables, keep/set `NEWS_API_KEY`.
4. Deploy.
5. Check `/health`; it should return version `9.0`.
6. Open `/dashboard` and click **Enable Alerts** once.

## Important
The app uses public/near-live data sources. yfinance is not exchange-grade tick data, and NSE endpoints can occasionally block/change. BUY/WATCH signals are heuristic decision support and do not place orders.

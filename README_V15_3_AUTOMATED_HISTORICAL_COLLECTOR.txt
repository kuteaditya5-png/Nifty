NIFTY AI v15.3 — Automated Historical Data Collector

NEW
- Auto Collect History v15.3 button.
- Uses Upstox Historical Candle Data V3 for genuine NIFTY 50 15-minute OHLC candles.
- Pulls the v15.2 suggested older range in <=30-day chunks.
- Normalizes, upserts and deduplicates candles into the existing persistent history store.
- Recalculates progress toward 200 trading sessions after collection.
- Never fabricates missing candles.

VERCEL SETUP REQUIRED
1. Create/obtain an Upstox API access token.
2. Vercel Project -> Settings -> Environment Variables.
3. Add: UPSTOX_ACCESS_TOKEN = your current Upstox access token
4. Optional: UPSTOX_NIFTY_INSTRUMENT_KEY = NSE_INDEX|Nifty 50
5. Redeploy after changing environment variables.

TEST
1. Open Dashboard -> Backtest.
2. Click Acquisition Progress v15.2 and note current sessions.
3. Click Auto Collect History v15.3.
4. Confirm fetched/written counts and session count increase.
5. Repeat only if still below 200.
6. At 200 sessions, run Data Quality & Gap Check and Backtest Readiness Gate.

Provider basis: Upstox Historical Candle Data V3 supports minute intervals including 15-minute candles and historical minute data from January 2022, with up to one month per request for 1–15 minute intervals.

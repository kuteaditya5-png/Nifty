NIFTY AI v15.1 — Historical Dataset Expansion

Added:
- Expand / Plan 200 Sessions v15.1 button.
- Refreshes the provider's currently recoverable 60-day 15m window before planning.
- Calculates exact remaining sessions to the 200-session research target.
- Identifies priority missing-date ranges inside the existing store.
- Calculates a suggested older backfill range when more sessions are required.
- Keeps the v15.0.x multi-file CSV validation/merge/deduplication pipeline.
- Never fabricates unavailable historical candles.

Test:
1. Deploy this package to GitHub/Vercel.
2. Open Backtest.
3. Click Expand / Plan 200 Sessions v15.1.
4. Confirm it reports current candles, sessions, coverage, sessions still needed, and a suggested backfill range.
5. Import genuine 15-minute NIFTY CSV file(s) covering older dates with Build / Merge Dataset v15.1.
6. Click Dataset Builder Status and Data Quality & Gap Check v14.8.
7. Repeat import until the store reaches the desired historical coverage; 200+ sessions is preferred.
8. Then run Regime-Aware Walk-Forward v14.4 and Extended Historical Validation v14.5.


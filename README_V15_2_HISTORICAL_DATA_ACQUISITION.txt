NIFTY AI v15.2 — Historical Data Acquisition

Purpose
- Turn the v15.1 200-session expansion plan into a measurable acquisition workflow.
- Preserve the persistent PostgreSQL candle store and multi-file CSV merge/deduplication.
- Never fabricate missing candles.

New UI
- Historical Dataset section is labelled v15.2 HISTORICAL DATA ACQUISITION.
- Build / Merge Dataset v15.2 accepts multiple genuine 15-minute NIFTY CSV files.
- Acquisition Progress v15.2 reports current sessions / 200, progress %, remaining sessions, suggested older range and priority internal gaps.

Recommended test
1. Open Backtest and click Acquisition Progress v15.2.
2. Confirm current session count and remaining target are shown.
3. Import one or more genuine NIFTY 15-minute CSV files with Build / Merge Dataset v15.2.
4. Click Acquisition Progress again and confirm session count only increases when new dates were actually added.
5. Re-import the same file: deduplication should prevent fake growth.
6. At 200+ sessions, run Data Quality & Gap Check then Backtest Readiness Gate.

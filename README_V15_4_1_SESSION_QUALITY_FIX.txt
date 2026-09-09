NIFTY AI v15.4.1 — Session Quality / Timezone Fix

Fixes the v14.8 historical quality checker when persistent candle timestamps are returned in UTC.
The diagnostic frame is normalized to Asia/Kolkata before matching NSE 15-minute session slots (09:15–15:15).
This prevents valid Upstox candles from being incorrectly classified as severe gaps solely because of timezone offset.

TEST
1. Deploy this package.
2. Run Data Quality & Gap Check v14.8.
3. Confirm full/partial session counts are now plausible and severe-gap is no longer every session.
4. Run Backtest Readiness Gate.
5. If READY, run Full Validation v15.4.

The fix does not fabricate candles, relax quality thresholds, or alter stored historical timestamps.

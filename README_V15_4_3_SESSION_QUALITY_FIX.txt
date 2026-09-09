NIFTY AI v15.4.3 — Session Quality Fix

Changes:
- Data Quality & Gap Check now uses the same Asia/Kolkata timestamp normalization as v15.4.2 diagnostic.
- Session grouping occurs only after timezone conversion.
- 15-minute NSE session grid is 09:15 through 15:15 IST (25 candles).
- FULL/PARTIAL/SEVERE_GAP are recalculated from actual expected IST slots.
- Median interval is calculated within sessions, avoiding overnight/weekend distortion.
- Backtest Readiness Gate automatically consumes the corrected quality report.
- Stored historical candles are not modified or fabricated.

Test order after deployment:
1. Session Timestamp Diagnostic v15.4.2
2. Data Quality & Gap Check v15.4.3
3. Backtest Readiness Gate
4. Run Full Validation v15.4 only if readiness is READY.

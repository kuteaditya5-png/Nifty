NIFTY AI v14.7.1 — Backfill Parser Fix

Fixes
-----
- 2-row template now correctly detects a 15-minute interval.
- Better Date + Time parsing.
- Supports DD-MM-YYYY / DD/MM/YYYY / YYYY-MM-DD styles.
- Supports Unix timestamps in seconds or milliseconds.
- Reports:
  * input rows
  * timestamps parsed
  * timestamp failures
  * valid OHLC rows
  * detected median interval
- Better error messages when a file cannot be parsed.

Important
---------
The included 2-row CSV is only a format template.
For meaningful historical validation, import a real NIFTY 50 INDEX
15-minute OHLC file with at least 6-12 months of data.

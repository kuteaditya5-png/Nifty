NIFTY AI v18.10 — chart directly below Current Prediction.

Replace main.py in GitHub main branch; keep entry_confirmation_v187.py and auth.py and .github workflow unchanged.
No new secrets or DB changes.
5-minute chart shows CE/PE confirmation marker only when the confirmed candle timestamp exactly matches a chart bar and the final prediction agrees. No marker for WAIT, false breakouts, stale/missing data or 1m/15m.
Important: chart feed is yfinance and can lag the entry confirmation feed. If times differ, marker is deliberately withheld.
Check live behavior and signal persistence during market hours before relying on signals.

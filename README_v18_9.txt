NIFTY AI v18.9 — Option 1 dashboard reference layout

Changed: main.py only.
Existing v18.8 entry_confirmation_v187.py and GitHub workflow are preserved in the package.

Deploy: Replace main.py in your GitHub repository, commit to main, and wait for Vercel deployment.
If you have not deployed v18.8, also upload entry_confirmation_v187.py.
Keep auth.py, requirements, Vercel env vars and GitHub Actions secrets as-is.

UI additions:
- Clear BUY CE / WAIT / BUY PE decision based on final gated fno_setup.
- NIFTY spot, direction, confidence.
- Opening-range high/low, breakout type, completed candle time, reason.
- EMA, Supertrend, ADX, RSI, VWAP, ATR (unavailable values show --).
- Suggested option and entry/target/SL only when confirmed and available from live API.
- ORB HIGH / ORB LOW dashed price lines on 5-minute chart.
- Responsive phone layout.

The screenshot is a visual reference, not a source of real trading numbers.
No fabricated option premiums or targets are shown.

IMPORTANT: Live data and DB storage must still be verified during market hours.
This package does not guarantee prediction accuracy or real-time alert delivery.

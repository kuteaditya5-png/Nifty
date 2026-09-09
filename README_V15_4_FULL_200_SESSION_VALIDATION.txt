NIFTY AI v15.4 — Full 200-Session Strategy Validation

What changed
- Added Run Full Validation v15.4 button to Backtest panel.
- Added /v15/full-validation endpoint.
- Validation uses the persistent 15-minute historical store collected by v15.3, not a fresh short yfinance window.
- Chain: Data Quality/Readiness -> Regime x Engine Matrix -> extended unseen walk-forward -> signal edge vs seeded random baseline -> PASS/PROMISING/FAIL.
- Requires a backtest-ready store and at least 200 trading sessions for the full gate.

How to test
1. Deploy this package with the existing Vercel environment variables unchanged.
2. Open Dashboard -> Backtest.
3. Run Data Quality & Gap Check v14.8. Confirm BACKTEST READY YES.
4. Run Backtest Readiness Gate. Confirm READY.
5. Click Run Full Validation v15.4 once.
6. Capture the complete v15.4 result line and share it for review.

Important
v15.4 validates NIFTY price-direction signal quality. It does not claim historical CE/PE premium P&L accuracy because the project does not yet store historical option-premium snapshots.

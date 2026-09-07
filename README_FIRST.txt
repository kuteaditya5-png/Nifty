NIFTY AI v12.3 — Signal Quality Optimizer

New:
- Optimize + Walk-Forward button in Backtest panel
- tests threshold 0.30, 0.35, 0.40, 0.45, 0.50
- tests BOTH / CE-only / PE-only
- tests market-regime combinations
- chronological 70% training / 30% unseen validation
- reports training and unseen validation PF, expectancy, return, drawdown and verdict
- live prediction logic is NOT automatically changed by optimizer results

Important:
The current backtest remains a NIFTY directional proxy, not literal historical option-premium P&L.
Only consider promoting a configuration after unseen validation passes with a meaningful sample.

Deploy:
Replace your repo root files with this package and redeploy Vercel.

NIFTY AI v12.2 - Backtest Audit & Validation

WHY THIS VERSION
The previous 30-day result showed roughly:
- Rs 60k final capital from Rs 1 lakh
- ~40% win rate
- profit factor below 1
- severe drawdown

v12.2 does NOT try to hide that failure by changing settings blindly.
It audits the backtest.

NEW
- PASS / CAUTION / FAIL verdict
- CE / PE / WAIT counts
- WAIT ratio
- CE win rate
- PE win rate
- expectancy per trade
- average win / average loss
- max consecutive losses
- regime breakdown
- risk-adjusted dynamic threshold
- configurable fees
- configurable slippage
- detailed trade audit:
  timestamp, CE/PE, score, threshold, regime, entry, exit reason, P&L, capital

BACKTEST LOGIC
- one open position at a time
- WAIT creates no trade
- high-volatility and sideways regimes require stronger signal thresholds
- opening/closing periods are more selective
- stop is checked before target inside the same bar (conservative)
- fees and slippage reduce P&L

IMPORTANT
This is still a NIFTY directional proxy backtest because the project does not
contain historical option premium/OI/IV snapshots for every past candle.
Do not interpret proxy capital results as literal historical CE/PE contract P&L.

PASS guideline in this build:
- profit factor >= 1.30
- positive expectancy
- max drawdown <= 20%

CAUTION:
- profit factor >= 1.0
- non-negative expectancy
- max drawdown <= 30%

Otherwise: FAIL.

DEPLOY
Replace the files in your GitHub repo root with the files in this ZIP,
then redeploy Vercel.

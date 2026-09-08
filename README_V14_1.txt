NIFTY AI v14.1 — Signal Edge Diagnostic

Purpose
-------
Before optimizing stops, targets, fees, slippage or position sizing, determine
whether the CE/PE prediction direction itself has measurable predictive edge.

New endpoint
------------
GET /v14/signal-edge

New dashboard action
--------------------
Backtest -> Signal Edge Diagnostic v14.1

It compares:
- TREND engine
- REVERSION engine
- BLENDED engine

For every non-WAIT signal it measures NIFTY direction after:
- 1 candle
- 3 candles
- 6 candles
- 12 candles

Outputs:
- Directional accuracy
- Average directional move in basis points
- Median directional move
- WAIT ratio
- Performance by TRENDING / RANGE / HIGH_VOLATILITY regime
- Seeded random-side baseline on the same signal timestamps
- Edge vs random
- Best engine
- EDGE DETECTED / WEAK / NO RAW SIGNAL EDGE verdict

Important
---------
This diagnostic intentionally ignores stop-loss, targets, transaction fees,
slippage and position sizing. It is designed to isolate prediction quality.

Do not promote new live thresholds solely because a backtest return improves.
First establish raw signal edge, then optimize execution separately.

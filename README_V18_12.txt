NIFTY AI v18.12 — Research/Shadow Prediction Build

Upload main.py, prediction_v1812.py, signal_tracker.py and requirements.txt to the repository root.
Keep your existing vercel_entry.py, vercel.json, and all other repository files unchanged.

New read-only endpoints:
/api/v18-12/shadow — latest research-only CE/PE/WAIT using completed 5-minute candles
/api/v18-12/replay?date=2026-10-29 — chronological replay on a date available from Yahoo

This build deliberately DOES NOT override the existing live /prediction logic.
It tests a price-action alternative requiring EMA9/21/50 trend alignment,
MACD direction, RSI regime and a completed-candle breakout/pullback.
Replay evaluates direction after three 5m bars (15m), without option premiums,
slippage, commissions, or non-overlapping trade controls. Do not use hit rate as
proof of trading profitability. Yahoo 5m history has limited availability.

Key finding from existing code: the existing CE/PE watch is gated by
`option_available` and `option_score` as well as combined_score and confirmations.
When option-chain data is missing, both sides necessarily remain WAIT, even if
NIFTY trends. v18.12 shadow signals allow us to diagnose this separately.

Next: compare replay and live predictions over several unseen trading sessions,
then promote only validated changes to the live strategy.

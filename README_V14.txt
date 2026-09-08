NIFTY AI v14.0 — Routed Prediction Engine + Frozen Prediction Zone

PREDICTION ARCHITECTURE
Market Regime
  -> TREND engine for trending markets
  -> REVERSION engine for range/mean-reverting markets
  -> defensive trend handling for event/high-volatility markets
  -> Context Filters: Options, Breadth, FII/DII, Futures
  -> CE / PE / WAIT

The existing broad v13.5 blend is retained as a 28% stabilizer while the
new routed engine contributes 72%. This avoids an uncontrolled hard reset.

FROZEN CHART PREDICTION
- Prediction timestamp is tied to the latest completed candle when available.
- Forecast candles are saved in browser localStorage using:
  interval + prediction timestamp
- Page refresh / live chart refresh does NOT regenerate that forecast.
- Actual candles continue updating.
- The label shows FROZEN AI PREDICTION and its locked timestamp.
- A new completed-candle prediction gets a new frozen forecast.

WHY
This prevents visual repainting/hindsight and makes it easier to compare
what the model predicted with what the market actually did.

IMPORTANT
This remains a validation/paper-trading system. Backtest results do not
guarantee real F&O profitability.

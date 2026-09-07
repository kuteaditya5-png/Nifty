NIFTY AI v10.1 - Prediction Zone UI

This build keeps all v10 functionality:
- mobile number + password login
- exact-contract paper P&L
- per-user paper portfolio
- prediction accuracy tracker
- WhatsApp support when configured

NEW
- Dashboard redesigned to match the approved NIFTY AI reference style.
- AI Prediction Zone is ALWAYS shown after every prediction cycle.
- It does NOT depend on buying a paper trade.
- BUY CE = green prediction zone and upward estimated candles.
- BUY PE = red prediction zone and downward estimated candles.
- WAIT = amber prediction zone with a narrow/sideways estimated path.
- Prediction start is marked on the latest actual candle.
- AI Insights and Prediction Summary panels are shown beside the chart.
- The estimated candles are clearly labelled as model projections, not actual market candles.

IMPORTANT
The future candles are a visualization derived from current model direction,
confidence, combined score and recent candle volatility. They are not guaranteed
future prices and should be used for validation/paper trading only.

DEPLOY
Replace files in GitHub root with all files from this ZIP, then redeploy Vercel.
No environment-variable changes are required from v10.

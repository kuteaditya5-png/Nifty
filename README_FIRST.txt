NIFTY AI v12 - Backtest Sidebar

NEW
- Left-side navigation panel.
- Dashboard button.
- Backtest button.
- Backtest opens as a left-side panel without replacing the main dashboard.
- Starting capital defaults to Rs 1,00,000.
- 30-day / 60-day historical replay.
- Configurable signal threshold.
- Configurable risk per trade.
- Configurable reward:risk.
- Compounding ON/OFF.
- Final capital, return %, trades, win rate, profit factor and max drawdown.
- Equity curve.
- Trade-by-trade backtest history.

BACKTEST MODE
This first v12 backtest is a NIFTY DIRECTION PROXY.
It replays historical NIFTY candles chronologically and uses only information
available at each candle.

It DOES NOT invent historical option premiums/OI/IV.
Therefore the Rs 1,00,000 simulation uses risk-per-trade capital sizing rather
than pretending we bought historical CE/PE contracts at unavailable prices.

Existing features retained:
- mobile + password login
- no WhatsApp/Twilio
- v11 feature engine
- paper trading
- exact-contract live paper P&L
- prediction accuracy tracker
- walk-forward validation
- AI Prediction Zone

DEPLOY
Replace the GitHub root files with the files from this ZIP and redeploy Vercel.

Core environment variables:
DATABASE_URL
JWT_SECRET
NEWS_API_KEY

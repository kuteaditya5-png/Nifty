NIFTY AI v11 - Feature + Validation Upgrade

This package keeps:
- Mobile number + password login
- Exact-contract paper P&L
- Per-user paper portfolios
- Accuracy tracker
- Always-visible AI Prediction Zone
- WhatsApp support when configured

NEW PREDICTION FEATURES
1. Technical:
   - SMA 20/50
   - Stochastic K/D
   - Bollinger Band width and %B
   - ATR 14
   - Existing EMA/RSI/MACD retained

2. Statistical / normalized:
   - 1/3/6-bar returns
   - log return
   - rolling volatility
   - annualized realized volatility
   - 20-bar price z-score

3. Volume:
   - relative volume vs 20-bar average
   - OBV 5-bar change
   - VWAP deviation
   - automatically excluded when NIFTY index volume is unavailable/zero

4. Breadth:
   - advance/decline
   - 52-week high / low proximity count when NSE supplies those fields

5. Cross-asset / context:
   - Bank Nifty
   - DXY
   - US 10-year yield
   - EEM as an emerging-market proxy

6. Volatility:
   - India VIX level
   - India VIX daily/session change
   - realized vs ATM implied volatility spread

7. Time / event risk:
   - opening / midday / closing session phase
   - day of week
   - F&O expiry-day flag
   - optional event-day and holiday-adjacent flags
   - risky sessions automatically raise the CE/PE threshold

OPTIONAL VERCEL ENVIRONMENT VARIABLES
NIFTY_EVENT_DATES=2026-09-30,2026-10-07
NIFTY_HOLIDAY_DATES=2026-10-02,2026-11-09

VALIDATION
New endpoint:
  /validation/walk-forward

It uses expanding-window threshold calibration with chronological unseen test blocks.
It reports:
- directional accuracy
- signal precision
- bullish precision / recall / F1
- bearish precision / recall / F1

IMPORTANT:
The walk-forward endpoint is explicitly a PRICE-FEATURE proxy because we do not have
historical option-chain, FII/DII and news snapshots for the full live model.
It must not be treated as full-model historical accuracy.

DEPLOY:
Replace all files in your GitHub repo root with the files in this ZIP and redeploy Vercel.
No database migration is required.

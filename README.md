# NIFTY AI V7 - F&O Alert Engine

Version 7 keeps the existing dashboard and prediction model, and adds a
CE/PE F&O alert layer.

## New F&O features

For CALL (CE) and PUT (PE), independently:

- WAIT
- WATCH
- BUY SIGNAL
- ATM strike selection
- Current option premium (LTP)
- Entry zone
- Premium stop-loss
- Target 1
- Target 2
- NIFTY invalidation level
- Signal strength
- Confirmation/warning reasons
- Browser-side signal lifecycle monitoring
- STOP LOSS HIT alert
- TARGET 1 alert
- TARGET 2 / exit alert
- Model-reversal EXIT alert
- NIFTY-invalidation EXIT alert
- Recent alert history stored in the user's browser
- Optional browser notification + alert tone

The engine never places orders.

## New endpoint

`/fno-alerts`

It returns the current CE and PE alert snapshot.

## Existing endpoints

- `/health`
- `/dashboard`
- `/prediction`
- `/market-breadth`
- `/futures-analysis`
- `/premarket-analysis`
- `/option-chain`
- `/backtest?period=2y`

## Alert logic

A BUY SIGNAL is intentionally conservative and requires sufficient live-data
coverage plus agreement between the combined model, probability, option-chain
score and price-action confirmations.

CE and PE are evaluated independently. Both may remain WAIT.

The premium stop is volatility-aware. The engine also builds an underlying
NIFTY invalidation from immediate option-chain structure and intraday ATR.

Targets are generated from premium risk:

- Target 1: 1.2R
- Target 2: 2.0R

## Browser alert lifecycle

When the live engine generates a BUY SIGNAL, the dashboard stores the generated
signal in browser localStorage and monitors it on future dashboard refreshes.

It can produce:

- STOP LOSS HIT
- TARGET 1 HIT
- TARGET 2 HIT
- EXIT SIGNAL when NIFTY invalidation is breached
- EXIT SIGNAL when the model reverses

This is browser-local state. Clearing browser storage removes the local signal
history.

Browser alerts currently work while the dashboard is open. A future persistent
worker/notification service is needed for reliable closed-browser monitoring.

## Deployment

Replace the `app.py` in the existing GitHub repository with this package's
`app.py`, commit to the main branch, and let Vercel redeploy.

Keep the Vercel environment variable:

`NEWS_API_KEY`

After deployment test:

1. `/health`
2. `/prediction`
3. `/fno-alerts`
4. `/option-chain`
5. `/dashboard`
6. `/backtest?period=6mo`

## Important

BUY SIGNAL means the project's programmed rule set triggered. It is not a
guarantee of profit and it does not execute a trade. The F&O alert rules should
be backtested and forward-tested before being trusted with real capital.

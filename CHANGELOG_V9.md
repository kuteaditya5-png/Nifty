# NIFTY AI V9 changes

- Simplified dashboard to one unified prediction, one suggested option, chart and signal history.
- Removed detailed analysis cards from the visible dashboard; their backend calculations remain active.
- Added 30-minute trend confirmation to the existing 5m/15m price-action layer.
- Added optional relative-volume confirmation when usable volume is available.
- Added conflict detection across technical, price action, option chain, candlestick, breadth and futures layers.
- Added IST market-session and stale-data gating so live BUY signals are not issued from closed/stale sessions.
- Added expiry-day context.
- Added strike ranking rather than always using the nearest ATM contract.
- Strike ranking uses moneyness/distance, OI, volume, bid/ask spread when available, IV, estimated delta and change in OI.
- Added a single `trade_decision` (`CE BUY`, `PE BUY`, `CE WATCH`, `PE WATCH`, `WAIT`) and `suggested_trade` object.
- Added heuristic 15-minute projected level for chart display when the directional score is strong enough.
- Retained WAIT change timestamps, CE/PE reversal alerts and chart markers.

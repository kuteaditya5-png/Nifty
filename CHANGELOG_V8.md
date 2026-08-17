# NIFTY AI V8 Change Log

## Dashboard
- Removed F&O sidebar/drawer and hamburger launcher.
- Added main-card WAIT reason and signal-change timestamp.
- Added Enable Alerts button.
- Added in-page toast notification.
- Added Recent Signal Changes card.
- Added prediction/candlestick markers to Lightweight Charts.

## Prediction engine
- Added `calculate_price_action_confirmation()`.
- Uses completed 5m candles to reduce repainting.
- Adds reconstructed completed 15m trend confirmation.
- Adds ADX/DI, optional VWAP, and breakout state.
- Adds `price_action` to regime-adjusted weighted model.
- Adds cross-signal consensus adjustment to scenario probabilities.
- Makes CE/PE watch setup require non-opposing price action.
- Adds `fno_setup_reason` and `signal_generated_at` to `/prediction`.

## Alert state
- Browser localStorage tracks the current F&O setup and its detected change time.
- WAIT → CE/PE and CE ↔ PE trigger notification/sound/toast.
- Historical signal changes are plotted on the chart by snapping the detection time to the nearest available chart candle.

## Compatibility
- Existing NSE option chain, FII/DII, breadth, futures, VIX, news, global cues, F&O alert engine and backtest routes are preserved.

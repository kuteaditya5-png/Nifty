NIFTY AI v14.5 — Extended Historical Validation

Purpose
-------
Increase the historical sample before changing live prediction logic.

New endpoint
------------
GET /v14/extended-validation

New dashboard action
--------------------
Backtest -> Extended Historical Validation v14.5

What it does
------------
- Attempts to load up to ~6 months of 15-minute NIFTY history.
- Falls back to shorter available intraday history when the upstream provider
  cannot supply the full request, and reports the actual usable period.
- Re-runs Regime × Engine Matrix on the larger sample.
- Runs expanding-window unseen validation across up to 6 folds.
- Reports historical candle count/date range, regime counts, best engine/regime,
  unseen H6 accuracy, unseen directional bps, signal count, degradation,
  stable threshold, and promotable YES/NO.

Important
---------
This is a validation build only. Live routing is not changed automatically.

Persistent login, frozen prediction zone, signal-edge diagnostic,
regime matrix and v14.4 walk-forward remain included.

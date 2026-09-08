NIFTY AI v13 — Edge Diagnostics

WHAT CHANGED FROM v12.3
-----------------------
v12.3 backtested at 36.2% win rate against a 40.0% coin-flip baseline for
its own stop/target geometry. The signal was subtracting value, so threshold
and filter tuning could not have helped. Causes found:

  - zscore and bb_percent_b (mean-reversion measures) were summed with a
    momentum sign, so a stretched-up market read as more bullish
  - 7 of 10 score components were the same trend factor
  - max_hold=6 gave 90 minutes to travel 1.5 x ATR; the stop was simply nearer
  - entry filled at the same close the score was computed from
  - positions held overnight in an intraday options product
  - the optimizer post-filtered a fixed, truncated trade list rather than
    re-running the engine, so its walk-forward results were invalid

NOTHING IN v12.3 WAS REMOVED
----------------------------
/backtest/run and /backtest/optimize behave exactly as before. v13 lives on
separate routes so you can compare the two side by side.

NEW ROUTES
----------
  /v13/edge-report   RUN THIS FIRST. Is there any edge to tune?
  /v13/baseline      Coin-flip win rate for a given stop/target geometry
  /v13/backtest      Next-bar entry, session-bounded, symmetric slippage
  /v13/optimize      Re-runs the engine per config, validates on unseen bars
                     Add ?fast=true if it times out on Vercel

DEPLOY
------
Replace your repo root files with this package and push. Vercel redeploys
automatically. Confirm with:

  your-app.vercel.app/v13/baseline?reward_risk=1.5   -> should return 40.0

THEN
----
1. Open /v13/edge-report and read the fwd_6bar row.
     below -0.02  -> component is backwards, flip its sign
     above +0.03  -> real, build around it
     all inside +/-0.02 -> stop tuning; price indicators on 15m have no edge
2. Test each leg alone: /v13/backtest?use_reversion=false then true
3. Optimize locally (uvicorn main:app --reload), read only the validation block
4. Promote nothing unless validation is PASS with >=30 trades and
   overfit_degradation_r < 0.10

IMPORTANT
---------
This backtests NIFTY spot while the product signals options. Theta decay and
bid-ask on a ~15 rupee premium will consume much of any spot edge this proves.
A PASS here is necessary, not sufficient. Paper-trade before risking money.

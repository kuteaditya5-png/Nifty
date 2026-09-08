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
                     ALWAYS add ?fast=true on Vercel (300 runs will time out).
                     Run the full grid locally instead:
                       uvicorn main:app --reload
                       localhost:8000/v13/optimize

DEPLOY
------
Replace your repo root files with this package and push. Vercel redeploys
automatically.

vercel.json is UNCHANGED from v12.3. Do not add a "functions" block to it,
because Vercel rejects "functions" and "builds" in the same file. If you want
a longer serverless timeout you must first migrate off "builds" entirely,
which is a separate change and not needed here. Use ?fast=true instead.

Confirm the deploy with:

  your-app.vercel.app/v13/baseline?reward_risk=1.5   -> should return 40.0

EDGE REPORT RESULT (60d to 2026-09-08, 1455 bars)
-------------------------------------------------
All 9 momentum indicators were NEGATIVE at all 4 horizons.
reversion_score was POSITIVE at all 4. NIFTY 15m was mean-reverting;
v12.3 was systematically buying strength and selling weakness.

Default is therefore mode=reversion_only.

Caveats on that result:
  - corrected for overlapping windows, no full-sample IC reached |t| > 1.1.
    The sign consistency is the evidence, not the magnitude.
  - the HIGH VOLATILITY trend IC of -0.397 is NOT an edge. 186 bars with
    6-bar overlapping returns is ~31 independent observations, clustered
    into a couple of episodes, and it was the most extreme of 6 cells
    inspected. Do not build on it.
  - the regime cells were not significant (|t| < 0.7), so mode=auto gates
    on noise. It is kept for comparison only.

THEN
----
1. Open /v13/edge-report and read the fwd_6bar row.
     below -0.02  -> component is backwards, flip its sign
     above +0.03  -> real, build around it
     all inside +/-0.02 -> stop tuning; price indicators on 15m have no edge
2. Compare directions:
     /v13/backtest?mode=reversion_only     <- expected best
     /v13/backtest?mode=trend_only         <- v12.3's direction
   Read edge_vs_random_percentage_points, not return_percent.
3. Optimize locally (uvicorn main:app --reload), read only the validation block
4. Promote nothing unless validation is PASS with >=30 trades and
   overfit_degradation_r < 0.10

IMPORTANT
---------
This backtests NIFTY spot while the product signals options. Theta decay and
bid-ask on a ~15 rupee premium will consume much of any spot edge this proves.
A PASS here is necessary, not sufficient. Paper-trade before risking money.

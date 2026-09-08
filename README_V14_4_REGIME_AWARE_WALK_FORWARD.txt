NIFTY AI v14.4 — Regime-Aware Rolling Walk-Forward Validation

Rule under test
---------------
TRENDING -> REVERSION
RANGE -> WAIT
HIGH_VOLATILITY -> WAIT

Why
---
v14.3 repeatedly discovered TRENDING -> REVERSION as the strongest candidate
across thresholds 0.15 / 0.20 / 0.25.

v14.4 tests whether that discovered relationship survives unseen data.

Method
------
Expanding-window rolling walk-forward.

Each fold:
1. Uses only past candles as training data.
2. Selects threshold from 0.15 / 0.20 / 0.25 / 0.30.
3. Tests the chosen threshold on the immediately following unseen block.
4. Reports H1 / H3 / H6 / H12 directional performance.

Main gate
---------
H6 is the primary validation horizon.

Promotion requires:
- overall PASS
- >= 3 PASS folds
- average unseen H6 accuracy >= 53%
- average unseen H6 move > 1.5 bps
- >= 80 total unseen validation signals
- average training-to-validation accuracy degradation <= 5 points
- no more than one FAIL fold

New endpoint
------------
GET /v14/regime-aware-walk-forward

New dashboard button
--------------------
Backtest -> Regime-Aware Walk-Forward v14.4

Important
---------
This version does NOT change the live router.
It is a validation gate only.

Persistent-login fix and all v14.3 diagnostics remain included.

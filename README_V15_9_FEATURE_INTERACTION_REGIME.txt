NIFTY AI v15.9 — Feature Interaction & Regime Discovery

Purpose
- Test whether the weak-but-positive v15.8 feature edge becomes more repeatable when independent feature pairs agree.
- Evaluate pair behavior inside frozen volatility/trend regime contexts.
- Preserve chronological train -> later validation discipline.

Rules
- H6 NIFTY forward direction remains the research label.
- Feature thresholds, polarity, pair ranking, and regime cutoffs are learned from train data only.
- Validation data never chooses thresholds or pair polarity.
- Live CE/PE prediction and routing remain unchanged.

Promotion gate
- At least 3/4 positive folds.
- Weighted accuracy >= 55%.
- Positive average bps.
- Worst fold accuracy >= 50%.

Use
Backtest -> Feature Interaction & Regime v15.9

If the gate passes, the next version should be a paper-only shadow candidate. If it fails, do not add fitted filters to the live engine.

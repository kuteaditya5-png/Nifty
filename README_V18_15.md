# Next-candle export audit

The old export exposed candle shapes without a matching prediction and outcome.
Version 18.15 adds exact-timestamp matching to the next completed five-minute
candle, independent of whether the live trading engine returned WAIT.

## Data and model separation

- The first 35 candle columns are retained; 52 additional audit columns include
  indicators, OR/rolling-breakout evidence, prediction, live call, next OHLC,
  close-to-close move, excursions, timing, quality and model/source identifiers.
- Existing shadow conditions supply four UP and four DOWN evidence tests.
  The signed audit base is `(up_score - down_score) / 4`. The existing breakout
  function can add at most 0.05 in the confirmed breakout direction. Direction
  is UP above +0.125, DOWN below -0.125, otherwise NEUTRAL. Strength is the
  absolute score times 100. This is a new audit convention, not a probability.
- `Breakout Adjustment` is audit strength percentage-point change. The live
  model's signed score adjustment is separately labelled. Never mix the units.
- EMA20/50, RSI14, MACD(12,26,9) and ATR14 accompany the assessment. The shadow
  model uses EMA9/21/50 internally; EMA20 is context, not a claim about its gates.
- Indicators require 50 prior candles. Seven calendar days are requested before
  the chosen day (bounded by provider history). Recent flagged bars or a gap in
  the current session prevent an audit direction until valid context exists.
- No volume provider, live BUY/WAIT threshold or clean OR chart logic changed.

## Storage and matching

`nifty_candle_audit_v1815` stores the first server-generated full snapshot per
candle. INSERT ON CONFLICT DO NOTHING prevents retrospective replacement.
Storage errors appear as `audit_storage_status` in the prediction response and
in the workbook's storage note; they do not break the live prediction response.
The UI defaults to auto matching; live and replay export modes are selectable.
Historical data is fetched at export time; saved reference close differences
above 0.01 are flagged as revised data and excluded from accuracy.

The audit source key is the candle START timestamp, not a browser five-minute
observation bucket. Only the exact next bar, in the same session, is attached.
Raw next OHLC remains visible even when ineligible. Invalid next candles have
no direction/excursion assessment. Neutral movement is inclusive +/-2 points.

Strict full-candle LIVE accuracy requires capture no later than the next candle
start. Normal API/scheduled calls have positive delay and are labelled LATE
CAPTURE, with outcomes shown but correctness excluded. No scheduling precision
is promised. A future post-capture return metric would need an observed price
at capture and is not invented in this release.

## Interpretation

`Next Candle Prediction` is the OHLC audit direction. `Trade Call` is the live
CE/PE alert, with NOT RECORDED for absent alerts. `Shadow Trade Call` is research
output and never replaces a missing live call. `Live Market Prediction` is the
original broader market prediction, whose horizon is not relabelled as five
minutes. Missing historical news/options prevent a faithful replay of that
broader live model; only the OHLC audit is replayed.

Compare LIVE and REPLAY separately. Split later sessions from sessions used to
tune thresholds; one-day or in-sample correctness is not future accuracy or
option profitability. The app does not auto-adjust its trading model from Excel.

## Checks

Run `python -m pytest -q tests/test_v1814.py tests/test_v1815.py` and
`node tests/chart_v1814.test.cjs` after installing requirements plus pytest/httpx.
Tests cover prefix invariance under future mutations, warm-up, missing bars,
overnight boundaries, neutral outcomes, late/revised/invalid exclusions, first
capture immutability, protected export endpoints, mode validation, complete
workbook responses and preservation of original export fields.

Follow START_HERE_V18_15.txt for installation. The package is not deployed by
downloading it; live database/collector operation still needs environment checks.

# NIFTY AI v18.17.1 — FVG patch for v18.16

Extract this patch into the existing NIFTY AI v18.16 app folder, replacing main.py and candle_audit_v1815.py, and restart/redeploy the app. Back up the existing files first. No new dependencies, environment variables or database migration are needed. This patch is not for the separate StockLens project.

## What is included
- Bullish/bearish FVG detection on completed 5-minute candles only.
- Inverse FVG tracking after a close crosses the far edge. A second adverse close invalidates the inverse zone.
- Dedicated FVG card, with lower/upper/50% chart lines for the selected zone. Existing breakout entry/stop/target lines remain.
- Twelve appended Excel columns: source, type, status, lower/upper/midpoint, size, formation candle start, original gap fill %, retest signal, active count, quality.
- New live snapshots capture FVG evidence; historical exports reconstruct it as REPLAY. LIVE-only mode leaves absent historical FVG evidence MISSING.

## Exact research rules
Three consecutive bars within the same session; bullish = candle 3 low > candle 1 high; bearish = candle 3 high < candle 1 low. Minimum gap is 1 spot point. Middle candle must have at least 50% body/range, matching direction, and close beyond candle 1's boundary. These are initial research parameters, not optimized thresholds.
Detection occurs only at candle 3 close. No retest or fill is attributed to the formation candle. Later wicks determine partial/full filling. A close through the far edge takes precedence and inverts the zone. On an inverse zone, fill % still refers to the original gap (100%); it is not an inverse-retouch percentage.
Retest signal = a later candle overlaps the zone, closes outside on the supportive side, and its body agrees with the zone direction. First qualifying rejection per original/inverse phase only. The inversion candle cannot confirm its own retest. Previously filled original zones cannot issue a later original retest signal, but can subsequently invert.
Zones reset at each session. Missing bars or invalid price data retire existing zones to DATA_REVIEW; no three-bar formation may bridge a missing/invalid candle. No volume required.
The card selects a current retest zone first, otherwise the nearest active midpoint; if none remain, it displays the latest retired zone for context without lines. Historical/stale data is labelled. These are horizontal reference lines, not time-bounded shaded boxes.

## Calls and confidence (18.17.1)
Confirmed current-candle FVG/IFVG retests now affect the live combined score before confidence labels, directional percentages, CE/PE WATCH checks and alert-strength calculations.
- Supporting retest: up to 0.05 additional signed score, only if the existing score agrees by at least 0.08. Positive breakout and FVG boosts share a 0.05 budget.
- Opposing retest: strength falls by up to 0.05 without flipping direction; the opposing WATCH/BUY alert is set to WAIT.
- Conflicting bullish/bearish retests: both sides blocked and strength reduced.
- Fresh zone without retest, stale/missing evidence: no FVG score change or block.
- Retests do not bypass option pricing, option-chain, coverage, freshness or other existing gates. No standalone FVG trade or broker order.
- Confidence remains heuristic. This is not a calibrated win probability and no improvement in accuracy/profit has been demonstrated.
The market card shows the FVG score adjustment. Four additional LIVE export columns record FVG score adjustment, final score, blocked sides and reason (16 total added FVG columns). Historical calls are not fabricated: old snapshots leave these LIVE fields blank. The separate next-candle research model remains version 18.15; its replay confidence is not the new live CE/PE confidence.

## Installation
This ZIP supersedes the original v18.17 patch and works over v18.16 or v18.17. Back up your app, extract into its root folder and restart/redeploy. No database migration or new dependencies. It has not been applied to your hosted website by this patch download.

## Validation
44 Python tests and all three chart JavaScript checks passed; changed Python files compile. Tests cover both directions, capped boosts, opposing/conflicting signals, stale data, no direction flip, and retention of WAIT where existing gates fail. Browser appearance and deployed live market operation have not been verified.

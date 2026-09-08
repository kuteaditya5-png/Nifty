NIFTY AI v14.3 — Regime × Engine Matrix

Purpose
-------
Identify exactly which prediction engine works in which market regime
before changing the live CE / PE / WAIT router.

New endpoint
------------
GET /v14/regime-engine-matrix

New dashboard action
--------------------
Backtest -> Regime × Engine Matrix v14.3

Matrix tested
-------------
TREND engine × TRENDING
TREND engine × RANGE
TREND engine × HIGH_VOLATILITY

REVERSION engine × TRENDING
REVERSION engine × RANGE
REVERSION engine × HIGH_VOLATILITY

BLENDED engine × TRENDING
BLENDED engine × RANGE
BLENDED engine × HIGH_VOLATILITY

For each cell
-------------
- signal count
- H1 / H3 / H6 / H12 directional accuracy
- average directional move in bps
- median directional move
- evidence score
- PROMISING / WEAK POSITIVE / NO EDGE / INSUFFICIENT verdict

Output also includes
--------------------
- best engine per regime
- suggested routing map
- ranked combinations
- usable combinations

Important
---------
The suggested routing map is diagnostic only.
Do NOT promote a combination to live logic until it also passes rolling
unseen validation.

Existing v14.2 persistent-login fix remains included.

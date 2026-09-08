NIFTY AI v14.7 — Historical Backfill

Goal
----
Populate the persistent PostgreSQL candle store with older 15-minute
NIFTY 50 history now, instead of waiting months for the database to grow.

New Backtest controls
---------------------
- CSV file picker
- Import 15m CSV Backfill v14.7

New endpoint
------------
POST /v14/history/backfill-csv

Accepted CSV
------------
Timeframe: 15 minutes only

Required columns:
datetime, open, high, low, close

Optional:
volume

Common aliases are also accepted:
timestamp / candle_time / date
o / h / l / c
vol / v

The import:
- validates OHLC
- checks that median intraday spacing looks like 15 minutes
- normalizes timestamps
- UPSERTS into nifty_candle_history
- never deletes older stored data
- reports total stored rows and date span

Included template:
NIFTY_15m_Backfill_Template.csv

Recommended backfill
--------------------
Use at least 6-12 months of NIFTY 50 INDEX 15-minute OHLC data.
More history is better if sourced consistently.

Do not mix:
- NIFTY futures prices
- option premiums
- 5-minute candles
- 30-minute candles
- daily candles

After import
------------
1. History Store Status
2. Extended Historical Validation v14.5
3. Regime × Engine Matrix v14.3
4. Regime-Aware Walk-Forward v14.4

Important
---------
This version does not change live CE / PE / WAIT routing.
It expands the evidence base used by our validation tools.

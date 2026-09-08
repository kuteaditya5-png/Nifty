NIFTY AI v14.6 — Historical Data Store

Goal
----
Break the repeated ~60-day intraday backtest limitation.

How it works
------------
The application now has a persistent PostgreSQL table:

nifty_candle_history

Each sync:
1. Downloads the current available 60-day NIFTY intraday window.
2. UPSERTS those candles into PostgreSQL.
3. NEVER deletes older candles during a normal sync.

Therefore the research dataset grows over time instead of always rolling
back to only the provider's latest 60 days.

New Backtest actions
--------------------
- Sync Historical Store v14.6
- History Store Status

New endpoints
-------------
GET /v14/history/sync
GET /v14/history/status

v14.5 Extended Historical Validation now uses PostgreSQL first.
It refreshes the latest window, then loads the full accumulated store.

First deployment
----------------
1. Deploy v14.6.
2. Open Backtest.
3. Click Sync Historical Store v14.6.
4. Click History Store Status.
5. Run Extended Historical Validation v14.5 again.

Initially the store will still contain only the currently obtainable
provider history. As future 15-minute candles arrive and syncs are run,
older rows remain and the dataset grows beyond that rolling window.

Requirements
------------
DATABASE_URL must remain configured.

Important
---------
This version does not change the live CE / PE / WAIT router.
It improves the quality and size of the validation dataset.

The historical store is per PostgreSQL database, not per logged-in user,
because market candles are common research data shared by all users.

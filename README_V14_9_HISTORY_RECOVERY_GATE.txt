NIFTY AI v14.9 — Historical Data Recovery + Backtest Readiness Gate

Goal
----
Stop long-horizon validation from running on incomplete history.

New Backtest actions
--------------------
- Historical Data Recovery v14.9
- Backtest Readiness Gate

Recovery does
-------------
1. Re-fetch current 60d 15m NIFTY history.
2. Re-fetch current 30d history as a second pass.
3. UPSERT both into PostgreSQL.
4. Keep all older stored candles.
5. Recalculate quality, missing weekday sessions and intraday slot gaps.
6. Report what is still missing.

Readiness gate
--------------
Serious validation is blocked until:

- quality verdict = PASS
- coverage >= 95%
- actual trading sessions >= 100

The following endpoints are now gated:
- Extended Historical Validation
- Regime-Aware Walk-Forward

If history is not ready, the endpoint returns a clear readiness-gate error
instead of producing a misleading backtest result.

Important
---------
API recovery can only refill history that the upstream provider still exposes.
Older gaps must still be filled with the CSV backfill importer.

Live CE / PE / WAIT prediction logic is unchanged.

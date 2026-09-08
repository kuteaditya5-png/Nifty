NIFTY AI v14.8 — Historical Data Quality & Gap Detector

Goal
----
Prevent incomplete historical coverage from being mistaken for a large,
high-quality backtest sample.

New Backtest action
-------------------
Data Quality & Gap Check v14.8

New endpoint
------------
GET /v14/history/quality

Checks
------
- total stored candles
- actual trading sessions
- calendar span
- expected 15-minute candles per NSE session
- overall coverage %
- full / partial / severe-gap days
- duplicate timestamps
- invalid OHLC
- abnormal candle ranges
- median intraday interval
- large calendar gaps between stored sessions
- worst-coverage dates

Verdict
-------
PASS
CAUTION
FAIL

BACKTEST READY = YES only when:
- quality verdict is PASS
- coverage >= 95%
- >= 100 trading sessions

Important
---------
A database that spans many calendar months can still contain very few real
trading sessions. v14.8 makes that visible before we trust walk-forward or
portfolio results.

This version does not change live CE / PE / WAIT routing.

NIFTY AI v15.0.2 — Historical Store VARCHAR Fix

Fix:
- Historical-store source identifier changed to a short fixed value:
  v15_dataset
- Prevents PostgreSQL: value too long for type character varying(40).
- Original uploaded filename is still returned in the Dataset Builder result/UI.
- v15.0.1 Volume/fillna fix remains included.
- Existing OHLC validation, 15-minute validation, IST normalization,
  duplicate handling, and historical-store upsert logic remain unchanged.

Retest:
1. Deploy v15.0.2.
2. Open Backtest.
3. Select the same NIFTY_15m_Backfill_Template.csv.
4. Click Build / Merge Dataset v15.0.2.
5. Confirm the varchar(40) error is gone.
6. Check Dataset Builder Status.

import os
from datetime import datetime

def setup_v1525(app):
    """v15.25 real-history backfill readiness + frozen revalidation workflow."""
    from main import _v146_load_raw_history

    TARGET_ROWS=12261

    def snapshot():
        raw=_v146_load_raw_history("15m",limit=50000)
        rows=0 if raw is None else len(raw)
        start=end=None
        if raw is not None and rows:
            try:
                start=str(raw.index.min()); end=str(raw.index.max())
            except Exception: pass
        return rows,start,end

    @app.get("/api/history/nifty/backfill-readiness")
    def nifty_backfill_readiness_v1525():
        rows,start,end=snapshot()
        return {
            "status":"success","version":"15.25",
            "mode":"Real NIFTY Historical Backfill + Frozen Revalidation",
            "current":{"rows_15m":rows,"start":start,"end":end},
            "target":{"rows_15m":TARGET_ROWS,"remaining_rows":max(0,TARGET_ROWS-rows)},
            "ready_for_frozen_revalidation":rows>=TARGET_ROWS,
            "data_policy":"REAL_PROVIDER_DATA_ONLY",
            "synthetic_backfill":False,
            "frozen_rule_changed":False,
            "next_action":("Run /api/regime/frozen-validation." if rows>=TARGET_ROWS else
                "Backfill older real NIFTY 15-minute candles through the production provider/storage path, then rerun this readiness endpoint."),
            "live_routing_changed":False
        }

    @app.get("/api/history/nifty/backfill-plan")
    def nifty_backfill_plan_v1525():
        rows,start,end=snapshot()
        return {
            "status":"success","version":"15.25",
            "current_rows":rows,"current_start":start,"current_end":end,
            "target_rows":TARGET_ROWS,
            "required_additional_rows":max(0,TARGET_ROWS-rows),
            "requirements":[
                "Use only real provider NIFTY 15-minute OHLC candles.",
                "Persist using the application's existing historical storage path.",
                "Deduplicate by candle timestamp/instrument.",
                "Preserve chronological timestamps and timezone handling.",
                "Do not synthesize or interpolate missing candles.",
                "Do not change the frozen TREND_LOW_VOL rule or validation gates."
            ],
            "revalidation_endpoint":"/api/regime/frozen-validation",
            "live_routing_changed":False
        }

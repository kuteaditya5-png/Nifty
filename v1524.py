import inspect

def setup_v1524(app):
    """v15.24: historical NIFTY expansion diagnostics + unchanged v15.23 frozen revalidation."""
    from main import _v146_load_raw_history

    @app.get("/api/regime/expand-nifty-history")
    def expand_nifty_history_v1524():
        # Do not fabricate provider history. Inspect the actual history currently available
        # through the production loader and report whether it is large enough for revalidation.
        try:
            raw=_v146_load_raw_history("15m",limit=50000)
            rows=0 if raw is None else len(raw)
            start=end=None
            if raw is not None and rows:
                try:
                    idx=raw.index
                    start=str(idx.min()); end=str(idx.max())
                except Exception: pass
            target_multiplier=2.3
            target_rows=int(max(rows,round(rows*target_multiplier)))
            return {
                "status":"success","version":"15.24",
                "purpose":"Assess available NIFTY 15-minute history before rerunning the frozen TREND_LOW_VOL hypothesis.",
                "available_15m_rows":rows,
                "available_start":start,"available_end":end,
                "estimated_target_rows_for_200_signals":target_rows,
                "target_basis":"v15.23 produced 86 independent signals; approximately 2.3x comparable history may be needed for 200 signals.",
                "provider_expansion_performed":False,
                "note":"This endpoint does not invent/backfill candles. If the existing loader/provider already exposes more history after deployment, the frozen validator will use it automatically.",
                "next_action":"Run /api/regime/frozen-validation. If independent signals remain below 200, a provider-supported older NIFTY 15m acquisition path is required before promotion can be reconsidered.",
                "live_routing_changed":False
            }
        except Exception as e:
            return {"status":"error","version":"15.24","message":str(e),"live_routing_changed":False}

    @app.get("/api/regime/v1524-status")
    def status_v1524():
        return {
          "status":"success","version":"15.24",
          "mode":"NIFTY Historical Expansion + Frozen TREND_LOW_VOL Revalidation",
          "frozen_rule_changed":False,
          "frozen_validator":"/api/regime/frozen-validation",
          "history_check":"/api/regime/expand-nifty-history",
          "required_gates":["independent_signals>=200","positive_folds>=3/4","accuracy>=55%","worst_fold>=50%","net_after_3bps>0","p<0.05"],
          "live_routing_changed":False
        }

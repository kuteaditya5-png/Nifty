def setup_v1521(app):
    """v15.21: expand confirmed monthly futures history, then rerun the frozen v15.20 hypothesis."""
    from main import v15172_futures_monthly_discovery
    # Reuse the already-registered v15.20 implementation through its source logic.
    from v1520 import setup_v1520

    @app.get("/api/futures/expand-history")
    def expand_history_v1521(max_contracts:int=18, scan_limit:int=240):
        r=v15172_futures_monthly_discovery(max_contracts=max_contracts,scan_limit=scan_limit)
        return {
            "status":(r or {}).get("status","error"),
            "version":"15.21",
            "purpose":"Expand confirmed monthly NIFTY futures history without changing the frozen signal hypothesis.",
            "requested_max_contracts":max_contracts,
            "requested_scan_limit":scan_limit,
            "acquisition":r,
            "next_action":"After successful expansion, run /api/futures/frozen-validation. The v15.20 hypothesis and gates remain unchanged.",
            "live_routing_changed":False
        }

    @app.get("/api/futures/v1521-status")
    def status_v1521():
        return {
            "status":"success","version":"15.21",
            "mode":"Historical Futures Expansion + Frozen Revalidation",
            "frozen_hypothesis":{
                "feature":"oi_chg1_pct","direction":"REVERSED",
                "session":"OPEN (<11:00 IST)","horizon_bars":8,
                "threshold":"30th percentile of absolute OI change learned from training data only"
            },
            "promotion_gates":{
                "independent_signals":">=200","positive_folds":">=3 of 4",
                "weighted_accuracy_percent":">=55","worst_fold_accuracy_percent":">=50",
                "net_edge_after_3bps":">0","p_value":"<0.05"
            },
            "steps":["Run /api/futures/expand-history","Then run /api/futures/frozen-validation"],
            "live_routing_changed":False
        }

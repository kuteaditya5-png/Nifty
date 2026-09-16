def setup_v1518(app):
    """v15.18 futures research decision layer. Does not modify live CE/PE/WAIT routing."""
    from main import v15172_futures_monthly_discovery, v1517_futures_research_validation

    @app.get("/api/futures/acquire")
    def futures_acquire_v1518(max_contracts: int = 6, scan_limit: int = 102):
        return v15172_futures_monthly_discovery(max_contracts=max_contracts, scan_limit=scan_limit)

    @app.get("/api/futures/validate")
    def futures_validate_v1518(blocks: int = 4, cost_bps: float = 3.0):
        return v1517_futures_research_validation(blocks=blocks, cost_bps=cost_bps)

    @app.get("/api/futures/decision")
    def futures_decision_v1518(blocks: int = 4, cost_bps: float = 3.0):
        result = v1517_futures_research_validation(blocks=blocks, cost_bps=cost_bps)
        if not isinstance(result, dict) or result.get("status") != "success":
            return {
                "status": "error",
                "version": "15.18",
                "message": (result or {}).get("message", "Futures validation failed."),
                "validation": result,
                "live_routing_changed": False
            }

        gates = result.get("gate_checks") or {}
        folds = result.get("folds") or []
        passed = bool(gates) and all(bool(v) for v in gates.values())

        weak_folds = []
        for f in folds:
            accuracy = float(f.get("accuracy_percent") or 0.0)
            net_bps = float(f.get("net_avg_bps") or 0.0)
            if accuracy < 50.0 or net_bps <= 0.0:
                weak_folds.append({
                    "fold": f.get("fold"),
                    "accuracy_percent": f.get("accuracy_percent"),
                    "net_avg_bps": f.get("net_avg_bps"),
                    "signals": f.get("signals"),
                    "selected_features": f.get("selected_features") or []
                })

        if passed:
            verdict = "SHADOW ENSEMBLE CANDIDATE"
            next_action = (
                "Independent futures research passed the configured gate. "
                "Keep live CE/PE/WAIT unchanged and evaluate futures in shadow/paper mode first."
            )
        else:
            verdict = "FUTURES EDGE NOT PROMOTED"
            next_action = (
                "Keep live CE/PE/WAIT unchanged. Review failing gates and weak folds; "
                "do not reduce the validation thresholds to force a pass."
            )

        return {
            "status": "success",
            "version": "15.18",
            "verdict": verdict,
            "summary": result.get("summary") or {},
            "failing_gates": [k for k, v in gates.items() if not bool(v)],
            "weak_folds": weak_folds,
            "selected_features": result.get("features_selected") or [],
            "next_action": next_action,
            "validation": result,
            "live_routing_changed": False
        }

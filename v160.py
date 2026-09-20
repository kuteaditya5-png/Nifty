from datetime import datetime, timezone
import traceback

VERSION="16.0"

ARCHIVED={"OPTION_OI","FUTURES_OI_BASIS","TREND_LOW_VOL"}

def _utc_now():
    return datetime.now(timezone.utc).isoformat()

def _normalize_call(v):
    s=str(v or "").strip().upper()
    if s in ("CE","CALL","BUY CE","BUY_CALL"): return "CE"
    if s in ("PE","PUT","BUY PE","BUY_PUT"): return "PE"
    if s in ("WAIT","HOLD","NO TRADE","NO_TRADE","NEUTRAL"): return "WAIT"
    return s or "WAIT"

def setup_v160(app):
    @app.get("/api/v16/status")
    def status():
        return {"status":"success","version":VERSION,"stage":"UNIFIED_PRODUCTION_ENGINE",
          "mode":"BASELINE_PRESERVATION","archived_research_branches":sorted(ARCHIVED),
          "research_branches_promoted":0,
          "live_baseline":"existing CE/PE/WAIT engine",
          "live_routing_changed":False,
          "prediction_endpoint":"/api/v16/prediction",
          "policy_endpoint":"/api/v16/policy"}

    @app.get("/api/v16/policy")
    def policy():
        return {"status":"success","version":VERSION,
          "prediction_policy":{
            "baseline":"Existing production CE/PE/WAIT prediction remains authoritative.",
            "wait_behavior":"WAIT remains a valid output; v16 does not force CE or PE.",
            "archived_predictive_inputs":sorted(ARCHIVED),
            "archived_inputs_used_for_prediction":False,
            "research_promotion_rule":"A new predictive component must pass a separately frozen out-of-sample validation before promotion.",
            "engineering_safeguards":["decision timestamp","data availability transparency","single normalized CE/PE/WAIT output","no silent research promotion"]
          },"live_routing_changed":False}

    @app.get("/api/v16/prediction")
    def prediction():
      try:
        # Read the existing production endpoint/function without changing its routing.
        # FastAPI route inspection avoids duplicating or reimplementing the established signal logic.
        target=None
        for r in app.routes:
            if getattr(r,"path",None)=="/prediction" and "GET" in getattr(r,"methods",set()):
                target=getattr(r,"endpoint",None); break
        if target is None:
            return {"status":"error","version":VERSION,"stage":"BASELINE_LOOKUP",
                    "message":"Existing /prediction baseline route was not found.",
                    "live_routing_changed":False}
        raw=target()
        if hasattr(raw,"body"):
            import json
            try: raw=json.loads(raw.body)
            except Exception: raw={"raw_response":str(raw)}
        if not isinstance(raw,dict):
            raw={"raw_response":raw}
        # Preserve the full baseline payload. We only derive a normalized decision for a unified contract.
        candidates=["prediction","call","signal","decision","recommendation","action","final_call","trade_call"]
        decision=None; source_field=None
        for k in candidates:
            if k in raw:
                decision=_normalize_call(raw.get(k)); source_field=k; break
        if decision is None:
            # Search one level of common nested payloads without inventing a signal.
            for parent in ("data","result","prediction_data"):
                obj=raw.get(parent)
                if isinstance(obj,dict):
                    for k in candidates:
                        if k in obj:
                            decision=_normalize_call(obj.get(k)); source_field=parent+"."+k; break
                if decision is not None: break
        return {"status":"success","version":VERSION,
          "decision":decision,
          "decision_source_field":source_field,
          "decision_timestamp_utc":_utc_now(),
          "baseline_payload":raw,
          "archived_research_used":False,
          "archived_research_branches":sorted(ARCHIVED),
          "note":"v16.0 wraps the existing production baseline; it does not manufacture a CE/PE decision when the baseline field cannot be identified.",
          "live_routing_changed":False}
      except Exception as e:
        return {"status":"error","version":VERSION,"stage":"UNIFIED_PREDICTION",
          "error_type":type(e).__name__,"message":str(e),
          "trace_tail":traceback.format_exc().splitlines()[-8:],
          "live_routing_changed":False}

from datetime import datetime, timezone
import math
VERSION="17.0"

# v17.0 is an architecture/safety layer. It does NOT silently replace the v16.1
# baseline prediction. New predictive factors require separate validation.
def _f(v, default=None):
    try:
        x=float(v)
        return x if math.isfinite(x) else default
    except Exception:return default

def _regime(raw):
    s=raw.get("signals") or {}
    pa=s.get("price_action") or {}
    mr=s.get("market_regime") or {}
    adx=_f(pa.get("adx_14"))
    label=str(mr.get("regime") or (raw.get("prediction_architecture") or {}).get("market_regime") or "UNKNOWN")
    return {"label":label,"adx_14":adx,"source":"existing point-in-time baseline"}

def _health(raw):
    coverage=_f(raw.get("data_coverage_percent"),0.0)
    sig=raw.get("signal_generated_at")
    reasons=[]
    if coverage < 70: reasons.append("DATA_COVERAGE_BELOW_70")
    if not sig: reasons.append("SIGNAL_TIMESTAMP_MISSING")
    s=raw.get("signals") or {}
    pa=s.get("price_action") or {}
    if not pa.get("last_completed_candle"): reasons.append("COMPLETED_CANDLE_TIMESTAMP_MISSING")
    return {"pass":not reasons,"coverage_percent":coverage,"blocking_reasons":reasons}

def _context(raw):
    s=raw.get("signals") or {}
    return {
      "vix":s.get("vix"),
      "cross_asset":s.get("cross_asset"),
      "option_chain":s.get("option_chain"),
      "time_event_context":s.get("time_event_context"),
      "volatility_spread":s.get("volatility_spread")
    }

def setup_v170(app):
    def baseline():
        for r in app.routes:
            if getattr(r,"path",None)=="/prediction" and "GET" in getattr(r,"methods",set()):
                x=r.endpoint()
                if hasattr(x,"body"):
                    import json
                    try:x=json.loads(x.body)
                    except Exception:x={}
                return x if isinstance(x,dict) else {}
        raise RuntimeError("Baseline /prediction route not found")

    @app.get("/api/v17/status")
    def status():
        return {"status":"success","version":VERSION,"stage":"ACCURACY_ARCHITECTURE",
          "basis":"v17 Accuracy Upgrade blueprint",
          "mode":"CHALLENGER_SHADOW","baseline":"v16.1 existing CE/PE/WAIT",
          "production_model_replaced":False,"live_routing_changed":False,
          "implemented_now":["data-health gate","point-in-time/closed-candle audit surface",
            "regime visibility","feature-hygiene policy","calibration/expectancy schema",
            "champion-vs-challenger policy"],
          "research_only_until_validated":["learned weights","adaptive regime thresholds",
            "gamma exposure","ATM-weighted OI","IV rank","straddle implied move"],
          "next":"/api/v17/decision-audit"}

    @app.get("/api/v17/decision-audit")
    def audit():
        try:
            raw=baseline(); health=_health(raw); s=raw.get("signals") or {}
            trade=str(raw.get("fno_setup") or "WAIT").upper()
            market=str(raw.get("prediction") or "UNKNOWN")
            score=_f(raw.get("combined_score"))
            # No invented calibrated probability/EV: explicitly unavailable until trained.
            return {"status":"success","version":VERSION,
              "captured_at_utc":datetime.now(timezone.utc).isoformat(),
              "champion":{"model_version":raw.get("model_version"),"market_prediction":market,
                "trade_decision":trade,"combined_score":score,"confidence_label":raw.get("confidence")},
              "data_health":health,"regime":_regime(raw),"point_in_time":{
                "signal_generated_at":raw.get("signal_generated_at"),
                "last_completed_candle":(s.get("price_action") or {}).get("last_completed_candle"),
                "closed_candle_policy":"REQUIRED"},
              "context":_context(raw),
              "feature_hygiene":{"policy":"COUNT_EACH_INFORMATION_SOURCE_ONCE",
                "normalization":"REQUIRED_FOR_CHALLENGER_TRAINING",
                "correlation_pruning":"REQUIRED_BEFORE_PROMOTION",
                "ablation_testing":"REQUIRED_BEFORE_PROMOTION"},
              "calibration":{"calibrated_win_probability":None,"brier_score":None,
                "status":"PENDING_FORWARD/TRAINING_EVIDENCE"},
              "expectancy":{"ev_after_costs":None,"status":"PENDING_CALIBRATED_PROBABILITY_AND_VALIDATED_PAYOFF_MODEL"},
              "challenger":{"status":"NOT_TRAINED_OR_PROMOTED",
                "promotion_rule":"Must beat champion on frozen walk-forward + untouched holdout + forward paper evidence."},
              "effective_trade_decision":trade if health["pass"] else "WAIT",
              "health_gate_overrode_signal":bool(not health["pass"] and trade!="WAIT"),
              "production_model_replaced":False,"live_routing_changed":False}
        except Exception as e:
            return {"status":"error","version":VERSION,"message":str(e),"live_routing_changed":False}

    @app.get("/api/v17/upgrade-plan")
    def plan():
        return {"status":"success","version":VERSION,"phases":[
          {"phase":1,"name":"DATA_AND_HYGIENE","state":"IMPLEMENTED_POLICY","items":["point-in-time inputs","closed candles","data health","no double counting","normalization","correlation pruning"]},
          {"phase":2,"name":"REGIME_AND_OPTIONS","state":"SHADOW_RESEARCH","items":["trend/range","volatility regime","opening gap/session","ATM-weighted OI","IV rank/skew","implied move","expiry mode"]},
          {"phase":3,"name":"MODEL_AND_CALIBRATION","state":"REQUIRES_TRAINING","items":["learned weights","calibrated probabilities","per-regime thresholds","clear horizon target","ensemble agreement"]},
          {"phase":4,"name":"TRADE_OUTPUT","state":"PARTIAL","items":["dynamic SL/targets already available in paper option selection","EV after costs pending calibration","position sizing pending risk settings","liquidity/spread gate pending reliable feed"]},
          {"phase":5,"name":"VALIDATION","state":"ACTIVE","items":["walk-forward","untouched holdout","paper trading","drift monitor","champion vs challenger"]}
        ],"principle":"No new predictive factor is promoted merely because it appears in the blueprint.","live_routing_changed":False}

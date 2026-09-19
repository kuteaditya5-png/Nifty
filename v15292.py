import math, traceback
import numpy as np
import pandas as pd
from v1528 import load_pg_history_v1528

VERSION="15.29.2"
TARGET=12261
H=6
COST_BPS=3.0

def _base_raw():
    from main import _v146_load_raw_history
    x=_v146_load_raw_history("15m",limit=50000)
    if x is None:return pd.DataFrame()
    x=x.copy()
    x.index=pd.to_datetime(x.index,utc=True,errors="coerce")
    return x[~x.index.isna()].sort_index()

def _merged_raw():
    base=_base_raw()
    pg=load_pg_history_v1528()
    if pg is None: pg=pd.DataFrame()
    if len(pg):
        pg=pg.copy()
        pg.index=pd.to_datetime(pg.index,utc=True,errors="coerce")
        pg=pg[~pg.index.isna()].sort_index()
    x=pd.concat([pg,base]).sort_index() if len(pg) or len(base) else pd.DataFrame()
    if len(x): x=x[~x.index.duplicated(keep="last")]
    return base,pg,x

def _ohlc_cols(x):
    cols={str(c).lower():c for c in x.columns}
    need=[]
    for k in ("open","high","low","close"):
        if k not in cols: raise ValueError("Missing OHLC column: "+k)
        need.append(cols[k])
    return need

def _feature_frame(raw):
    # Directly calculate the frozen v15.23 inputs on the MERGED raw frame.
    # This deliberately bypasses _v146_feature_frame_from_raw so it cannot
    # silently fall back to / truncate the old production-only history.
    o,h,l,c=_ohlc_cols(raw)
    x=raw.copy().sort_index()
    O=pd.to_numeric(x[o],errors="coerce"); Hh=pd.to_numeric(x[h],errors="coerce")
    L=pd.to_numeric(x[l],errors="coerce"); C=pd.to_numeric(x[c],errors="coerce")
    x["close_frozen"]=C
    x["ema20_frozen"]=C.ewm(span=20,adjust=False).mean()
    x["ema50_frozen"]=C.ewm(span=50,adjust=False).mean()
    x["trend_strength_frozen"]=((x["ema20_frozen"]-x["ema50_frozen"])/C).abs()*100.0
    ret=C.pct_change(fill_method=None)
    x["rv20_frozen"]=ret.rolling(20).std()*math.sqrt(20)*100.0
    prev=C.shift(1)
    tr=pd.concat([(Hh-L).abs(),(Hh-prev).abs(),(L-prev).abs()],axis=1).max(axis=1)
    x["atr14_pct_frozen"]=tr.rolling(14).mean()/C*100.0
    x["direction_frozen"]=np.sign(x["ema20_frozen"]-x["ema50_frozen"])
    x["fwd_bps_frozen"]=(C.shift(-H)/C-1.0)*10000.0
    return x.replace([np.inf,-np.inf],np.nan).dropna(
        subset=["trend_strength_frozen","rv20_frozen","atr14_pct_frozen","direction_frozen","fwd_bps_frozen"]
    )

def _pvalue(acc,n):
    if n<=0:return 1.0
    z=abs((acc-.5)/math.sqrt(.25/n))
    return math.erfc(z/math.sqrt(2))

def _round(v,n=4):
    try:
        v=float(v)
        return round(v,n) if math.isfinite(v) else None
    except:return None

def setup_v15292(app):
    @app.get("/api/regime/v15292-status")
    def status():
        try:
            base,pg,merged=_merged_raw()
            return {"status":"success","version":VERSION,
                "production_rows":len(base),"postgres_rows":len(pg),"merged_unique_rows":len(merged),
                "merged_start":str(merged.index.min()) if len(merged) else None,
                "merged_end":str(merged.index.max()) if len(merged) else None,
                "target_rows":TARGET,"ready":len(merged)>=TARGET,
                "validator":"/api/regime/frozen-validation-v15292",
                "direct_merged_feature_calculation":True,
                "frozen_rule_changed":False,"live_routing_changed":False}
        except Exception as e:
            return {"status":"error","version":VERSION,"stage":"STATUS",
                "error_type":type(e).__name__,"message":str(e),"live_routing_changed":False}

    @app.get("/api/regime/frozen-validation-v15292")
    def validate(blocks:int=4):
        try:
            base,pg,merged=_merged_raw()
            if len(merged)<TARGET:
                return {"status":"error","version":VERSION,"stage":"HISTORY_GATE",
                    "message":"Merged history is below frozen-validation target.",
                    "production_rows":len(base),"postgres_rows":len(pg),"merged_unique_rows":len(merged),
                    "target_rows":TARGET,"frozen_rule_changed":False,"live_routing_changed":False}
            feat=_feature_frame(merged)
            # Hard guard against the v15.29.1 failure mode.
            min_expected_feature_rows=int(len(merged)*0.90)
            if len(feat)<min_expected_feature_rows:
                return {"status":"error","version":VERSION,"stage":"FEATURE_COVERAGE_GATE",
                    "message":"Feature frame does not represent the expanded merged history; verdict intentionally blocked.",
                    "merged_unique_rows":len(merged),"feature_rows":len(feat),
                    "minimum_expected_feature_rows":min_expected_feature_rows,
                    "frozen_rule_changed":False,"live_routing_changed":False}
            n=len(feat); initial=max(500,int(n*.45)); remain=n-initial
            step=max(1,remain//blocks)
            folds=[]; all_events=[]
            for i in range(blocks):
                train_end=initial+i*step
                test_end=n if i==blocks-1 else min(n,train_end+step)
                train=feat.iloc[:train_end]; test=feat.iloc[train_end:test_end].copy()
                tc=float(train["trend_strength_frozen"].quantile(.60))
                rc=float(train["rv20_frozen"].quantile(.60))
                ac=float(train["atr14_pct_frozen"].quantile(.60))
                eligible=test[(test["trend_strength_frozen"]>=tc)&
                              (test["rv20_frozen"]<rc)&
                              (test["atr14_pct_frozen"]<ac)].copy()
                ev=eligible.iloc[::H].copy()
                if len(ev):
                    gross=ev["direction_frozen"]*ev["fwd_bps_frozen"]
                    acc=float((gross>0).mean()); net=gross-COST_BPS
                    fold={"fold":i+1,"signals":len(ev),"accuracy_percent":_round(acc*100,1),
                          "gross_avg_bps":_round(gross.mean(),2),"net_avg_bps":_round(net.mean(),2),
                          "p_value":_round(_pvalue(acc,len(ev)),4)}
                    all_events.append(ev)
                else:
                    fold={"fold":i+1,"signals":0,"accuracy_percent":None,"gross_avg_bps":None,
                          "net_avg_bps":None,"p_value":None}
                fold.update({"train_rows":len(train),"test_rows":len(test),"eligible_rows":len(eligible),
                    "training_only_cutoffs":{"trend_strength_cut":_round(tc,6),
                    "rv20_cut":_round(rc,6),"atr14_pct_cut":_round(ac,6)}})
                folds.append(fold)
            if not all_events:
                return {"status":"error","version":VERSION,"stage":"SIGNAL_GATE",
                        "message":"No frozen signals generated.","folds":folds,
                        "frozen_rule_changed":False,"live_routing_changed":False}
            ev=pd.concat(all_events).sort_index()
            gross=ev["direction_frozen"]*ev["fwd_bps_frozen"]; net=gross-COST_BPS
            acc=float((gross>0).mean()); N=len(ev)
            pos=sum(1 for f in folds if f["net_avg_bps"] is not None and f["net_avg_bps"]>0)
            worst=min([f["accuracy_percent"] for f in folds if f["accuracy_percent"] is not None],default=None)
            summary={"independent_signals":N,"weighted_accuracy_percent":_round(acc*100,1),
                     "gross_avg_bps":_round(gross.mean(),2),"net_avg_bps":_round(net.mean(),2),
                     "p_value":_round(_pvalue(acc,N),4),"positive_folds":pos,
                     "folds":len(folds),"worst_fold_accuracy_percent":worst}
            gates={"independent_signals_200":N>=200,
                   "positive_folds_3of4":len(folds)>=4 and pos>=3,
                   "accuracy_55":summary["weighted_accuracy_percent"]>=55.0,
                   "worst_fold_50":worst is not None and worst>=50.0,
                   "net_edge_after_cost":summary["net_avg_bps"]>0,
                   "significant_p05":summary["p_value"]<.05}
            passed=all(gates.values())
            return {"status":"success","version":VERSION,
                "data_lineage":{"production_rows":len(base),"postgres_rows":len(pg),
                    "merged_unique_rows":len(merged),"feature_rows":len(feat),
                    "feature_coverage_percent":_round(len(feat)/len(merged)*100,2),
                    "validation_consumed_expanded_history":True},
                "hypothesis":{"regime":"TREND_LOW_VOL","direction":"EMA20 vs EMA50",
                    "horizon_bars":H,"timeframe":"15m","cost_bps":COST_BPS,
                    "regime_cutoffs":"60th percentiles learned from training history only",
                    "signal_independence":"every 6th eligible observation"},
                "verdict":"FROZEN TREND_LOW_VOL HYPOTHESIS PASSES" if passed else "FROZEN TREND_LOW_VOL HYPOTHESIS REJECTED",
                "summary":summary,"folds":folds,"gate_checks":gates,
                "integration_fix_only":True,"frozen_rule_changed":False,
                "next_action":"Proceed to final validation without tuning." if passed else "Archive this frozen hypothesis; do not tune it to force a pass.",
                "live_routing_changed":False}
        except Exception as e:
            return {"status":"error","version":VERSION,"stage":"RUNTIME",
                "error_type":type(e).__name__,"message":str(e),
                "trace_tail":traceback.format_exc().splitlines()[-8:],
                "integration_fix_only":True,"frozen_rule_changed":False,"live_routing_changed":False}

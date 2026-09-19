import math, traceback
import numpy as np
import pandas as pd
from v1528 import load_pg_history_v1528

VERSION="15.29.4"; TARGET=12261; H=6; COST_BPS=3.0

def _normalize(df):
    if df is None or not len(df): return pd.DataFrame(columns=["open","high","low","close","volume"])
    x=df.copy()
    x.index=pd.to_datetime(x.index,utc=True,errors="coerce")
    x=x[~x.index.isna()]
    # Canonicalize case BEFORE concatenation. This is the only lineage fix.
    cmap={}
    for c in x.columns:
        lc=str(c).lower()
        if lc in ("open","high","low","close","volume","oi"): cmap[c]=lc
    x=x.rename(columns=cmap)
    # Protect against duplicate columns after normalization.
    x=x.loc[:,~x.columns.duplicated(keep="last")]
    for c in ("open","high","low","close","volume"):
        if c not in x.columns: x[c]=np.nan
        x[c]=pd.to_numeric(x[c],errors="coerce")
    if "oi" in x.columns:x["oi"]=pd.to_numeric(x["oi"],errors="coerce")
    return x.sort_index()

def _history():
    from main import _v146_load_raw_history
    prod=_normalize(_v146_load_raw_history("15m",limit=50000))
    pg=_normalize(load_pg_history_v1528())
    merged=pd.concat([pg,prod],sort=False).sort_index()
    merged=merged[~merged.index.duplicated(keep="last")]
    return prod,pg,merged

def _features(x):
    C=x["close"]; Hh=x["high"]; L=x["low"]
    y=x.copy()
    y["ema20"]=C.ewm(span=20,adjust=False).mean()
    y["ema50"]=C.ewm(span=50,adjust=False).mean()
    y["trend_strength"]=((y["ema20"]-y["ema50"])/C).abs()*100
    ret=C.pct_change(fill_method=None)
    y["rv20"]=ret.rolling(20).std()*math.sqrt(20)*100
    prev=C.shift(1)
    tr=pd.concat([(Hh-L).abs(),(Hh-prev).abs(),(L-prev).abs()],axis=1).max(axis=1)
    y["atr14_pct"]=tr.rolling(14).mean()/C*100
    y["direction"]=np.sign(y["ema20"]-y["ema50"])
    y["fwd_bps"]=(C.shift(-H)/C-1)*10000
    return y.replace([np.inf,-np.inf],np.nan).dropna(subset=["trend_strength","rv20","atr14_pct","direction","fwd_bps"])

def _p(acc,n):
    if n<=0:return 1.0
    z=abs((acc-.5)/math.sqrt(.25/n))
    return math.erfc(z/math.sqrt(2))
def _r(v,n=4):
    try:
        v=float(v); return round(v,n) if math.isfinite(v) else None
    except:return None

def setup_v15294(app):
    @app.get("/api/regime/v15294-status")
    def status():
      try:
        prod,pg,m=_history(); f=_features(m)
        valid=int(m[["open","high","low","close"]].notna().all(axis=1).sum())
        return {"status":"success","version":VERSION,"production_rows":len(prod),"postgres_rows":len(pg),
          "merged_unique_rows":len(m),"merged_valid_ohlc_rows":valid,"feature_rows":len(f),
          "feature_coverage_percent":_r(len(f)/len(m)*100,2) if len(m) else 0,
          "target_rows":TARGET,"ready":len(m)>=TARGET and len(f)>=int(len(m)*.90),
          "validator":"/api/regime/frozen-validation-v15294",
          "ohlc_schema_normalized":True,"frozen_rule_changed":False,"live_routing_changed":False}
      except Exception as e:
        return {"status":"error","version":VERSION,"stage":"STATUS","error_type":type(e).__name__,"message":str(e)}

    @app.get("/api/regime/frozen-validation-v15294")
    def validate(blocks:int=4):
      try:
        prod,pg,m=_history(); f=_features(m)
        minfeat=int(len(m)*.90)
        if len(m)<TARGET or len(f)<minfeat:
            return {"status":"error","version":VERSION,"stage":"COVERAGE_GATE",
              "production_rows":len(prod),"postgres_rows":len(pg),"merged_unique_rows":len(m),
              "feature_rows":len(f),"minimum_expected_feature_rows":minfeat,
              "message":"Expanded-history coverage gate failed; verdict blocked.",
              "frozen_rule_changed":False,"live_routing_changed":False}
        n=len(f); initial=max(500,int(n*.45)); step=max(1,(n-initial)//blocks)
        folds=[]; evs=[]
        for i in range(blocks):
            a=initial+i*step; b=n if i==blocks-1 else min(n,a+step)
            tr=f.iloc[:a]; te=f.iloc[a:b].copy()
            tc=float(tr["trend_strength"].quantile(.60)); rc=float(tr["rv20"].quantile(.60)); ac=float(tr["atr14_pct"].quantile(.60))
            eligible=te[(te["trend_strength"]>=tc)&(te["rv20"]<rc)&(te["atr14_pct"]<ac)].copy()
            ev=eligible.iloc[::H].copy()
            if len(ev):
                gross=ev["direction"]*ev["fwd_bps"]; acc=float((gross>0).mean()); net=gross-COST_BPS
                q={"fold":i+1,"signals":len(ev),"accuracy_percent":_r(acc*100,1),
                   "gross_avg_bps":_r(gross.mean(),2),"net_avg_bps":_r(net.mean(),2),"p_value":_r(_p(acc,len(ev)),4)}
                evs.append(ev)
            else:q={"fold":i+1,"signals":0,"accuracy_percent":None,"gross_avg_bps":None,"net_avg_bps":None,"p_value":None}
            q.update({"train_rows":len(tr),"test_rows":len(te),"eligible_rows":len(eligible),
              "training_only_cutoffs":{"trend_strength_cut":_r(tc,6),"rv20_cut":_r(rc,6),"atr14_pct_cut":_r(ac,6)}})
            folds.append(q)
        if not evs:return {"status":"error","version":VERSION,"stage":"SIGNALS","message":"No signals generated."}
        ev=pd.concat(evs).sort_index(); gross=ev["direction"]*ev["fwd_bps"]; acc=float((gross>0).mean()); net=gross-COST_BPS; N=len(ev)
        pos=sum(1 for q in folds if q["net_avg_bps"] is not None and q["net_avg_bps"]>0)
        worst=min([q["accuracy_percent"] for q in folds if q["accuracy_percent"] is not None],default=None)
        s={"independent_signals":N,"weighted_accuracy_percent":_r(acc*100,1),"gross_avg_bps":_r(gross.mean(),2),
           "net_avg_bps":_r(net.mean(),2),"p_value":_r(_p(acc,N),4),"positive_folds":pos,"folds":len(folds),"worst_fold_accuracy_percent":worst}
        g={"independent_signals_200":N>=200,"positive_folds_3of4":len(folds)>=4 and pos>=3,
           "accuracy_55":s["weighted_accuracy_percent"]>=55,"worst_fold_50":worst is not None and worst>=50,
           "net_edge_after_cost":s["net_avg_bps"]>0,"significant_p05":s["p_value"]<.05}
        passed=all(g.values())
        return {"status":"success","version":VERSION,
          "data_lineage":{"production_rows":len(prod),"postgres_rows":len(pg),"merged_unique_rows":len(m),
            "merged_valid_ohlc_rows":int(m[["open","high","low","close"]].notna().all(axis=1).sum()),
            "feature_rows":len(f),"feature_coverage_percent":_r(len(f)/len(m)*100,2),
            "validation_consumed_expanded_history":True,"ohlc_schema_normalized":True},
          "hypothesis":{"regime":"TREND_LOW_VOL","direction":"EMA20 vs EMA50","horizon_bars":H,"timeframe":"15m",
            "cost_bps":COST_BPS,"regime_cutoffs":"60th percentiles learned from training history only",
            "signal_independence":"every 6th eligible observation"},
          "verdict":"FROZEN TREND_LOW_VOL HYPOTHESIS PASSES" if passed else "FROZEN TREND_LOW_VOL HYPOTHESIS REJECTED",
          "summary":s,"folds":folds,"gate_checks":g,"schema_fix_only":True,"frozen_rule_changed":False,
          "next_action":"Proceed to final validation without tuning." if passed else "Archive this frozen hypothesis; do not tune it to force a pass.",
          "live_routing_changed":False}
      except Exception as e:
        return {"status":"error","version":VERSION,"stage":"RUNTIME","error_type":type(e).__name__,"message":str(e),
          "trace_tail":traceback.format_exc().splitlines()[-10:],"schema_fix_only":True,
          "frozen_rule_changed":False,"live_routing_changed":False}

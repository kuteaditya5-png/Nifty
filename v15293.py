import traceback
import pandas as pd
import numpy as np
from v15292 import _base_raw, _merged_raw, _feature_frame

VERSION="15.29.3"

def _profile(name,df):
    r={"name":name,"rows":int(len(df)),"columns":[str(c) for c in df.columns]}
    if len(df):
        r["start"]=str(df.index.min()); r["end"]=str(df.index.max())
        r["duplicate_timestamps"]=int(df.index.duplicated().sum())
    cols={str(c).lower():c for c in df.columns}
    oh={}
    for k in ("open","high","low","close","volume","oi"):
        if k in cols:
            s=df[cols[k]]
            num=pd.to_numeric(s,errors="coerce")
            oh[k]={"source_column":str(cols[k]),"non_null":int(s.notna().sum()),
                   "numeric":int(num.notna().sum()),"numeric_null":int(num.isna().sum()),
                   "zero":int((num==0).sum())}
    r["field_quality"]=oh
    return r

def _survival(df):
    if df is None or not len(df):return {"input_rows":0}
    x=df.copy().sort_index()
    cols={str(c).lower():c for c in x.columns}
    missing=[k for k in ("open","high","low","close") if k not in cols]
    if missing:return {"input_rows":len(x),"missing_ohlc":missing}
    O=pd.to_numeric(x[cols["open"]],errors="coerce")
    H=pd.to_numeric(x[cols["high"]],errors="coerce")
    L=pd.to_numeric(x[cols["low"]],errors="coerce")
    C=pd.to_numeric(x[cols["close"]],errors="coerce")
    out={"input_rows":len(x),
         "ohlc_all_numeric":int(pd.concat([O,H,L,C],axis=1).notna().all(axis=1).sum()),
         "close_numeric":int(C.notna().sum())}
    ema20=C.ewm(span=20,adjust=False).mean(); ema50=C.ewm(span=50,adjust=False).mean()
    trend=((ema20-ema50)/C).abs()*100
    ret=C.pct_change(fill_method=None)
    rv=ret.rolling(20).std()*np.sqrt(20)*100
    prev=C.shift(1)
    tr=pd.concat([(H-L).abs(),(H-prev).abs(),(L-prev).abs()],axis=1).max(axis=1)
    atr=tr.rolling(14).mean()/C*100
    fwd=(C.shift(-6)/C-1)*10000
    q=pd.DataFrame({"trend":trend,"rv":rv,"atr":atr,"fwd":fwd})
    out.update({
      "trend_non_null":int(q["trend"].notna().sum()),
      "rv20_non_null":int(q["rv"].notna().sum()),
      "atr14_non_null":int(q["atr"].notna().sum()),
      "fwd_h6_non_null":int(q["fwd"].notna().sum()),
      "all_frozen_features_non_null":int(q.notna().all(axis=1).sum())
    })
    # Show contiguous valid-close runs; a schema/NaN boundary will be obvious.
    valid=C.notna()
    grp=(valid!=valid.shift()).cumsum()
    runs=[]
    for _,idx in x.groupby(grp).groups.items():
        ids=list(idx); flag=bool(valid.loc[ids[0]])
        runs.append({"valid_close":flag,"rows":len(ids),"start":str(ids[0]),"end":str(ids[-1])})
    out["close_validity_runs"]=runs[:20]
    return out

def setup_v15293(app):
    @app.get("/api/regime/feature-diagnostic-v15293")
    def diagnostic():
      try:
        base,pg,merged=_merged_raw()
        feat=_feature_frame(merged)
        overlap=0
        if len(base) and len(pg): overlap=len(base.index.intersection(pg.index))
        return {"status":"success","version":VERSION,
          "purpose":"Diagnose merged-history feature loss only; no model decision is produced.",
          "production":_profile("production",base),
          "postgres":_profile("postgres",pg),
          "merged":_profile("merged",merged),
          "timestamp_overlap_rows":int(overlap),
          "survival":{"production":_survival(base),"postgres":_survival(pg),"merged":_survival(merged)},
          "current_feature_frame_rows":int(len(feat)),
          "expected_near_merged_rows":int(len(merged)),
          "rows_lost_before_final_feature_frame":int(len(merged)-len(feat)),
          "frozen_rule_changed":False,"live_routing_changed":False}
      except Exception as e:
        return {"status":"error","version":VERSION,"stage":"DIAGNOSTIC",
          "error_type":type(e).__name__,"message":str(e),
          "trace_tail":traceback.format_exc().splitlines()[-10:],
          "frozen_rule_changed":False,"live_routing_changed":False}

    @app.get("/api/regime/v15293-status")
    def status():
        return {"status":"success","version":VERSION,
          "diagnostic":"/api/regime/feature-diagnostic-v15293",
          "model_validation_enabled":False,
          "reason":"Diagnostic build only. Fix data lineage before rerunning frozen validation.",
          "frozen_rule_changed":False,"live_routing_changed":False}

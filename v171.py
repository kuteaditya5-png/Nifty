
from datetime import datetime, timezone
import os, math
VERSION="17.1"
FEATURES=["ret1","ret3","ema_gap","rsi14","rv20","atr14_pct","z20","tod_sin","tod_cos"]

def _db():
    import psycopg
    url=os.getenv("DATABASE_URL")
    if not url: raise RuntimeError("DATABASE_URL is not configured")
    return psycopg.connect(url,sslmode="require")

def _load_history():
    import pandas as pd
    # Durable historical backfill
    with _db() as c:
        pg=pd.read_sql_query("""SELECT candle_ts AS ts,open,high,low,close,volume
          FROM nifty_15m_history_v1528 ORDER BY candle_ts""",c)
    pg["ts"]=pd.to_datetime(pg["ts"],utc=True,errors="coerce")
    pg=pg.set_index("ts")
    # Existing production history; normalize schema before merge.
    try:
        from main import _v146_load_raw_history
        prod=_v146_load_raw_history("15m",limit=50000).copy()
        prod.index=pd.to_datetime(prod.index,utc=True,errors="coerce")
        prod.columns=[str(x).lower() for x in prod.columns]
        keep=[x for x in ["open","high","low","close","volume"] if x in prod.columns]
        prod=prod[keep]
    except Exception:
        prod=pd.DataFrame()
    for df in (pg,prod):
        for c in ["open","high","low","close","volume"]:
            if c not in df.columns: df[c]=float("nan")
            df[c]=pd.to_numeric(df[c],errors="coerce")
    merged=pd.concat([pg[["open","high","low","close","volume"]],prod[["open","high","low","close","volume"]]])
    merged=merged[~merged.index.duplicated(keep="last")].sort_index()
    return merged.dropna(subset=["open","high","low","close"])

def _features(raw,h=6):
    import numpy as np, pandas as pd
    x=raw.copy()
    c=x["close"]; hi=x["high"]; lo=x["low"]
    x["ret1"]=c.pct_change()
    x["ret3"]=c.pct_change(3)
    e20=c.ewm(span=20,adjust=False).mean(); e50=c.ewm(span=50,adjust=False).mean()
    x["ema_gap"]=(e20-e50)/c
    d=c.diff(); up=d.clip(lower=0).rolling(14).mean(); dn=(-d.clip(upper=0)).rolling(14).mean()
    rs=up/dn.replace(0,np.nan); x["rsi14"]=100-(100/(1+rs))
    x["rv20"]=x["ret1"].rolling(20).std()*np.sqrt(20)
    pc=c.shift(1); tr=pd.concat([(hi-lo).abs(),(hi-pc).abs(),(lo-pc).abs()],axis=1).max(axis=1)
    x["atr14_pct"]=tr.rolling(14).mean()/c
    mu=c.rolling(20).mean(); sd=c.rolling(20).std(); x["z20"]=(c-mu)/sd.replace(0,np.nan)
    mins=x.index.hour*60+x.index.minute
    x["tod_sin"]=np.sin(2*np.pi*mins/(24*60)); x["tod_cos"]=np.cos(2*np.pi*mins/(24*60))
    x["future_bps"]=(c.shift(-h)/c-1)*10000
    x["y"]=(x["future_bps"]>0).astype(int)
    return x.dropna(subset=FEATURES+["future_bps"])

def _sigmoid(z):
    import numpy as np
    return 1/(1+np.exp(-np.clip(z,-35,35)))

def _fit_logit(X,y,steps=450,lr=.08,l2=.03):
    import numpy as np
    w=np.zeros(X.shape[1]); b=0.
    for _ in range(steps):
        p=_sigmoid(X@w+b); err=p-y
        w-=lr*((X.T@err)/len(y)+l2*w); b-=lr*err.mean()
    return w,b

def _brier(y,p):
    import numpy as np
    return float(np.mean((p-y)**2))

def _metrics(y,p,ret_bps,cost_bps=3.0,threshold=.60):
    import numpy as np
    long=p>=threshold; short=p<=1-threshold; active=long|short
    pred=np.where(long,1,np.where(short,0,-1))
    n=int(active.sum())
    if not n:return {"signals":0}
    yy=y[active]; pp=pred[active]
    acc=float((yy==pp).mean())
    signed=np.where(pp==1,ret_bps[active],-ret_bps[active])
    return {"signals":n,"accuracy_percent":round(acc*100,2),
      "gross_avg_bps":round(float(signed.mean()),3),
      "net_avg_bps":round(float((signed-cost_bps).mean()),3)}

def _train_validate():
    import numpy as np, pandas as pd
    raw=_load_history(); f=_features(raw,6)
    n=len(f)
    if n<8000: raise RuntimeError(f"Insufficient feature rows: {n}")
    # Chronological split: first 70% development, final 30% untouched holdout.
    cut=int(n*.70); dev=f.iloc[:cut].copy(); hold=f.iloc[cut:].copy()
    # Correlation pruning learned on development only.
    corr=dev[FEATURES].corr().abs(); keep=[]; dropped=[]
    for col in FEATURES:
        if any(corr.loc[col,k]>.92 for k in keep): dropped.append(col)
        else: keep.append(col)
    # 4 expanding chronological walk-forward blocks inside development.
    start=max(1800,int(len(dev)*.45)); remain=len(dev)-start; block=max(1,remain//4)
    folds=[]; allp=[]; ally=[]; allr=[]
    for i in range(4):
        a=start+i*block; b=len(dev) if i==3 else min(len(dev),a+block)
        tr=dev.iloc[:a]; te=dev.iloc[a:b]
        mu=tr[keep].mean(); sd=tr[keep].std().replace(0,1)
        Xtr=((tr[keep]-mu)/sd).clip(-6,6).to_numpy(float)
        Xte=((te[keep]-mu)/sd).clip(-6,6).to_numpy(float)
        ytr=tr["y"].to_numpy(float); yte=te["y"].to_numpy(int)
        w,bias=_fit_logit(Xtr,ytr); p=_sigmoid(Xte@w+bias)
        met=_metrics(yte,p,te["future_bps"].to_numpy(float))
        met.update({"fold":i+1,"train_rows":len(tr),"test_rows":len(te),"brier":round(_brier(yte,p),5)})
        folds.append(met); allp.extend(p.tolist()); ally.extend(yte.tolist()); allr.extend(te["future_bps"].tolist())
    wf=_metrics(np.array(ally),np.array(allp),np.array(allr)); wf["brier"]=round(_brier(np.array(ally),np.array(allp)),5)
    # Freeze model using development only; untouched holdout evaluated once by endpoint call.
    mu=dev[keep].mean(); sd=dev[keep].std().replace(0,1)
    X=((dev[keep]-mu)/sd).clip(-6,6).to_numpy(float); y=dev["y"].to_numpy(float)
    w,bias=_fit_logit(X,y)
    Xh=((hold[keep]-mu)/sd).clip(-6,6).to_numpy(float); ph=_sigmoid(Xh@w+bias); yh=hold["y"].to_numpy(int)
    hm=_metrics(yh,ph,hold["future_bps"].to_numpy(float)); hm["brier"]=round(_brier(yh,ph),5)
    # Strict predeclared challenger gate. This is deliberately not tuned after seeing result.
    pos=sum(1 for x in folds if x.get("net_avg_bps",-999)>0)
    gates={
      "walk_forward_signals_200":wf.get("signals",0)>=200,
      "walk_forward_accuracy_55":wf.get("accuracy_percent",0)>=55,
      "walk_forward_net_positive":wf.get("net_avg_bps",-999)>0,
      "positive_net_folds_3of4":pos>=3,
      "holdout_signals_100":hm.get("signals",0)>=100,
      "holdout_accuracy_55":hm.get("accuracy_percent",0)>=55,
      "holdout_net_positive":hm.get("net_avg_bps",-999)>0,
      "holdout_brier_below_025":hm.get("brier",1)<.25}
    passed=all(gates.values())
    return {"raw_rows":len(raw),"feature_rows":n,"features_considered":FEATURES,
      "features_retained":keep,"correlation_pruned":dropped,
      "target":"NIFTY direction 6 x 15m bars ahead","horizon_bars":6,"cost_bps":3.0,
      "signal_probability_threshold":0.60,"development_rows":len(dev),"untouched_holdout_rows":len(hold),
      "walk_forward":{"summary":wf,"folds":folds,"positive_net_folds":pos},
      "untouched_holdout":hm,"gate_checks":gates,
      "verdict":"CHALLENGER PASSES VALIDATION" if passed else "CHALLENGER NOT PROMOTED",
      "production_model_replaced":False,"live_routing_changed":False}

def setup_v171(app):
    @app.get("/api/v17/challenger/status")
    def status():
        try:
            raw=_load_history()
            return {"status":"success","version":VERSION,"stage":"CHALLENGER_TRAINING_VALIDATION",
              "historical_rows":len(raw),"minimum_rows":8000,"ready":len(raw)>=8000,
              "target":"6-bar / 90-minute NIFTY direction","candidate_features":FEATURES,
              "validation":"chronological walk-forward + untouched 30% holdout",
              "cost_bps":3.0,"probability_threshold":0.60,
              "champion":"v16.1 baseline remains active","live_routing_changed":False}
        except Exception as e:
            return {"status":"error","version":VERSION,"stage":"STATUS","message":str(e),"live_routing_changed":False}

    @app.get("/api/v17/challenger/validate")
    def validate():
        try:
            x=_train_validate()
            return {"status":"success","version":VERSION,**x}
        except Exception as e:
            return {"status":"error","version":VERSION,"stage":"VALIDATION","message":str(e),
              "production_model_replaced":False,"live_routing_changed":False}

    @app.get("/api/v17/challenger/policy")
    def policy():
        return {"status":"success","version":VERSION,
          "leakage_controls":["chronological splits only","normalization learned from training only",
            "correlation pruning learned from development only","untouched final 30% holdout",
            "closed 15m OHLC candles","fixed H=6 target"],
          "excluded_from_this_challenger":["historically sparse Option PCR/OI research",
            "rejected Futures OI/Basis hypothesis","rejected frozen TREND_LOW_VOL hypothesis",
            "GEX until reliable point-in-time history exists"],
          "promotion":"Only a full gate pass makes the challenger eligible for later forward paper comparison; this endpoint never changes production routing.",
          "live_routing_changed":False}

import math
import numpy as np
import pandas as pd

def setup_v1522(app):
    """v15.22 independent market-regime research. Live CE/PE/WAIT is untouched."""
    from main import _v146_load_raw_history, _v146_feature_frame_from_raw

    def safe(v,d=4):
        try:
            x=float(v); return round(x,d) if math.isfinite(x) else None
        except Exception: return None

    def prepare():
        raw=_v146_load_raw_history("15m",limit=50000)
        f=_v146_feature_frame_from_raw(raw)
        if f is None or len(f)<800: return None,"Insufficient 15-minute NIFTY history."
        x=f.copy().sort_index()
        if not isinstance(x.index,pd.DatetimeIndex): x.index=pd.to_datetime(x.index,utc=True,errors="coerce")
        close_col="close" if "close" in x.columns else ("Close" if "Close" in x.columns else None)
        high_col="high" if "high" in x.columns else ("High" if "High" in x.columns else None)
        low_col="low" if "low" in x.columns else ("Low" if "Low" in x.columns else None)
        if not all([close_col,high_col,low_col]): return None,"OHLC columns not found."
        c=pd.to_numeric(x[close_col],errors="coerce")
        h=pd.to_numeric(x[high_col],errors="coerce")
        l=pd.to_numeric(x[low_col],errors="coerce")
        ret=c.pct_change(fill_method=None)
        x["close_v1522"]=c
        x["ret1"]=ret
        x["ema20"]=c.ewm(span=20,adjust=False).mean()
        x["ema50"]=c.ewm(span=50,adjust=False).mean()
        x["trend_strength"]=((x["ema20"]-x["ema50"])/c).abs()*100
        tr=pd.concat([(h-l).abs(),(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
        x["atr14_pct"]=tr.rolling(14).mean()/c*100
        x["rv20"]=ret.rolling(20).std()*math.sqrt(20)*100
        x["ema_direction"]=np.sign(x["ema20"]-x["ema50"])
        return x.replace([np.inf,-np.inf],np.nan),None

    def classify(train,test):
        # All regime cutoffs are learned from past/training data only.
        trend_cut=float(train["trend_strength"].dropna().quantile(.60))
        vol_cut=float(train["rv20"].dropna().quantile(.60))
        atr_cut=float(train["atr14_pct"].dropna().quantile(.60))
        t=test.copy()
        high_vol=(t["rv20"]>=vol_cut)|(t["atr14_pct"]>=atr_cut)
        trending=t["trend_strength"]>=trend_cut
        t["regime"]=np.select(
            [trending&high_vol,trending&~high_vol,~trending&high_vol],
            ["TREND_HIGH_VOL","TREND_LOW_VOL","RANGE_HIGH_VOL"],
            default="RANGE_LOW_VOL")
        return t,{"trend_strength_cut":safe(trend_cut,6),"rv20_cut":safe(vol_cut,6),"atr14_pct_cut":safe(atr_cut,6)}

    @app.get("/api/regime/research")
    def market_regime_research_v1522(blocks:int=4,cost_bps:float=3.0,horizon_bars:int=6):
        df,err=prepare()
        if err:return {"status":"error","version":"15.22","message":err,"live_routing_changed":False}
        df=df.dropna(subset=["close_v1522","trend_strength","rv20","atr14_pct","ema_direction"]).copy()
        df["fwd_bps"]=(df["close_v1522"].shift(-horizon_bars)/df["close_v1522"]-1)*10000
        df=df.dropna(subset=["fwd_bps"])
        n=len(df); initial=max(500,int(n*.45)); step=max(1,(n-initial)//blocks)
        folds=[]; regime_rows=[]
        for i in range(blocks):
            te=initial+i*step; ee=n if i==blocks-1 else min(n,te+step)
            train=df.iloc[:te]; test=df.iloc[te:ee]
            if len(test)==0:continue
            tagged,cuts=classify(train,test)
            fold={"fold":i+1,"train_rows":len(train),"test_rows":len(test),"training_only_cutoffs":cuts,"regimes":[]}
            for rg,g in tagged.groupby("regime"):
                # Diagnostic only: EMA trend direction is a fixed baseline directional signal.
                gross=g["ema_direction"]*g["fwd_bps"]; net=gross-float(cost_bps); wins=(gross>0)
                row={"regime":rg,"bars":len(g),"accuracy_percent":safe(wins.mean()*100,1),
                     "gross_avg_bps":safe(gross.mean(),2),"net_avg_bps":safe(net.mean(),2)}
                fold["regimes"].append(row)
                regime_rows.append({"fold":i+1,**row})
            folds.append(fold)
        agg=[]
        for rg in ["TREND_HIGH_VOL","TREND_LOW_VOL","RANGE_HIGH_VOL","RANGE_LOW_VOL"]:
            rr=[r for r in regime_rows if r["regime"]==rg]
            if not rr:continue
            bars=sum(r["bars"] for r in rr)
            agg.append({"regime":rg,"bars":bars,
                "weighted_accuracy_percent":safe(sum(r["accuracy_percent"]*r["bars"] for r in rr)/bars,1),
                "weighted_net_avg_bps":safe(sum(r["net_avg_bps"]*r["bars"] for r in rr)/bars,2),
                "positive_folds":sum(1 for r in rr if (r["net_avg_bps"] or -999)>0),
                "folds_present":len(rr)})
        return {"status":"success","version":"15.22",
          "purpose":"Independent market-regime attribution. This does not alter or validate the live CE/PE/WAIT calls.",
          "method":{"timeframe":"15m","horizon_bars":horizon_bars,"cost_bps":cost_bps,
                    "regimes":["TREND_HIGH_VOL","TREND_LOW_VOL","RANGE_HIGH_VOL","RANGE_LOW_VOL"],
                    "regime_inputs":["EMA20-vs-EMA50 trend strength","20-bar realized volatility","ATR14 percent"],
                    "cutoffs":"60th-percentile cutoffs learned separately from each fold's training history only",
                    "diagnostic_direction":"EMA20 vs EMA50 direction"},
          "aggregate_regime_diagnostics":agg,"folds":folds,
          "next_action":"Use these diagnostics only to choose one regime hypothesis for a new frozen chronological validation. Do not alter live CE/PE/WAIT from this exploratory result.",
          "live_routing_changed":False}

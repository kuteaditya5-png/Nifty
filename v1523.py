import math
import numpy as np
import pandas as pd

def setup_v1523(app):
    """Frozen TREND_LOW_VOL validation. No regime/feature/horizon search."""
    from main import _v146_load_raw_history, _v146_feature_frame_from_raw

    def safe(v,d=4):
        try:
            x=float(v); return round(x,d) if math.isfinite(x) else None
        except Exception:return None

    def prepare():
        raw=_v146_load_raw_history("15m",limit=50000)
        f=_v146_feature_frame_from_raw(raw)
        if f is None or len(f)<800:return None,"Insufficient NIFTY 15-minute history."
        x=f.copy().sort_index()
        ccol="close" if "close" in x.columns else ("Close" if "Close" in x.columns else None)
        hcol="high" if "high" in x.columns else ("High" if "High" in x.columns else None)
        lcol="low" if "low" in x.columns else ("Low" if "Low" in x.columns else None)
        if not all([ccol,hcol,lcol]):return None,"OHLC columns not found."
        c=pd.to_numeric(x[ccol],errors="coerce"); h=pd.to_numeric(x[hcol],errors="coerce"); l=pd.to_numeric(x[lcol],errors="coerce")
        ret=c.pct_change(fill_method=None)
        x["close_v1523"]=c
        x["ema20_v1523"]=c.ewm(span=20,adjust=False).mean()
        x["ema50_v1523"]=c.ewm(span=50,adjust=False).mean()
        x["trend_strength_v1523"]=((x["ema20_v1523"]-x["ema50_v1523"])/c).abs()*100
        tr=pd.concat([(h-l).abs(),(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
        x["atr14_pct_v1523"]=tr.rolling(14).mean()/c*100
        x["rv20_v1523"]=ret.rolling(20).std()*math.sqrt(20)*100
        x["direction_v1523"]=np.sign(x["ema20_v1523"]-x["ema50_v1523"])
        x["fwd_bps_v1523"]=(c.shift(-6)/c-1)*10000
        return x.replace([np.inf,-np.inf],np.nan).dropna(subset=["trend_strength_v1523","atr14_pct_v1523","rv20_v1523","direction_v1523","fwd_bps_v1523"]),None

    @app.get("/api/regime/frozen-validation")
    def frozen_trend_low_vol_v1523(blocks:int=4,cost_bps:float=3.0):
        df,err=prepare()
        if err:return {"status":"error","version":"15.23","message":err,"live_routing_changed":False}
        n=len(df); initial=max(500,int(n*.45)); step=max(1,(n-initial)//blocks)
        folds=[]; oos=[]
        for i in range(blocks):
            te=initial+i*step; ee=n if i==blocks-1 else min(n,te+step)
            train=df.iloc[:te]; test=df.iloc[te:ee].copy()
            trend_cut=float(train["trend_strength_v1523"].quantile(.60))
            rv_cut=float(train["rv20_v1523"].quantile(.60))
            atr_cut=float(train["atr14_pct_v1523"].quantile(.60))
            # Frozen v15.22 TREND_LOW_VOL definition.
            mask=(test["trend_strength_v1523"]>=trend_cut)&(test["rv20_v1523"]<rv_cut)&(test["atr14_pct_v1523"]<atr_cut)
            z=test[mask].copy()
            # Non-overlap for H=6: preserve only every 6th eligible observation.
            if len(z): z=z.iloc[::6].copy()
            if len(z):
                z["signal"] = z["direction_v1523"]
                gross=z["signal"]*z["fwd_bps_v1523"]; net=gross-float(cost_bps); wins=(gross>0).astype(int)
                nn=len(z); acc=float(wins.mean()); zz=abs((acc-.5)/math.sqrt(.25/nn)); p=math.erfc(zz/math.sqrt(2))
                r={"fold":i+1,"signals":nn,"accuracy_percent":safe(acc*100,1),"gross_avg_bps":safe(gross.mean(),2),"net_avg_bps":safe(net.mean(),2),"p_value":safe(p,4)}
                oos.append(z)
            else:r={"fold":i+1,"signals":0,"accuracy_percent":None,"gross_avg_bps":None,"net_avg_bps":None,"p_value":None}
            r.update({"train_rows":len(train),"test_rows":len(test),"training_only_cutoffs":{"trend_strength_cut":safe(trend_cut,6),"rv20_cut":safe(rv_cut,6),"atr14_pct_cut":safe(atr_cut,6)}})
            folds.append(r)
        if not oos:return {"status":"error","version":"15.23","message":"No frozen TREND_LOW_VOL signals generated.","folds":folds,"live_routing_changed":False}
        z=pd.concat(oos).sort_index()
        gross=z["direction_v1523"]*z["fwd_bps_v1523"]; net=gross-float(cost_bps); wins=(gross>0).astype(int)
        N=len(z); acc=float(wins.mean()); zz=abs((acc-.5)/math.sqrt(.25/N)); p=math.erfc(zz/math.sqrt(2))
        positive=sum(1 for f in folds if f["net_avg_bps"] is not None and f["net_avg_bps"]>0)
        worst=min([f["accuracy_percent"] for f in folds if f["accuracy_percent"] is not None],default=None)
        summary={"independent_signals":N,"weighted_accuracy_percent":safe(acc*100,1),"gross_avg_bps":safe(gross.mean(),2),"net_avg_bps":safe(net.mean(),2),"p_value":safe(p,4),"positive_folds":positive,"folds":len(folds),"worst_fold_accuracy_percent":worst}
        gates={"independent_signals_200":N>=200,"positive_folds_3of4":len(folds)>=4 and positive>=3,"accuracy_55":summary["weighted_accuracy_percent"]>=55,"worst_fold_50":worst is not None and worst>=50,"net_edge_after_cost":summary["net_avg_bps"]>0,"significant_p05":summary["p_value"]<.05}
        passed=all(gates.values())
        return {"status":"success","version":"15.23","hypothesis":{"regime":"TREND_LOW_VOL","direction":"EMA20 vs EMA50","horizon_bars":6,"timeframe":"15m","cost_bps":cost_bps,"regime_cutoffs":"60th percentiles learned from training history only","signal_independence":"every 6th eligible observation"},"verdict":"FROZEN TREND_LOW_VOL HYPOTHESIS PASSES" if passed else "FROZEN TREND_LOW_VOL HYPOTHESIS REJECTED","summary":summary,"folds":folds,"gate_checks":gates,"next_action":"Eligible for shadow-only regime-filter research; keep live routing unchanged." if passed else "Reject this frozen regime hypothesis; do not tune it to force a pass. Keep live routing unchanged.","live_routing_changed":False}

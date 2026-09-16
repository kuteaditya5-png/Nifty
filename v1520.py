import math
import numpy as np
import pandas as pd

def setup_v1520(app):
    """Frozen v15.20 test: reversed OI change, OPEN session, H=8. No feature search."""
    from main import _v1517_load_futures, _v146_load_raw_history, _v146_feature_frame_from_raw

    def safe(v,d=4):
        try:
            x=float(v); return round(x,d) if math.isfinite(x) else None
        except Exception: return None

    def prepare():
        raw=_v146_load_raw_history("15m",limit=50000)
        spot=_v146_feature_frame_from_raw(raw)
        fut=_v1517_load_futures()
        if spot is None or len(spot)==0 or fut is None or len(fut)==0:
            return None,"Spot or futures history is empty."
        s=spot.copy()
        if not isinstance(s.index,pd.DatetimeIndex): s.index=pd.to_datetime(s.index,utc=True,errors="coerce")
        if s.index.tz is None: s.index=s.index.tz_localize("UTC")
        s.index=s.index.tz_convert("Asia/Kolkata")
        f=fut.copy()
        if "timestamp" in f.columns:
            f["timestamp"]=pd.to_datetime(f["timestamp"],utc=True,errors="coerce").dt.tz_convert("Asia/Kolkata")
            f=f.set_index("timestamp")
        if not isinstance(f.index,pd.DatetimeIndex): f.index=pd.to_datetime(f.index,utc=True,errors="coerce")
        if f.index.tz is None: f.index=f.index.tz_localize("UTC")
        f.index=f.index.tz_convert("Asia/Kolkata")
        j=s.join(f,how="inner",rsuffix="_fut")
        sc="close" if "close" in j.columns else "Close"
        fc="close_fut" if "close_fut" in j.columns else ("fut_close" if "fut_close" in j.columns else None)
        if fc is None:
            cs=[c for c in j.columns if "close" in str(c).lower() and c!=sc]
            fc=cs[0] if cs else None
        oi=next((c for c in ["oi","fut_oi","open_interest","oi_fut"] if c in j.columns),None)
        if fc is None or oi is None: return None,"Required futures close/OI column not found."
        j["spot_close"]=pd.to_numeric(j[sc],errors="coerce")
        j["fut_oi_v1520"]=pd.to_numeric(j[oi],errors="coerce")
        j["oi_chg1_pct_v1520"]=j["fut_oi_v1520"].pct_change(fill_method=None).replace([np.inf,-np.inf],np.nan)*100
        j["fwd_bps_v1520"]=(j["spot_close"].shift(-8)/j["spot_close"]-1)*10000
        # Freeze OPEN exactly as discovered in v15.19: before 11:00 IST.
        hour=j.index.hour+j.index.minute/60
        j=j[hour<11].copy()
        return j.replace([np.inf,-np.inf],np.nan),None

    def evaluate(x,threshold,cost):
        z=x.dropna(subset=["oi_chg1_pct_v1520","fwd_bps_v1520"]).copy()
        # Frozen direction: reversed OI change. Threshold magnitude is learned on training only.
        z=z[z["oi_chg1_pct_v1520"].abs()>=threshold]
        if len(z)==0: return {"signals":0}
        z["signal"]=-np.sign(z["oi_chg1_pct_v1520"])
        gross=z["signal"]*z["fwd_bps_v1520"]
        net=gross-cost
        wins=(gross>0).astype(int)
        # Approx two-sided binomial normal approximation, sufficient for reporting gate.
        n=len(wins); p=float(wins.mean())
        zz=abs((p-0.5)/math.sqrt(0.25/n)) if n else 0
        pval=math.erfc(zz/math.sqrt(2))
        return {"signals":int(n),"accuracy_percent":safe(p*100,1),"gross_avg_bps":safe(gross.mean(),2),"net_avg_bps":safe(net.mean(),2),"p_value":safe(pval,4)}

    @app.get("/api/futures/frozen-validation")
    def frozen_futures_validation_v1520(blocks:int=4,cost_bps:float=3.0):
        df,err=prepare()
        if err: return {"status":"error","version":"15.20","message":err,"live_routing_changed":False}
        df=df.dropna(subset=["oi_chg1_pct_v1520","fwd_bps_v1520"]).sort_index()
        n=len(df)
        if n<250:
            return {"status":"error","version":"15.20","message":f"Only {n} usable OPEN-session observations; frozen validation requires at least 250.","live_routing_changed":False}
        initial=max(100,int(n*0.40))
        remain=n-initial
        step=max(1,remain//blocks)
        folds=[]; all_test=[]
        for i in range(blocks):
            train_end=initial+i*step
            test_end=n if i==blocks-1 else min(n,train_end+step)
            train=df.iloc[:train_end]
            test=df.iloc[train_end:test_end]
            if len(test)==0: continue
            # v15.19 used top/bottom 30%; frozen equivalent is the training-only 30th percentile of |OI change|.
            threshold=float(train["oi_chg1_pct_v1520"].abs().quantile(0.30))
            r=evaluate(test,threshold,float(cost_bps))
            r.update({"fold":i+1,"train_rows":int(len(train)),"test_rows":int(len(test)),"training_only_abs_oi_threshold_pct":safe(threshold,6)})
            folds.append(r)
            if r["signals"]>0:
                tt=test.dropna(subset=["oi_chg1_pct_v1520","fwd_bps_v1520"]).copy()
                tt=tt[tt["oi_chg1_pct_v1520"].abs()>=threshold]
                tt["signal"]=-np.sign(tt["oi_chg1_pct_v1520"])
                all_test.append(tt)
        if not all_test:
            return {"status":"error","version":"15.20","message":"No out-of-sample signals generated.","folds":folds,"live_routing_changed":False}
        oos=pd.concat(all_test).sort_index()
        gross=oos["signal"]*oos["fwd_bps_v1520"]; net=gross-float(cost_bps); wins=(gross>0).astype(int)
        N=len(wins); acc=float(wins.mean())
        zz=abs((acc-0.5)/math.sqrt(0.25/N)) if N else 0
        pval=math.erfc(zz/math.sqrt(2))
        summary={"independent_signals":int(N),"weighted_accuracy_percent":safe(acc*100,1),"gross_avg_bps":safe(gross.mean(),2),"net_avg_bps":safe(net.mean(),2),"p_value":safe(pval,4),"positive_folds":sum(1 for f in folds if (f.get("net_avg_bps") or -999)>0),"folds":len(folds),"worst_fold_accuracy_percent":min([f.get("accuracy_percent") for f in folds if f.get("accuracy_percent") is not None],default=None)}
        gates={
          "independent_signals_200":N>=200,
          "positive_folds_3of4":len(folds)>=4 and summary["positive_folds"]>=3,
          "accuracy_55":summary["weighted_accuracy_percent"] is not None and summary["weighted_accuracy_percent"]>=55,
          "worst_fold_50":summary["worst_fold_accuracy_percent"] is not None and summary["worst_fold_accuracy_percent"]>=50,
          "net_edge_after_cost":summary["net_avg_bps"] is not None and summary["net_avg_bps"]>0,
          "significant_p05":summary["p_value"] is not None and summary["p_value"]<0.05
        }
        passed=all(gates.values())
        return {"status":"success","version":"15.20","hypothesis":{"feature":"oi_chg1_pct","direction":"REVERSED","session":"OPEN (<11:00 IST)","horizon_bars":8,"threshold":"30th percentile of absolute OI change, learned from training data only"},"verdict":"FROZEN FUTURES OI HYPOTHESIS PASSES" if passed else "FROZEN FUTURES OI HYPOTHESIS REJECTED","summary":summary,"folds":folds,"gate_checks":gates,"next_action":"Proceed to v15.21 shadow-only integration; do not alter live calls." if passed else "Stop promotion of this frozen futures/OI hypothesis. Keep live routing unchanged and move research to a different independent signal source.","live_routing_changed":False}

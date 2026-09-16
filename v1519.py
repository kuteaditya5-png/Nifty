import math
import numpy as np
import pandas as pd

def setup_v1519(app):
    """v15.19 futures failure attribution. Research-only; live CE/PE/WAIT is untouched."""
    from main import _v1517_load_futures, _v146_load_raw_history, _v146_feature_frame_from_raw

    def _safe(v, digits=4):
        try:
            x=float(v)
            return round(x,digits) if math.isfinite(x) else None
        except Exception:
            return None

    def _prepare():
        raw=_v146_load_raw_history("15m", limit=50000)
        spot=_v146_feature_frame_from_raw(raw)
        fut=_v1517_load_futures()
        if spot is None or len(spot)==0 or fut is None or len(fut)==0:
            return None, "Spot or futures history is empty."
        s=spot.copy()
        if not isinstance(s.index,pd.DatetimeIndex):
            s.index=pd.to_datetime(s.index,utc=True,errors="coerce")
        if s.index.tz is None: s.index=s.index.tz_localize("UTC")
        s.index=s.index.tz_convert("Asia/Kolkata")
        f=fut.copy()
        if "timestamp" in f.columns:
            f["timestamp"]=pd.to_datetime(f["timestamp"],utc=True,errors="coerce").dt.tz_convert("Asia/Kolkata")
            f=f.set_index("timestamp")
        if not isinstance(f.index,pd.DatetimeIndex):
            f.index=pd.to_datetime(f.index,utc=True,errors="coerce")
        if f.index.tz is None: f.index=f.index.tz_localize("UTC")
        f.index=f.index.tz_convert("Asia/Kolkata")
        j=s.join(f,how="inner",rsuffix="_fut")
        spot_close="close" if "close" in j.columns else "Close"
        fut_close="close_fut" if "close_fut" in j.columns else ("fut_close" if "fut_close" in j.columns else None)
        if fut_close is None:
            candidates=[c for c in j.columns if "close" in str(c).lower() and c!=spot_close]
            fut_close=candidates[0] if candidates else None
        if fut_close is None: return None, "Futures close column not found."
        oi=next((c for c in ["oi","fut_oi","open_interest","oi_fut"] if c in j.columns),None)
        vol=next((c for c in ["volume_fut","fut_volume","volume"] if c in j.columns),None)
        j["spot_close"]=pd.to_numeric(j[spot_close],errors="coerce")
        j["fut_close"]=pd.to_numeric(j[fut_close],errors="coerce")
        j["basis_pct"]=(j["fut_close"]-j["spot_close"])/j["spot_close"]*100.0
        j["basis_chg1"]=j["basis_pct"].diff()
        if oi:
            j["fut_oi"]=pd.to_numeric(j[oi],errors="coerce")
            j["oi_chg1_pct"]=j["fut_oi"].pct_change(fill_method=None).replace([np.inf,-np.inf],np.nan)*100.0
        else:
            j["fut_oi"]=np.nan; j["oi_chg1_pct"]=np.nan
        j["fut_ret1"]=j["fut_close"].pct_change(fill_method=None)*100.0
        j["price_oi_interaction"]=np.sign(j["fut_ret1"])*np.sign(j["oi_chg1_pct"])
        if vol:
            j["fut_volume"]=pd.to_numeric(j[vol],errors="coerce")
            j["vol_chg1_pct"]=j["fut_volume"].pct_change(fill_method=None).replace([np.inf,-np.inf],np.nan)*100.0
        else: j["vol_chg1_pct"]=np.nan
        j["hour"]=j.index.hour+j.index.minute/60.0
        j["session_bucket"]=pd.cut(j["hour"],[-1,11,13.5,24],labels=["OPEN","MID","LATE"]).astype(str)
        return j.replace([np.inf,-np.inf],np.nan), None

    def _eval_signal(df,signal,h,cost_bps):
        x=df.copy()
        x["fwd_bps"]=(x["spot_close"].shift(-h)/x["spot_close"]-1.0)*10000.0
        x["signal"]=signal.reindex(x.index)
        x=x.dropna(subset=["fwd_bps","signal"])
        x=x[x["signal"]!=0]
        if len(x)==0: return {"signals":0}
        gross=x["signal"]*x["fwd_bps"]
        net=gross-float(cost_bps)
        wins=(gross>0).astype(int)
        return {"signals":int(len(x)),"accuracy_percent":_safe(wins.mean()*100,1),"gross_avg_bps":_safe(gross.mean(),2),"net_avg_bps":_safe(net.mean(),2)}

    @app.get("/api/futures/attribution")
    def futures_failure_attribution_v1519(cost_bps:float=3.0):
        df,err=_prepare()
        if err: return {"status":"error","version":"15.19","message":err,"live_routing_changed":False}
        features=["basis_pct","basis_chg1","fut_oi","oi_chg1_pct","price_oi_interaction","vol_chg1_pct"]
        horizons=[2,4,6,8]
        rows=[]
        for feat in features:
            s=pd.to_numeric(df[feat],errors="coerce")
            valid=s.dropna()
            if len(valid)<100: continue
            qlo,qhi=valid.quantile([0.30,0.70])
            sig=pd.Series(0.0,index=df.index)
            sig.loc[s>=qhi]=1.0
            sig.loc[s<=qlo]=-1.0
            for h in horizons:
                r=_eval_signal(df,sig,h,cost_bps)
                rows.append({"feature":feat,"horizon_bars":h,"rule":"top30 LONG / bottom30 SHORT",**r})
                rows.append({"feature":feat,"horizon_bars":h,"rule":"reversed",**_eval_signal(df,-sig,h,cost_bps)})
        # Price/OI quadrant attribution
        qsig=pd.Series(0.0,index=df.index)
        pr=np.sign(df["fut_ret1"]); oc=np.sign(df["oi_chg1_pct"])
        qsig[(pr>0)&(oc>0)]=1
        qsig[(pr<0)&(oc>0)]=-1
        quadrants=[]
        for h in horizons:
            quadrants.append({"horizon_bars":h,**_eval_signal(df,qsig,h,cost_bps)})
        # Time-of-day attribution for best raw candidate, without claiming promotion.
        ranked=sorted([r for r in rows if r.get("signals",0)>=20 and r.get("net_avg_bps") is not None],key=lambda r:r["net_avg_bps"],reverse=True)
        best=ranked[0] if ranked else None
        regimes=[]
        if best:
            s=pd.to_numeric(df[best["feature"]],errors="coerce")
            qlo,qhi=s.dropna().quantile([0.30,0.70])
            sig=pd.Series(0.0,index=df.index); sig[s>=qhi]=1; sig[s<=qlo]=-1
            if best["rule"]=="reversed": sig=-sig
            for bucket in ["OPEN","MID","LATE"]:
                mask=df["session_bucket"]==bucket
                regimes.append({"session":bucket,**_eval_signal(df[mask],sig[mask],best["horizon_bars"],cost_bps)})
        return {
            "status":"success","version":"15.19",
            "purpose":"Failure attribution only — not a promotion test.",
            "overlap_bars":int(len(df)),
            "cost_bps":float(cost_bps),
            "horizons_tested":[2,4,6,8],
            "feature_direction_tests":rows,
            "price_oi_quadrant_tests":quadrants,
            "best_exploratory_candidate":best,
            "best_candidate_session_breakdown":regimes,
            "interpretation_rule":"Use this output to locate failure modes or hypotheses. Any promising subgroup must pass a new chronological out-of-sample validation before it can be considered for shadow mode.",
            "live_routing_changed":False
        }

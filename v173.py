VERSION="17.3"
FEATURES=["ret1","ret3","ema_gap","rsi14","rv20","atr14_pct","z20","tod_sin","tod_cos"]
def setup_v173(app):
 @app.get("/api/v17/challenger2/status")
 def status():
  return {"status":"success","version":VERSION,"stage":"FROZEN_CHALLENGER_2","hypothesis":{"base_model":"v17.1 logistic challenger","probability_threshold":0.60,"filter":"HIGH_TREND_STRENGTH_ONLY","trend_measure":"abs(ema_gap)","high_cutoff":"67th percentile learned from each training window only","horizon_bars":6,"timeframe":"15m","cost_bps":3.0},"production_model_replaced":False,"live_routing_changed":False,"validator":"/api/v17/challenger2/validate"}
 @app.get("/api/v17/challenger2/validate")
 def validate():
  try:
   import numpy as np
   from v171 import _load_history,_features,_fit_logit,_sigmoid,_brier
   f=_features(_load_history(),6); n=len(f); cut=int(n*.70); dev=f.iloc[:cut]; hold=f.iloc[cut:]
   corr=dev[FEATURES].corr().abs(); keep=[]
   for col in FEATURES:
    if not any(corr.loc[col,k]>.92 for k in keep):keep.append(col)
   def ev(te,p,tc):
    a=((p>=.60)|(p<=.40))&(te["ema_gap"].abs().to_numpy(float)>=tc); pred=np.where(p>=.60,1,0); y=te["y"].to_numpy(int); r=te["future_bps"].to_numpy(float); nn=int(a.sum())
    if not nn:return {"signals":0,"accuracy_percent":None,"net_avg_bps":None,"brier":None}
    s=np.where(pred[a]==1,r[a],-r[a])
    return {"signals":nn,"accuracy_percent":round(float((pred[a]==y[a]).mean()*100),2),"net_avg_bps":round(float((s-3).mean()),3),"brier":round(_brier(y[a],p[a]),5)}
   start=max(1800,int(len(dev)*.45)); block=max(1,(len(dev)-start)//4); folds=[]
   for i in range(4):
    a=start+i*block; b=len(dev) if i==3 else min(len(dev),a+block); tr=dev.iloc[:a]; te=dev.iloc[a:b]; mu=tr[keep].mean(); sd=tr[keep].std().replace(0,1); tc=float(tr["ema_gap"].abs().quantile(.67))
    w,bi=_fit_logit(((tr[keep]-mu)/sd).clip(-6,6).to_numpy(float),tr["y"].to_numpy(float)); p=_sigmoid(((te[keep]-mu)/sd).clip(-6,6).to_numpy(float)@w+bi); m=ev(te,p,tc); m.update({"fold":i+1,"training_only_high_trend_cut":round(tc,8)}); folds.append(m)
   ns=sum(x["signals"] for x in folds); pos=sum(1 for x in folds if x["signals"] and x["net_avg_bps"]>0); wa=sum((x["accuracy_percent"] or 0)*x["signals"] for x in folds)/ns if ns else 0; wn=sum((x["net_avg_bps"] or 0)*x["signals"] for x in folds)/ns if ns else -999
   mu=dev[keep].mean(); sd=dev[keep].std().replace(0,1); tc=float(dev["ema_gap"].abs().quantile(.67)); w,bi=_fit_logit(((dev[keep]-mu)/sd).clip(-6,6).to_numpy(float),dev["y"].to_numpy(float)); ph=_sigmoid(((hold[keep]-mu)/sd).clip(-6,6).to_numpy(float)@w+bi); hm=ev(hold,ph,tc)
   gates={"walk_forward_signals_150":ns>=150,"walk_forward_accuracy_55":wa>=55,"walk_forward_net_positive":wn>0,"positive_net_folds_3of4":pos>=3,"holdout_signals_75":hm["signals"]>=75,"holdout_accuracy_55":(hm["accuracy_percent"] or 0)>=55,"holdout_net_positive":(hm["net_avg_bps"] if hm["net_avg_bps"] is not None else -999)>0,"holdout_brier_below_025":(hm["brier"] if hm["brier"] is not None else 1)<.25}
   return {"status":"success","version":VERSION,"hypothesis":{"filter":"HIGH trend strength only","training_percentile":67,"probability_threshold":0.60,"horizon_bars":6,"cost_bps":3.0},"data":{"feature_rows":n,"development_rows":len(dev),"untouched_holdout_rows":len(hold)},"walk_forward":{"signals":ns,"weighted_accuracy_percent":round(wa,2),"weighted_net_avg_bps":round(wn,3),"positive_net_folds":pos,"folds":folds},"untouched_holdout":hm,"final_training_only_high_trend_cut":round(tc,8),"gate_checks":gates,"verdict":"CHALLENGER 2 PASSES FROZEN VALIDATION" if all(gates.values()) else "CHALLENGER 2 NOT PROMOTED","production_model_replaced":False,"live_routing_changed":False}
  except Exception as e:return {"status":"error","version":VERSION,"stage":"VALIDATION","message":str(e),"production_model_replaced":False,"live_routing_changed":False}

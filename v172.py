VERSION="17.2"
def setup_v172(app):
 @app.get("/api/v17/challenger/v172-status")
 def status():
  return {"status":"success","version":VERSION,"stage":"FAILURE_ATTRIBUTION_ONLY","input":"v17.1 rejected challenger","dimensions":["fold","session","volatility","trend strength","coefficient stability"],"creates_new_model":False,"changes_threshold":False,"production_model_replaced":False,"live_routing_changed":False,"endpoint":"/api/v17/challenger/attribution"}
 @app.get("/api/v17/challenger/attribution")
 def attribution():
  try:
   import numpy as np,pandas as pd
   from v171 import _load_history,_features,FEATURES,_fit_logit,_sigmoid
   f=_features(_load_history(),6); dev=f.iloc[:int(len(f)*.70)].copy()
   corr=dev[FEATURES].corr().abs(); keep=[]
   for col in FEATURES:
    if not any(corr.loc[col,k]>.92 for k in keep):keep.append(col)
   start=max(1800,int(len(dev)*.45)); block=max(1,(len(dev)-start)//4); parts=[]; coefs=[]
   for i in range(4):
    a=start+i*block; b=len(dev) if i==3 else min(len(dev),a+block); tr=dev.iloc[:a]; te=dev.iloc[a:b].copy()
    mu=tr[keep].mean(); sd=tr[keep].std().replace(0,1)
    w,bias=_fit_logit(((tr[keep]-mu)/sd).clip(-6,6).to_numpy(float),tr["y"].to_numpy(float))
    p=_sigmoid(((te[keep]-mu)/sd).clip(-6,6).to_numpy(float)@w+bias)
    te["p"]=p; te["fold"]=i+1; te["pred"]=np.where(p>=.60,1,np.where(p<=.40,0,-1)); te=te[te["pred"]!=-1]; parts.append(te)
    coefs.append({"fold":i+1,"coefficients":{k:round(float(v),5) for k,v in zip(keep,w)}})
   ev=pd.concat(parts).sort_index()
   ev["signed_bps"]=np.where(ev["pred"]==1,ev["future_bps"],-ev["future_bps"]); ev["net_bps"]=ev["signed_bps"]-3; ev["correct"]=(ev["pred"]==ev["y"]).astype(int)
   mins=ev.index.hour*60+ev.index.minute; ev["session"]=pd.cut(mins,[-1,659,779,2000],labels=["OPEN","MID","LATE"])
   qv=dev["rv20"].quantile([.33,.67]).tolist(); qt=dev["ema_gap"].abs().quantile([.33,.67]).tolist()
   ev["volatility"]=pd.cut(ev["rv20"],[-np.inf,qv[0],qv[1],np.inf],labels=["LOW","MID","HIGH"])
   ev["trend_strength"]=pd.cut(ev["ema_gap"].abs(),[-np.inf,qt[0],qt[1],np.inf],labels=["LOW","MID","HIGH"])
   def summ(c):
    return [{"bucket":str(k),"signals":len(g),"accuracy_percent":round(float(g.correct.mean()*100),2),"gross_avg_bps":round(float(g.signed_bps.mean()),3),"net_avg_bps":round(float(g.net_bps.mean()),3),"positive_net":bool(g.net_bps.mean()>0)} for k,g in ev.groupby(c,observed=True)]
   signs={k:[int(np.sign(x["coefficients"][k])) for x in coefs] for k in keep}; stable=[k for k,v in signs.items() if len(set(v))==1 and 0 not in v]
   return {"status":"success","version":VERSION,"stage":"CHALLENGER_FAILURE_ATTRIBUTION","source_verdict":"v17.1 CHALLENGER NOT PROMOTED","signals_analyzed":len(ev),"diagnostics":{"by_fold":summ("fold"),"by_session":summ("session"),"by_volatility":summ("volatility"),"by_trend_strength":summ("trend_strength"),"standardized_coefficients":coefs,"coefficient_sign_stable":stable,"coefficient_sign_unstable":[k for k in keep if k not in stable]},"interpretation_policy":"Descriptive failure attribution only. Best-looking buckets are not promoted or treated as validated edges.","next_action":"Use diagnostics only to decide whether a single defensible Challenger #2 hypothesis exists. Freeze it before testing.","production_model_replaced":False,"live_routing_changed":False}
  except Exception as e:return {"status":"error","version":VERSION,"stage":"ATTRIBUTION","message":str(e),"production_model_replaced":False,"live_routing_changed":False}

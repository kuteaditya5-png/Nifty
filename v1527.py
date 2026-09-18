import os,sqlite3,json,urllib.request,urllib.parse
from pathlib import Path
from datetime import date,timedelta
from v1526 import _fetch_chunk as _proven_fetch
DB=Path(os.getenv("NIFTY_HISTORY_DB","/tmp/nifty_v1527.sqlite"))
INST="NSE_INDEX|Nifty 50"
def _con():
 c=sqlite3.connect(str(DB));c.execute("CREATE TABLE IF NOT EXISTS nifty15(instrument TEXT,timestamp TEXT,open REAL,high REAL,low REAL,close REAL,volume REAL,oi REAL,PRIMARY KEY(instrument,timestamp))");return c
def _fetch(a,b,token,inst=INST):
 k=urllib.parse.quote(inst,safe="");u=f"https://api.upstox.com/v3/historical-candle/{k}/minutes/15/{b}/{a}"
 q=urllib.request.Request(u,headers={"Accept":"application/json","Authorization":"Bearer "+token})
 with urllib.request.urlopen(q,timeout=30) as r:p=json.loads(r.read().decode())
 return ((p or {}).get("data") or {}).get("candles") or []
def setup_v1527(app):
 from main import _v146_load_raw_history
 @app.get("/api/history/nifty/persistent-backfill")
 def backfill(from_date:str="2023-01-01",to_date:str="2025-05-22",max_chunks:int=18):
  token=os.getenv("UPSTOX_ACCESS_TOKEN","").strip()
  if not token:return {"status":"error","version":"15.27","message":"UPSTOX_ACCESS_TOKEN missing"}
  a=date.fromisoformat(from_date);b=date.fromisoformat(to_date);chunks=[]
  while a<=b:
   e=min(a+timedelta(days=27),b);chunks.append((a,e));a=e+timedelta(days=1)
  con=_con();rec=add=0;details=[]
  for a,b in list(reversed(chunks))[:max(1,min(max_chunks,36))]:
   try:
    _,rr=_proven_fetch(INST,a,b,token);rows=[[r["timestamp"],r["open"],r["high"],r["low"],r["close"],r.get("volume",0),r.get("oi",0)] for r in rr];rec+=len(rows);before=con.total_changes
    for x in rows:
     if len(x)>=5:con.execute("INSERT OR REPLACE INTO nifty15 VALUES(?,?,?,?,?,?,?,?)",(INST,str(x[0]),x[1],x[2],x[3],x[4],x[5] if len(x)>5 else 0,x[6] if len(x)>6 else 0))
    con.commit();n=con.total_changes-before;add+=n;details.append({"from":str(a),"to":str(b),"received":len(rows),"writes":n,"ok":True})
   except Exception as e:details.append({"from":str(a),"to":str(b),"ok":False,"error":str(e)[:200]})
  stored=con.execute("SELECT COUNT(*) FROM nifty15").fetchone()[0];con.close()
  return {"status":"success","version":"15.27","provider_rows_received":rec,"write_operations":add,"persistent_rows":stored,"chunks":details,"storage":str(DB),"dedup_key":"instrument+timestamp","synthetic_data":False,"live_routing_changed":False}
 @app.get("/api/history/nifty/merged-status")
 def merged():
  raw=_v146_load_raw_history("15m",limit=50000);prod=0 if raw is None else len(raw)
  con=_con();stored=con.execute("SELECT COUNT(*) FROM nifty15").fetchone()[0];con.close()
  return {"status":"success","version":"15.27","production_rows":prod,"backfill_store_rows":stored,"estimated_rows_before_timestamp_merge":prod+stored,"target_rows":12261,"storage_warning":"Vercel /tmp is ephemeral; durable DATABASE_URL/Postgres wiring is required before frozen revalidation can reliably consume this across invocations.","ready_for_frozen_revalidation":False,"live_routing_changed":False}
 @app.get("/api/history/nifty/v1527-status")
 def status():return {"status":"success","version":"15.27","backfill":"/api/history/nifty/persistent-backfill?max_chunks=18","merged_status":"/api/history/nifty/merged-status","live_routing_changed":False}

import os,urllib.error
from datetime import date
from v1526 import _fetch_chunk
def setup_v15271(app):
 @app.get("/api/history/nifty/backfill-preflight")
 def preflight():
  token=os.getenv("UPSTOX_ACCESS_TOKEN","").strip()
  if not token:return {"status":"error","version":"15.27.1","message":"UPSTOX_ACCESS_TOKEN missing","safe_to_backfill":False}
  try:
   code,rows=_fetch_chunk("NSE_INDEX|Nifty 50",date(2025,4,25),date(2025,5,22),token)
   return {"status":"success","version":"15.27.1","http_status":code,"candles_received":len(rows),"safe_to_backfill":code==200 and len(rows)>0,"request_implementation":"V15.26_PROVEN_HELPER","next_action":"Run /api/history/nifty/persistent-backfill?max_chunks=18" if rows else "Stop and diagnose provider response.","live_routing_changed":False}
  except urllib.error.HTTPError as e:
   try:body=e.read().decode("utf-8","replace")[:1200]
   except:body=""
   return {"status":"error","version":"15.27.1","http_status":e.code,"provider_response":body,"safe_to_backfill":False,"live_routing_changed":False}
  except Exception as e:return {"status":"error","version":"15.27.1","message":str(e),"safe_to_backfill":False,"live_routing_changed":False}
 @app.get("/api/history/nifty/v15271-status")
 def status():return {"status":"success","version":"15.27.1","preflight":"/api/history/nifty/backfill-preflight","backfill":"/api/history/nifty/persistent-backfill?max_chunks=18","live_routing_changed":False}

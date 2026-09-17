import os, json, urllib.request, urllib.parse
from datetime import date, timedelta, datetime

TARGET_ROWS=12261
DEFAULT_INSTRUMENT="NSE_INDEX|Nifty 50"

def _request_json(url, token):
    req=urllib.request.Request(url,headers={"Accept":"application/json","Authorization":"Bearer "+token,"User-Agent":"NIFTY-AI/15.26"})
    with urllib.request.urlopen(req,timeout=30) as r:
        return r.status,json.loads(r.read().decode("utf-8"))

def _chunks(start_date,end_date,days=28):
    cur=start_date
    while cur<=end_date:
        e=min(cur+timedelta(days=days-1),end_date)
        yield cur,e
        cur=e+timedelta(days=1)

def _fetch_chunk(instrument, start, end, token):
    key=urllib.parse.quote(instrument,safe="")
    # Upstox V3: /historical-candle/:instrument_key/:unit/:interval/:to_date/:from_date
    url=f"https://api.upstox.com/v3/historical-candle/{key}/minutes/15/{end.isoformat()}/{start.isoformat()}"
    status,payload=_request_json(url,token)
    candles=((payload or {}).get("data") or {}).get("candles") or []
    rows=[]
    for c in candles:
        if not isinstance(c,(list,tuple)) or len(c)<5: continue
        rows.append({"timestamp":c[0],"open":c[1],"high":c[2],"low":c[3],"close":c[4],
                     "volume":c[5] if len(c)>5 else 0,"oi":c[6] if len(c)>6 else 0})
    return status,rows

def setup_v1526(app):
    from main import _v146_load_raw_history

    def snapshot():
        raw=_v146_load_raw_history("15m",limit=50000)
        n=0 if raw is None else len(raw)
        s=e=None
        if n:
            try:s=str(raw.index.min());e=str(raw.index.max())
            except Exception:pass
        return n,s,e

    @app.get("/api/history/nifty/upstox-probe")
    def probe_v1526(to_date:str="2025-05-22",from_date:str="2025-04-25",
                     instrument_key:str=DEFAULT_INSTRUMENT):
        token=os.getenv("UPSTOX_ACCESS_TOKEN","").strip()
        if not token:return {"status":"error","version":"15.26","message":"UPSTOX_ACCESS_TOKEN is not configured.","live_routing_changed":False}
        try:
            f=date.fromisoformat(from_date);t=date.fromisoformat(to_date)
            status,rows=_fetch_chunk(instrument_key,f,t,token)
            return {"status":"success","version":"15.26","http_status":status,"instrument_key":instrument_key,
                    "from_date":from_date,"to_date":to_date,"candles_received":len(rows),
                    "first_candle":rows[-1] if rows else None,"last_candle":rows[0] if rows else None,
                    "provider":"Upstox Historical Candle Data V3","persisted":False,
                    "next_action":"If candles_received > 0, run /api/history/nifty/upstox-backfill.","live_routing_changed":False}
        except Exception as e:
            return {"status":"error","version":"15.26","message":str(e),"instrument_key":instrument_key,"live_routing_changed":False}

    @app.get("/api/history/nifty/upstox-backfill")
    def backfill_v1526(from_date:str="2023-01-01",to_date:str="2025-05-22",
                       instrument_key:str=DEFAULT_INSTRUMENT,max_chunks:int=6):
        token=os.getenv("UPSTOX_ACCESS_TOKEN","").strip()
        if not token:return {"status":"error","version":"15.26","message":"UPSTOX_ACCESS_TOKEN is not configured.","live_routing_changed":False}
        # Fetch-only staging is intentional unless a verified writable history adapter exists.
        # This prevents silently writing to a table/schema that the production loader may not read.
        try:
            f=date.fromisoformat(from_date);t=date.fromisoformat(to_date)
            if f>t: raise ValueError("from_date must be <= to_date")
            results=[];total=0;unique={}
            chunks=list(_chunks(f,t,28))
            # Work backwards from the current history boundary.
            chunks=list(reversed(chunks))[:max(1,min(int(max_chunks),24))]
            for a,b in chunks:
                try:
                    status,rows=_fetch_chunk(instrument_key,a,b,token)
                    for r in rows: unique[r["timestamp"]]=r
                    total+=len(rows)
                    results.append({"from":a.isoformat(),"to":b.isoformat(),"http_status":status,"rows":len(rows),"ok":True})
                except Exception as e:
                    results.append({"from":a.isoformat(),"to":b.isoformat(),"rows":0,"ok":False,"error":str(e)[:300]})
            existing,start,end=snapshot()
            return {"status":"success","version":"15.26","engine":"Upstox NIFTY Historical Backfill",
                    "provider":"Upstox Historical Candle Data V3","instrument_key":instrument_key,
                    "requested_range":{"from":from_date,"to":to_date},"chunks_attempted":len(results),
                    "provider_rows_received":total,"unique_provider_candles":len(unique),
                    "chunk_results":results,"production_history_before":{"rows":existing,"start":start,"end":end},
                    "target_rows":TARGET_ROWS,"persisted":False,
                    "persistence_status":"AWAITING_VERIFIED_HISTORY_STORAGE_ADAPTER",
                    "message":"Real Upstox candles were fetched, but v15.26 will not guess the database table/schema used by _v146_load_raw_history. Wire the verified production history storage adapter before persistence.",
                    "synthetic_data":False,"frozen_rule_changed":False,"live_routing_changed":False}
        except Exception as e:
            return {"status":"error","version":"15.26","message":str(e),"live_routing_changed":False}

    @app.get("/api/history/nifty/v1526-status")
    def status_v1526():
        n,s,e=snapshot()
        return {"status":"success","version":"15.26","current_rows":n,"current_start":s,"current_end":e,
                "target_rows":TARGET_ROWS,"remaining_rows":max(0,TARGET_ROWS-n),
                "probe":"/api/history/nifty/upstox-probe",
                "backfill":"/api/history/nifty/upstox-backfill",
                "frozen_revalidation":"/api/regime/frozen-validation",
                "provider_contract":"Upstox V3 historical candles, minutes/15, max one-month retrieval window per request",
                "synthetic_data":False,"live_routing_changed":False}

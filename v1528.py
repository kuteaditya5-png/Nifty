import os, json, urllib.request, urllib.parse
from datetime import date,timedelta
import pandas as pd
try:
    import psycopg2
except Exception:
    psycopg2=None
from v1526 import _fetch_chunk as _proven_fetch

VERSION="15.28"
INST="NSE_INDEX|Nifty 50"
TARGET=12261

def _conn():
    url=os.getenv("DATABASE_URL","").strip()
    if not url: raise RuntimeError("DATABASE_URL is not configured")
    if psycopg2 is None: raise RuntimeError("psycopg2 is unavailable")
    return psycopg2.connect(url,sslmode="require")

def _ensure():
    con=_conn()
    try:
        with con.cursor() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS nifty_15m_history_v1528(
                instrument_key TEXT NOT NULL,
                candle_ts TIMESTAMPTZ NOT NULL,
                open NUMERIC, high NUMERIC, low NUMERIC, close NUMERIC,
                volume NUMERIC, oi NUMERIC,
                source TEXT NOT NULL DEFAULT 'UPSTOX',
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(instrument_key,candle_ts)
            )""")
        con.commit()
    finally: con.close()

def load_pg_history_v1528(inst=INST):
    _ensure(); con=_conn()
    try:
        q="""SELECT candle_ts AS timestamp,open,high,low,close,volume,oi
             FROM nifty_15m_history_v1528 WHERE instrument_key=%s ORDER BY candle_ts"""
        df=pd.read_sql_query(q,con,params=(inst,))
    finally: con.close()
    if df.empty:return df
    df["timestamp"]=pd.to_datetime(df["timestamp"],utc=True,errors="coerce")
    return df.dropna(subset=["timestamp"]).drop_duplicates("timestamp").set_index("timestamp").sort_index()

def _upsert(inst,rows):
    _ensure(); con=_conn(); writes=0
    sql="""INSERT INTO nifty_15m_history_v1528
      (instrument_key,candle_ts,open,high,low,close,volume,oi,source)
      VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'UPSTOX')
      ON CONFLICT(instrument_key,candle_ts) DO UPDATE SET
      open=EXCLUDED.open,high=EXCLUDED.high,low=EXCLUDED.low,close=EXCLUDED.close,
      volume=EXCLUDED.volume,oi=EXCLUDED.oi,updated_at=CURRENT_TIMESTAMP"""
    try:
        with con.cursor() as c:
            for r in rows:
                c.execute(sql,(inst,r["timestamp"],r["open"],r["high"],r["low"],r["close"],r.get("volume",0),r.get("oi",0))); writes+=1
        con.commit()
    except Exception:
        con.rollback(); raise
    finally: con.close()
    return writes

def setup_v1528(app):
    from main import _v146_load_raw_history

    @app.get("/api/history/nifty/postgres-status")
    def pg_status():
        try:
            p=load_pg_history_v1528()
            return {"status":"success","version":VERSION,"database_url_configured":bool(os.getenv("DATABASE_URL")),
                    "postgres_rows":len(p),"postgres_start":str(p.index.min()) if len(p) else None,
                    "postgres_end":str(p.index.max()) if len(p) else None,"table":"nifty_15m_history_v1528",
                    "durable_storage":True,"live_routing_changed":False}
        except Exception as e:return {"status":"error","version":VERSION,"message":str(e),"live_routing_changed":False}

    @app.get("/api/history/nifty/postgres-backfill")
    def pg_backfill(from_date:str="2024-01-28",to_date:str="2025-05-22",max_chunks:int=18):
        token=os.getenv("UPSTOX_ACCESS_TOKEN","").strip()
        if not token:return {"status":"error","version":VERSION,"message":"UPSTOX_ACCESS_TOKEN missing"}
        try:_ensure()
        except Exception as e:return {"status":"error","version":VERSION,"stage":"POSTGRES_INIT","message":str(e)}
        a=date.fromisoformat(from_date); b=date.fromisoformat(to_date); chunks=[]
        while a<=b:
            e=min(a+timedelta(days=27),b);chunks.append((a,e));a=e+timedelta(days=1)
        received=writes=0; details=[]
        for a,b in list(reversed(chunks))[:max(1,min(int(max_chunks),36))]:
            try:
                code,rows=_proven_fetch(INST,a,b,token); n=_upsert(INST,rows)
                received+=len(rows);writes+=n
                details.append({"from":str(a),"to":str(b),"http_status":code,"received":len(rows),"upserts":n,"ok":True})
            except Exception as e:
                details.append({"from":str(a),"to":str(b),"received":0,"upserts":0,"ok":False,"error":str(e)[:300]})
        p=load_pg_history_v1528()
        return {"status":"success","version":VERSION,"provider_rows_received":received,"postgres_upserts":writes,
                "postgres_rows":len(p),"postgres_start":str(p.index.min()) if len(p) else None,
                "postgres_end":str(p.index.max()) if len(p) else None,"chunks":details,
                "table":"nifty_15m_history_v1528","dedup_key":["instrument_key","candle_ts"],
                "synthetic_data":False,"next_action":"Run /api/history/nifty/integrated-status.","live_routing_changed":False}

    @app.get("/api/history/nifty/integrated-status")
    def integrated_status():
        try:
            base=_v146_load_raw_history("15m",limit=50000)
            pg=load_pg_history_v1528()
            if base is None or len(base)==0: merged=pg
            elif pg.empty: merged=base.copy()
            else:
                b=base.copy(); b.index=pd.to_datetime(b.index,utc=True,errors="coerce")
                merged=pd.concat([pg,b]).sort_index()
                merged=merged[~merged.index.duplicated(keep="last")]
            return {"status":"success","version":VERSION,"production_rows":0 if base is None else len(base),
                    "postgres_rows":len(pg),"merged_unique_rows":len(merged),
                    "merged_start":str(merged.index.min()) if len(merged) else None,
                    "merged_end":str(merged.index.max()) if len(merged) else None,
                    "target_rows":TARGET,"remaining_rows":max(0,TARGET-len(merged)),
                    "ready_for_integrated_frozen_validation":len(merged)>=TARGET,
                    "live_routing_changed":False}
        except Exception as e:return {"status":"error","version":VERSION,"message":str(e),"live_routing_changed":False}

    @app.get("/api/regime/frozen-validation-v1528")
    def frozen_integrated(blocks:int=4,cost_bps:float=3.0):
        # Temporarily provide the v15.23 validator a merged loader without changing live routing.
        import main as m, v1523
        original=m._v146_load_raw_history
        def merged_loader(timeframe="15m",limit=50000):
            base=original(timeframe,limit)
            if timeframe!="15m":return base
            pg=load_pg_history_v1528()
            if base is None or len(base)==0:return pg.tail(limit)
            if pg.empty:return base
            b=base.copy();b.index=pd.to_datetime(b.index,utc=True,errors="coerce")
            x=pd.concat([pg,b]).sort_index();x=x[~x.index.duplicated(keep="last")]
            return x.tail(limit)
        # Reproduce frozen logic by invoking a local temporary FastAPI-like registrar is unsafe;
        # expose readiness here and keep original /api/regime/frozen-validation unchanged.
        base=original("15m",50000); pg=load_pg_history_v1528()
        b=base.copy();b.index=pd.to_datetime(b.index,utc=True,errors="coerce")
        merged=pd.concat([pg,b]).sort_index();merged=merged[~merged.index.duplicated(keep="last")]
        return {"status":"ready" if len(merged)>=TARGET else "not_ready","version":VERSION,
                "merged_unique_rows":len(merged),"target_rows":TARGET,
                "message":"Integrated history is ready. v15.29 should run the unchanged frozen validator directly against this merged loader." if len(merged)>=TARGET else "Backfill more real history first.",
                "frozen_rule_changed":False,"live_routing_changed":False}

from datetime import datetime, timezone
import json, os
VERSION="16.1"

def _now(): return datetime.now(timezone.utc)
def _iso(x):
    if x is None:return None
    return str(x)

def _baseline(app):
    for r in app.routes:
        if getattr(r,"path",None)=="/prediction" and "GET" in getattr(r,"methods",set()):
            x=r.endpoint()
            if hasattr(x,"body"):
                try:x=json.loads(x.body)
                except Exception:x={"raw_response":str(x)}
            return x if isinstance(x,dict) else {"raw_response":x}
    raise RuntimeError("Existing /prediction baseline route not found")

def _trade_decision(raw):
    x=str(raw.get("fno_setup") or "").upper().strip()
    if x in ("CE","PE","WAIT"):return x
    return "WAIT"

def _market_prediction(raw):
    return str(raw.get("prediction") or "UNKNOWN")

def _parse_ts(v):
    if not v:return None
    try:return datetime.fromisoformat(str(v).replace("Z","+00:00"))
    except Exception:return None

def _snapshot(raw):
    sig=_parse_ts(raw.get("signal_generated_at"))
    now=_now()
    age=None
    if sig:
        if sig.tzinfo is None:sig=sig.replace(tzinfo=timezone.utc)
        age=round((now-sig.astimezone(timezone.utc)).total_seconds()/60,1)
    return {
      "captured_at_utc":now.isoformat(),
      "signal_generated_at":raw.get("signal_generated_at"),
      "signal_age_minutes":age,
      "market_prediction":_market_prediction(raw),
      "trade_decision":_trade_decision(raw),
      "confidence":raw.get("confidence"),
      "nifty_price":raw.get("price"),
      "combined_score":raw.get("combined_score"),
      "fno_setup_reason":raw.get("fno_setup_reason"),
      "entry":raw.get("entry") or raw.get("entry_price"),
      "target":raw.get("target") or raw.get("target_price"),
      "stop_loss":raw.get("stop_loss") or raw.get("sl"),
      "model_version":raw.get("model_version")
    }

def _db():
    import psycopg
    url=os.getenv("DATABASE_URL")
    if not url: raise RuntimeError("DATABASE_URL is not configured")
    return psycopg.connect(url,sslmode="require")

def _ensure():
    with _db() as c:
      with c.cursor() as q:
        q.execute("""CREATE TABLE IF NOT EXISTS nifty_forward_validation_v161(
          id BIGSERIAL PRIMARY KEY,
          captured_at_utc TIMESTAMPTZ NOT NULL,
          signal_generated_at TEXT,
          market_prediction TEXT,
          trade_decision TEXT NOT NULL,
          confidence TEXT,
          nifty_price DOUBLE PRECISION,
          combined_score DOUBLE PRECISION,
          fno_setup_reason TEXT,
          entry_price DOUBLE PRECISION,
          target_price DOUBLE PRECISION,
          stop_loss DOUBLE PRECISION,
          model_version TEXT,
          signal_age_minutes DOUBLE PRECISION,
          baseline_payload JSONB NOT NULL,
          UNIQUE(signal_generated_at,trade_decision)
        )""")
      c.commit()

def setup_v161(app):
    @app.get("/api/v16/forward/status")
    def status():
      try:
        _ensure()
        with _db() as c:
          with c.cursor() as q:
            q.execute("SELECT count(*),min(captured_at_utc),max(captured_at_utc),count(*) FILTER(WHERE trade_decision='CE'),count(*) FILTER(WHERE trade_decision='PE'),count(*) FILTER(WHERE trade_decision='WAIT') FROM nifty_forward_validation_v161")
            a=q.fetchone()
        return {"status":"success","version":VERSION,"stage":"FORWARD_PAPER_VALIDATION",
          "stored_snapshots":a[0],"first_capture":_iso(a[1]),"last_capture":_iso(a[2]),
          "decisions":{"CE":a[3],"PE":a[4],"WAIT":a[5]},
          "canonical_trade_field":"fno_setup","market_context_field":"prediction",
          "production_execution":False,"paper_validation_only":True,
          "archived_research_used":False,"live_routing_changed":False}
      except Exception as e:
        return {"status":"error","version":VERSION,"stage":"STATUS","message":str(e),"live_routing_changed":False}

    @app.get("/api/v16/forward/capture")
    def capture():
      try:
        raw=_baseline(app); s=_snapshot(raw); _ensure()
        inserted=False
        with _db() as c:
          with c.cursor() as q:
            q.execute("""INSERT INTO nifty_forward_validation_v161(
              captured_at_utc,signal_generated_at,market_prediction,trade_decision,confidence,nifty_price,
              combined_score,fno_setup_reason,entry_price,target_price,stop_loss,model_version,
              signal_age_minutes,baseline_payload)
              VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
              ON CONFLICT(signal_generated_at,trade_decision) DO NOTHING RETURNING id""",
              (s["captured_at_utc"],s["signal_generated_at"],s["market_prediction"],s["trade_decision"],
               s["confidence"],s["nifty_price"],s["combined_score"],s["fno_setup_reason"],s["entry"],
               s["target"],s["stop_loss"],s["model_version"],s["signal_age_minutes"],json.dumps(raw)))
            inserted=q.fetchone() is not None
          c.commit()
        return {"status":"success","version":VERSION,"stored":inserted,"duplicate_signal":not inserted,
          "snapshot":s,"canonical_trade_decision":s["trade_decision"],
          "production_execution":False,"paper_validation_only":True,"live_routing_changed":False}
      except Exception as e:
        return {"status":"error","version":VERSION,"stage":"CAPTURE","message":str(e),"live_routing_changed":False}

    @app.get("/api/v16/forward/recent")
    def recent(limit:int=20):
      try:
        _ensure(); limit=max(1,min(limit,100))
        with _db() as c:
          with c.cursor() as q:
            q.execute("""SELECT captured_at_utc,signal_generated_at,market_prediction,trade_decision,
              confidence,nifty_price,combined_score,signal_age_minutes,entry_price,target_price,stop_loss
              FROM nifty_forward_validation_v161 ORDER BY captured_at_utc DESC LIMIT %s""",(limit,))
            rows=q.fetchall()
        return {"status":"success","version":VERSION,"count":len(rows),"rows":[
          {"captured_at_utc":_iso(r[0]),"signal_generated_at":r[1],"market_prediction":r[2],
           "trade_decision":r[3],"confidence":r[4],"nifty_price":r[5],"combined_score":r[6],
           "signal_age_minutes":r[7],"entry":r[8],"target":r[9],"stop_loss":r[10]} for r in rows],
          "paper_validation_only":True,"live_routing_changed":False}
      except Exception as e:
        return {"status":"error","version":VERSION,"stage":"RECENT","message":str(e),"live_routing_changed":False}

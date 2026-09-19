import os
try:
    import psycopg
except Exception:
    psycopg=None

def setup_v15281(app):
    @app.get("/api/history/nifty/postgres-preflight")
    def postgres_preflight():
        if psycopg is None:
            return {"status":"error","version":"15.28.1","stage":"DRIVER","message":"psycopg is unavailable","safe_to_backfill":False,"live_routing_changed":False}
        url=os.getenv("DATABASE_URL","").strip()
        if not url:
            return {"status":"error","version":"15.28.1","stage":"CONFIG","message":"DATABASE_URL is not configured","safe_to_backfill":False,"live_routing_changed":False}
        try:
            with psycopg.connect(url,sslmode="require") as con:
                with con.cursor() as cur:
                    cur.execute("SELECT current_database(), current_user, version()")
                    db,user,ver=cur.fetchone()
                    cur.execute("""CREATE TABLE IF NOT EXISTS nifty_15m_history_v1528(
                        instrument_key TEXT NOT NULL,
                        candle_ts TIMESTAMPTZ NOT NULL,
                        open NUMERIC, high NUMERIC, low NUMERIC, close NUMERIC,
                        volume NUMERIC, oi NUMERIC,
                        source TEXT NOT NULL DEFAULT 'UPSTOX',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY(instrument_key,candle_ts)
                    )""")
                    cur.execute("SELECT COUNT(*) FROM nifty_15m_history_v1528")
                    rows=cur.fetchone()[0]
                con.commit()
            return {"status":"success","version":"15.28.1","stage":"POSTGRES_PREFLIGHT",
                    "driver":"psycopg3","database":db,"database_user":user,
                    "server_version":str(ver).split(",")[0],"table":"nifty_15m_history_v1528",
                    "existing_rows":rows,"safe_to_backfill":True,
                    "next_action":"Run /api/history/nifty/postgres-backfill?max_chunks=18",
                    "live_routing_changed":False}
        except Exception as e:
            return {"status":"error","version":"15.28.1","stage":"POSTGRES_PREFLIGHT",
                    "driver":"psycopg3","message":str(e)[:1000],
                    "safe_to_backfill":False,"live_routing_changed":False}

    @app.get("/api/history/nifty/v15281-status")
    def status():
        return {"status":"success","version":"15.28.1",
                "fix":"v15.28 PostgreSQL adapter changed from unavailable psycopg2 to project-standard psycopg v3.",
                "preflight":"/api/history/nifty/postgres-preflight",
                "backfill":"/api/history/nifty/postgres-backfill?max_chunks=18",
                "integrated_status":"/api/history/nifty/integrated-status",
                "live_routing_changed":False}

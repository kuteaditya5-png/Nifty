import json
import hashlib
import secrets
import math
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
import psycopg
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel


DATABASE_URL = os.getenv("DATABASE_URL")
JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
SESSION_COOKIE = "nifty_ai_session"
SESSION_DAYS = 30


PUBLIC_PATHS = {
    "/", "/login", "/auth/register", "/auth/login",
    "/health", "/docs", "/openapi.json", "/redoc"
}


class RegisterPayload(BaseModel):
    mobile_number: str
    password: str
    confirm_password: str


class LoginPayload(BaseModel):
    mobile_number: str
    password: str


class AlertSettingsPayload(BaseModel):
    alert_type: str = "BOTH"
    alert_time: Optional[str] = None
    min_confidence: float = 70.0


def _normalize_mobile(value: str) -> str:
    value = "".join(ch for ch in (value or "") if ch.isdigit() or ch == "+")
    if not value:
        raise ValueError("Mobile number is required.")

    if value.startswith("+"):
        normalized = value
    elif len(value) == 10:
        normalized = "+91" + value
    elif value.startswith("91") and len(value) == 12:
        normalized = "+" + value
    else:
        raise ValueError("Enter a valid mobile number, e.g. +919876543210.")

    digits = "".join(ch for ch in normalized if ch.isdigit())
    if len(digits) < 10 or len(digits) > 15:
        raise ValueError("Invalid mobile number.")

    return "+" + digits


def _db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured.")
    return psycopg.connect(DATABASE_URL)


def _init_db():
    if not DATABASE_URL:
        return
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS app_users (
                    user_id BIGSERIAL PRIMARY KEY,
                    mobile_number VARCHAR(20) UNIQUE NOT NULL,
                    is_mobile_verified BOOLEAN NOT NULL DEFAULT FALSE,
                    password_hash TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMPTZ
                )
            """)
            cur.execute("ALTER TABLE app_users ADD COLUMN IF NOT EXISTS password_hash TEXT")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS paper_accounts (
                    user_id BIGINT PRIMARY KEY REFERENCES app_users(user_id) ON DELETE CASCADE,
                    starting_balance NUMERIC(14,2) NOT NULL DEFAULT 100000,
                    cash_balance NUMERIC(14,2) NOT NULL DEFAULT 100000,
                    auto_trade BOOLEAN NOT NULL DEFAULT FALSE,
                    quantity INTEGER NOT NULL DEFAULT 75,
                    min_confidence NUMERIC(5,2) NOT NULL DEFAULT 70,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS paper_trades (
                    trade_id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES app_users(user_id) ON DELETE CASCADE,
                    signal VARCHAR(30) NOT NULL, option_type VARCHAR(5) NOT NULL,
                    strike_price NUMERIC(12,2) NOT NULL, nifty_price NUMERIC(12,2),
                    entry_price NUMERIC(12,2) NOT NULL, current_price NUMERIC(12,2), exit_price NUMERIC(12,2),
                    stop_loss NUMERIC(12,2), target1 NUMERIC(12,2), target2 NUMERIC(12,2), confidence NUMERIC(5,2),
                    quantity INTEGER NOT NULL DEFAULT 75, status VARCHAR(12) NOT NULL DEFAULT 'OPEN',
                    pnl NUMERIC(14,2) NOT NULL DEFAULT 0, exit_reason VARCHAR(40),
                    opened_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, closed_at TIMESTAMPTZ
                )
            """)
            cur.execute("ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS expiry VARCHAR(30)")
            cur.execute("ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS last_price_at TIMESTAMPTZ")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS prediction_audit (
                    audit_id BIGSERIAL PRIMARY KEY,
                    signal_key VARCHAR(220) UNIQUE NOT NULL,
                    model_version VARCHAR(30),
                    prediction VARCHAR(40),
                    option_type VARCHAR(5) NOT NULL,
                    expiry VARCHAR(30),
                    strike_price NUMERIC(12,2) NOT NULL,
                    nifty_price NUMERIC(12,2),
                    entry_price NUMERIC(12,2) NOT NULL,
                    current_price NUMERIC(12,2),
                    stop_loss NUMERIC(12,2),
                    target1 NUMERIC(12,2),
                    target2 NUMERIC(12,2),
                    confidence NUMERIC(5,2),
                    status VARCHAR(12) NOT NULL DEFAULT 'OPEN',
                    result VARCHAR(12),
                    pnl_points NUMERIC(12,2) NOT NULL DEFAULT 0,
                    generated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    closed_at TIMESTAMPTZ,
                    last_checked_at TIMESTAMPTZ
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS ix_prediction_audit_status
                ON prediction_audit(status, generated_at DESC)
            """)
        conn.commit()


def _hash_password(password: str) -> str:
    if len(password or "") < 6:
        raise ValueError("Password must be at least 6 characters.")
    salt=secrets.token_hex(16)
    digest=hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 250000).hex()
    return f"{salt}${digest}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt,expected=stored.split("$",1)
        actual=hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 250000).hex()
        return secrets.compare_digest(actual, expected)
    except Exception:
        return False


def _ensure_paper_account(user_id: int):
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO paper_accounts(user_id) VALUES(%s) ON CONFLICT(user_id) DO NOTHING", (user_id,))
        conn.commit()


def setup_auth(app, fno_alert_provider=None):
    try:
        _init_db()
    except Exception as e:
        print("NIFTY AI auth DB init warning:", str(e))

    @app.middleware("http")
    async def nifty_auth_middleware(request: Request, call_next):
        path = request.url.path

        if (
            path in PUBLIC_PATHS
            or path.startswith("/static/")
            or path.startswith("/auth/")
        ):
            return await call_next(request)

        if (
            path == "/dashboard"
            or path.startswith("/api/account")
        ):
            if not _current_user(request):
                if path == "/dashboard":
                    return RedirectResponse("/login", status_code=303)

                return JSONResponse(
                    {"status":"error","message":"Authentication required."},
                    status_code=401
                )

        return await call_next(request)

    @app.get("/login", response_class=HTMLResponse, include_in_schema=False)
    def login_page(request: Request):
        if _current_user(request):
            return RedirectResponse("/dashboard", status_code=303)
        return _login_page()

    @app.post("/auth/register")
    def register(payload: RegisterPayload):
        try:
            mobile=_normalize_mobile(payload.mobile_number)
            if payload.password != payload.confirm_password:
                return JSONResponse({"status":"error","message":"Passwords do not match."},status_code=400)
            ph=_hash_password(payload.password)
            with _db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT user_id,password_hash FROM app_users WHERE mobile_number=%s",(mobile,))
                    row=cur.fetchone()
                    if row and row[1]:
                        return JSONResponse({"status":"error","message":"Account already exists. Please login."},status_code=409)
                    if row:
                        cur.execute("UPDATE app_users SET password_hash=%s,last_login=CURRENT_TIMESTAMP WHERE user_id=%s RETURNING user_id",(ph,row[0]))
                    else:
                        cur.execute("INSERT INTO app_users(mobile_number,password_hash,last_login) VALUES(%s,%s,CURRENT_TIMESTAMP) RETURNING user_id",(mobile,ph))
                    uid=cur.fetchone()[0]
                conn.commit()
            _ensure_paper_account(uid)
            response=JSONResponse({"status":"success","message":"Account created."})
            response.set_cookie(SESSION_COOKIE,_create_token(uid,mobile),max_age=SESSION_DAYS*86400,httponly=True,secure=True,samesite="lax",path="/")
            return response
        except Exception as e:
            return JSONResponse({"status":"error","message":str(e)},status_code=400)

    @app.post("/auth/login")
    def password_login(payload: LoginPayload):
        try:
            mobile=_normalize_mobile(payload.mobile_number)
            with _db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT user_id,password_hash FROM app_users WHERE mobile_number=%s",(mobile,))
                    row=cur.fetchone()
                    if not row or not row[1] or not _verify_password(payload.password,row[1]):
                        return JSONResponse({"status":"error","message":"Invalid mobile number or password."},status_code=401)
                    uid=row[0]
                    cur.execute("UPDATE app_users SET last_login=CURRENT_TIMESTAMP WHERE user_id=%s",(uid,))
                conn.commit()
            _ensure_paper_account(uid)
            response=JSONResponse({"status":"success","message":"Login successful."})
            response.set_cookie(SESSION_COOKIE,_create_token(uid,mobile),max_age=SESSION_DAYS*86400,httponly=True,secure=True,samesite="lax",path="/")
            return response
        except Exception as e:
            return JSONResponse({"status":"error","message":str(e)},status_code=400)

    @app.post("/auth/logout")
    def logout():
        response = JSONResponse({"status":"success"})
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    @app.get("/api/paper/summary")
    def paper_summary(request: Request):
        user=_current_user(request); _ensure_paper_account(user["user_id"])
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT starting_balance,cash_balance,auto_trade,quantity,min_confidence FROM paper_accounts WHERE user_id=%s",(user["user_id"],)); a=cur.fetchone()
                cur.execute("SELECT COALESCE(SUM(CASE WHEN status='OPEN' THEN pnl ELSE 0 END),0),COALESCE(SUM(CASE WHEN status='CLOSED' THEN pnl ELSE 0 END),0),COUNT(*) FILTER(WHERE status='OPEN'),COUNT(*) FILTER(WHERE status='CLOSED'),COUNT(*) FILTER(WHERE status='CLOSED' AND pnl>0) FROM paper_trades WHERE user_id=%s",(user["user_id"],)); x=cur.fetchone()
        closed=int(x[3] or 0); wins=int(x[4] or 0)
        return {"status":"success","summary":{"starting_balance":float(a[0]),"cash_balance":float(a[1]),"equity":float(a[1])+float(x[0]),"open_pnl":float(x[0]),"realized_pnl":float(x[1]),"open_positions":int(x[2]),"win_rate":round(wins/closed*100,1) if closed else 0,"auto_trade":a[2],"quantity":a[3],"min_confidence":float(a[4])}}

    @app.get("/api/paper/history")
    def paper_history(request: Request):
        user=_current_user(request)
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT trade_id,signal,option_type,strike_price,entry_price,current_price,exit_price,quantity,status,pnl,exit_reason,opened_at,expiry,last_price_at FROM paper_trades WHERE user_id=%s ORDER BY trade_id DESC LIMIT 50",(user["user_id"],)); rows=cur.fetchall()
        return {"status":"success","trades":[{"trade_id":r[0],"signal":r[1],"option_type":r[2],"strike_price":float(r[3]),"entry_price":float(r[4]),"current_price":float(r[5]) if r[5] is not None else None,"exit_price":float(r[6]) if r[6] is not None else None,"quantity":r[7],"status":r[8],"pnl":float(r[9]),"exit_reason":r[10],"opened_at":r[11].isoformat(),"expiry":r[12],"last_price_at":r[13].isoformat() if r[13] else None} for r in rows]}

    @app.post("/api/paper/open")
    async def paper_open(request: Request):
        user=_current_user(request); d=await request.json(); qty=max(1,int(d.get("quantity",75))); entry=float(d["entry_price"]); cost=entry*qty
        _ensure_paper_account(user["user_id"])
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT cash_balance FROM paper_accounts WHERE user_id=%s FOR UPDATE",(user["user_id"],)); cash=float(cur.fetchone()[0])
                if cost>cash: return JSONResponse({"status":"error","message":"Not enough paper balance."},status_code=400)
                expiry=d.get("expiry")
                cur.execute("INSERT INTO paper_trades(user_id,signal,option_type,strike_price,nifty_price,entry_price,current_price,stop_loss,target1,target2,confidence,quantity,expiry,last_price_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP) RETURNING trade_id",(user["user_id"],d.get("signal"),d.get("option_type"),d.get("strike_price"),d.get("nifty_price"),entry,entry,d.get("stop_loss"),d.get("target1"),d.get("target2"),d.get("confidence"),qty,expiry)); tid=cur.fetchone()[0]
                cur.execute("UPDATE paper_accounts SET cash_balance=cash_balance-%s WHERE user_id=%s",(cost,user["user_id"]))
            conn.commit()
        return {"status":"success","trade_id":tid}

    @app.post("/api/paper/close")
    async def paper_close(request: Request):
        user=_current_user(request); d=await request.json(); tid=int(d["trade_id"]); exitp=float(d["exit_price"])
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT entry_price,quantity,status FROM paper_trades WHERE trade_id=%s AND user_id=%s FOR UPDATE",(tid,user["user_id"])); r=cur.fetchone()
                if not r or r[2] != 'OPEN': return JSONResponse({"status":"error","message":"Open trade not found."},status_code=400)
                pnl=(exitp-float(r[0]))*int(r[1]); proceeds=exitp*int(r[1])
                cur.execute("UPDATE paper_trades SET current_price=%s,exit_price=%s,pnl=%s,status='CLOSED',exit_reason='MANUAL',closed_at=CURRENT_TIMESTAMP WHERE trade_id=%s",(exitp,exitp,pnl,tid))
                cur.execute("UPDATE paper_accounts SET cash_balance=cash_balance+%s WHERE user_id=%s",(proceeds,user["user_id"]))
            conn.commit()
        return {"status":"success","pnl":round(pnl,2)}

    @app.post("/api/paper/sync")
    def paper_sync(request: Request):
        user=_current_user(request)
        if fno_alert_provider is None:
            return {"status":"success","updated":0,"message":"F&O provider unavailable."}
        try:
            snap=fno_alert_provider()
            if not isinstance(snap, dict) or snap.get("status") != "success":
                return {"status":"success","updated":0,"message":"Market snapshot unavailable."}

            audit_result = _record_and_evaluate_prediction(snap)
            updated=0
            closed=0

            with _db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT trade_id,option_type,strike_price,entry_price,quantity,
                               stop_loss,target1,target2,expiry
                        FROM paper_trades
                        WHERE user_id=%s AND status='OPEN'
                        ORDER BY trade_id
                    """,(user["user_id"],))
                    rows=cur.fetchall()

                    for r in rows:
                        tid,typ,strike,entry,qty,stop,t1,t2,expiry=r
                        live=_exact_contract_price(snap,typ,strike,expiry)
                        if live is None:
                            continue

                        pnl=(float(live)-float(entry))*int(qty)
                        exit_reason=None
                        if stop is not None and live <= float(stop):
                            exit_reason="STOP LOSS"
                        elif t2 is not None and live >= float(t2):
                            exit_reason="TARGET 2"
                        elif t1 is not None and live >= float(t1):
                            exit_reason="TARGET 1"

                        if exit_reason:
                            proceeds=float(live)*int(qty)
                            cur.execute("""
                                UPDATE paper_trades
                                SET current_price=%s,exit_price=%s,pnl=%s,status='CLOSED',
                                    exit_reason=%s,closed_at=CURRENT_TIMESTAMP,last_price_at=CURRENT_TIMESTAMP
                                WHERE trade_id=%s
                            """,(live,live,pnl,exit_reason,tid))
                            cur.execute("UPDATE paper_accounts SET cash_balance=cash_balance+%s WHERE user_id=%s",(proceeds,user["user_id"]))
                            closed+=1
                        else:
                            cur.execute("""
                                UPDATE paper_trades
                                SET current_price=%s,pnl=%s,last_price_at=CURRENT_TIMESTAMP
                                WHERE trade_id=%s
                            """,(live,pnl,tid))
                        updated+=1
                conn.commit()

            return {
                "status":"success",
                "updated":updated,
                "closed":closed,
                "audit_created":audit_result.get("created",0),
                "audit_evaluated":audit_result.get("evaluated",0)
            }
        except Exception as e:
            return {"status":"success","updated":0,"message":str(e)}

    @app.get("/api/accuracy/summary")
    def accuracy_summary(request: Request):
        try:
            if fno_alert_provider is not None:
                snap=fno_alert_provider()
                _record_and_evaluate_prediction(snap)
            return {"status":"success","summary":_accuracy_summary()}
        except Exception as e:
            return JSONResponse({"status":"error","message":str(e)},status_code=400)

    @app.get("/api/accuracy/history")
    def accuracy_history(request: Request, limit: int = 30):
        limit=max(1,min(100,int(limit)))
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT audit_id,prediction,option_type,expiry,strike_price,entry_price,
                           current_price,stop_loss,target1,target2,confidence,status,result,
                           pnl_points,generated_at,closed_at
                    FROM prediction_audit
                    ORDER BY audit_id DESC
                    LIMIT %s
                """,(limit,))
                rows=cur.fetchall()
        return {"status":"success","signals":[{
            "audit_id":r[0],"prediction":r[1],"option_type":r[2],"expiry":r[3],
            "strike_price":float(r[4]),"entry_price":float(r[5]),
            "current_price":float(r[6]) if r[6] is not None else None,
            "stop_loss":float(r[7]) if r[7] is not None else None,
            "target1":float(r[8]) if r[8] is not None else None,
            "target2":float(r[9]) if r[9] is not None else None,
            "confidence":float(r[10]) if r[10] is not None else None,
            "status":r[11],"result":r[12],"pnl_points":float(r[13] or 0),
            "generated_at":r[14].isoformat() if r[14] else None,
            "closed_at":r[15].isoformat() if r[15] else None
        } for r in rows]}

    @app.post("/api/paper/reset")
    def paper_reset(request: Request):
        user=_current_user(request)
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM paper_trades WHERE user_id=%s",(user["user_id"],)); cur.execute("UPDATE paper_accounts SET cash_balance=starting_balance WHERE user_id=%s",(user["user_id"],))
            conn.commit()
        return {"status":"success"}

    @app.get("/api/account/me")
    def me(request: Request):
        user = _current_user(request)

        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        user_id,
                        mobile_number,
                        is_mobile_verified,
                        last_login
                    FROM app_users
                    WHERE user_id=%s
                """, (user["user_id"],))
                row = cur.fetchone()

        if not row:
            return JSONResponse(
                {"status":"error","message":"User not found."},
                status_code=404
            )

        return {
            "status":"success",
            "user":{
                "user_id":row[0],
                "mobile_number":row[1],
                "is_mobile_verified":row[2],
                "last_login":row[4].isoformat() if row[4] else None
            }
        }

    @app.get("/api/account/alert-settings")
    def get_alert_settings(request: Request):
        user = _current_user(request)

        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        alert_id,
                        alert_time,
                        alert_type,
                        min_confidence,
                        is_active
                    FROM fo_alert_settings
                    WHERE user_id=%s
                      AND is_active=TRUE
                    ORDER BY alert_id DESC
                    LIMIT 1
                """, (user["user_id"],))
                row = cur.fetchone()

        if not row:
            return {"status":"success","settings":None}

        return {
            "status":"success",
            "settings":{
                "alert_id":row[0],
                "alert_time":row[1].isoformat() if row[1] else None,
                "alert_type":row[2],
                "min_confidence":float(row[3]),
                "is_active":row[4]
            }
        }

    @app.post("/api/account/alert-settings")
    def save_alert_settings(
        payload: AlertSettingsPayload,
        request: Request
    ):
        user = _current_user(request)
        alert_type = payload.alert_type.upper()

        if alert_type not in {"CE","PE","BOTH"}:
            return JSONResponse(
                {
                    "status":"error",
                    "message":"alert_type must be CE, PE or BOTH."
                },
                status_code=400
            )

        min_confidence = max(
            0,
            min(100, float(payload.min_confidence))
        )

        alert_time = None
        if payload.alert_time:
            try:
                alert_time = datetime.strptime(
                    payload.alert_time,
                    "%H:%M"
                ).time()
            except ValueError:
                return JSONResponse(
                    {
                        "status":"error",
                        "message":"alert_time must be HH:MM."
                    },
                    status_code=400
                )

        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE fo_alert_settings
                    SET
                        is_active=FALSE,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE user_id=%s
                      AND is_active=TRUE
                """, (user["user_id"],))

                cur.execute("""
                    INSERT INTO fo_alert_settings(
                        user_id,
                        alert_time,
                        alert_type,
                        min_confidence,
                        is_active
                    )
                    VALUES(%s,%s,%s,%s,TRUE)
                    RETURNING alert_id
                """, (
                    user["user_id"],
                    alert_time,
                    alert_type,
                    min_confidence
                ))

                alert_id = cur.fetchone()[0]

                cur.execute("""
                    UPDATE app_users
                    WHERE user_id=%s
                """, (
                    user["user_id"]
                ))

            conn.commit()

        return {
            "status":"success",
            "alert_id":alert_id
        }

    @app.get("/api/account/alert-history")
    def alert_history(
        request: Request,
        limit: int = 30
    ):
        user = _current_user(request)
        limit = max(1, min(100, limit))

        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        signal,
                        nifty_price,
                        strike_price,
                        option_type,
                        entry_price,
                        stop_loss,
                        target1,
                        target2,
                        confidence,
                        sent_at
                    FROM fo_alert_history
                    WHERE user_id=%s
                    ORDER BY sent_at DESC
                    LIMIT %s
                """, (
                    user["user_id"],
                    limit
                ))
                rows = cur.fetchall()

        return {
            "status":"success",
            "history":[
                {
                    "signal":r[0],
                    "nifty_price":float(r[1]) if r[1] is not None else None,
                    "strike_price":float(r[2]) if r[2] is not None else None,
                    "option_type":r[3],
                    "entry_price":float(r[4]) if r[4] is not None else None,
                    "stop_loss":float(r[5]) if r[5] is not None else None,
                    "target1":float(r[6]) if r[6] is not None else None,
                    "target2":float(r[7]) if r[7] is not None else None,
                    "confidence":float(r[8]) if r[8] is not None else None,
                    "sent_at":r[10].isoformat() if r[10] else None
                }
                for r in rows
            ]
        }



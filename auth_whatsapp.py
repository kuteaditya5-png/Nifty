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
from twilio.rest import Client


DATABASE_URL = os.getenv("DATABASE_URL")
JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
SESSION_COOKIE = "nifty_ai_session"
SESSION_DAYS = 30

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM")
TWILIO_CONTENT_SID = os.getenv("TWILIO_CONTENT_SID")

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
    whatsapp_enabled: bool = True


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
                    whatsapp_enabled BOOLEAN NOT NULL DEFAULT TRUE,
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


def _twilio_client():
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        raise RuntimeError("Twilio credentials are not configured.")
    return Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def _create_token(user_id: int, mobile: str) -> str:
    if not JWT_SECRET or len(JWT_SECRET) < 24:
        raise RuntimeError("JWT_SECRET must be configured with a strong random value.")

    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "mobile": mobile,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=SESSION_DAYS)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode_token(token: str):
    if not token or not JWT_SECRET:
        return None
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        return None


def _current_user(request: Request):
    payload = _decode_token(request.cookies.get(SESSION_COOKIE))
    if not payload:
        return None

    try:
        return {
            "user_id": int(payload["sub"]),
            "mobile_number": payload["mobile"],
        }
    except Exception:
        return None


def _login_page():
    return r"""
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>NIFTY AI Login</title>
<style>*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#07111f;color:#eef5ff;font-family:Inter,system-ui,sans-serif}.card{width:min(92vw,430px);background:#0d1a2b;border:1px solid #22334c;border-radius:22px;padding:28px}.logo{width:50px;height:50px;display:grid;place-items:center;border-radius:14px;background:#eef5ff;color:#08111e;font-weight:900}h1{margin:18px 0 6px}.sub,.status,.small{color:#91a3bb;line-height:1.5}label{display:block;margin:15px 0 7px;color:#b9c8db;font-size:13px}input{width:100%;padding:14px;border:1px solid #2c405d;border-radius:12px;background:#081423;color:white;font-size:16px}button{width:100%;margin-top:16px;padding:14px;border:0;border-radius:12px;background:#eef5ff;color:#08111e;font-size:15px;font-weight:800}.secondary{background:#13243a;color:#eef5ff;border:1px solid #28405f}.hidden{display:none}.status{min-height:20px;margin-top:12px;font-size:13px}.small{font-size:12px;margin-top:16px}</style></head><body>
<div class="card"><div class="logo">N</div><h1>NIFTY AI</h1><div class="sub" id="subtitle">Login with your mobile number and password.</div>
<label>Mobile number</label><input id="mobile" inputmode="tel" placeholder="+91 98765 43210">
<label>Password</label><input id="password" type="password" placeholder="Password">
<div id="confirmBox" class="hidden"><label>Confirm password</label><input id="confirm" type="password" placeholder="Confirm password"></div>
<button id="mainBtn" onclick="submitForm()">Login</button><button class="secondary" id="switchBtn" onclick="switchMode()">First time? Create Password</button><div class="status" id="status"></div>
<div class="small">Password is stored as a secure hash. OTP is no longer used for login.</div></div>
<script>let register=false;function switchMode(){register=!register;document.getElementById('confirmBox').classList.toggle('hidden',!register);document.getElementById('mainBtn').textContent=register?'Create Account':'Login';document.getElementById('switchBtn').textContent=register?'Already registered? Login':'First time? Create Password';document.getElementById('subtitle').textContent=register?'Create your password for this mobile number.':'Login with your mobile number and password.'}async function submitForm(){const body={mobile_number:document.getElementById('mobile').value.trim(),password:document.getElementById('password').value};if(register)body.confirm_password=document.getElementById('confirm').value;const r=await fetch(register?'/auth/register':'/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();document.getElementById('status').textContent=d.message||d.detail||'';if(r.ok)location.href='/dashboard'}</script></body></html>
"""


def _pick_trade(alerts):
    if not isinstance(alerts, dict):
        return None

    candidates = []
    for key, option_type in (("call", "CE"), ("put", "PE")):
        item = alerts.get(key) or {}
        signal = str(item.get("signal") or "WAIT").upper()

        try:
            strength = float(item.get("signal_strength") or item.get("confidence") or 0)
        except Exception:
            strength = 0.0

        if "BUY" in signal:
            candidates.append((strength, option_type, item))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1], candidates[0][2]


def _signal_key(option_type, item, nifty_price):
    strike = item.get("strike") or item.get("strike_price")
    signal = str(item.get("signal") or "WAIT").upper()

    try:
        rounded_nifty = round(float(nifty_price or 0), -1)
    except Exception:
        rounded_nifty = 0

    return f"{option_type}|{strike}|{signal}|{rounded_nifty}"


def _already_sent(user_id: int, signal_key: str, minutes: int = 45):
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 1
                FROM fo_alert_history
                WHERE user_id=%s
                  AND signal_key=%s
                  AND sent_at >= CURRENT_TIMESTAMP - (%s * INTERVAL '1 minute')
                LIMIT 1
            """, (user_id, signal_key, minutes))
            return cur.fetchone() is not None


def _send_whatsapp(to_mobile: str, text: str):
    if not TWILIO_WHATSAPP_FROM:
        raise RuntimeError("TWILIO_WHATSAPP_FROM is not configured.")

    client = _twilio_client()
    kwargs = {
        "from_": TWILIO_WHATSAPP_FROM,
        "to": "whatsapp:" + to_mobile,
    }

    if TWILIO_CONTENT_SID:
        kwargs["content_sid"] = TWILIO_CONTENT_SID
        kwargs["content_variables"] = json.dumps({"1": text}, ensure_ascii=False)
    else:
        kwargs["body"] = text

    msg = client.messages.create(**kwargs)
    return msg.sid


def _num(value):
    try:
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            return float(value)
        if value is None:
            return None

        match = re.search(
            r"-?\d+(?:\.\d+)?",
            str(value).replace(",", "")
        )
        return float(match.group()) if match else None
    except Exception:
        return None


def _exact_contract_price(snapshot, option_type, strike_price, expiry=None):
    """Return the latest premium for the exact saved strike/type from option-chain rows."""
    if not isinstance(snapshot, dict):
        return None
    chain = snapshot.get("option_chain") or {}
    snap_expiry = chain.get("expiry")
    if expiry and snap_expiry and str(expiry) != str(snap_expiry):
        return None
    rows = chain.get("nearby_strikes") or []
    for row in rows:
        try:
            if abs(float(row.get("strike")) - float(strike_price)) > 0.01:
                continue
            key = "call_ltp" if str(option_type).upper() == "CE" else "put_ltp"
            value = row.get(key)
            if value is None:
                return None
            value = float(value)
            return value if value > 0 else None
        except Exception:
            continue
    return None


def _alert_entry_price(side):
    if not isinstance(side, dict):
        return None
    for key in ("ltp", "option_ltp", "premium", "entry_price"):
        try:
            value = side.get(key)
            if value is not None and float(value) > 0:
                return float(value)
        except Exception:
            pass
    zone = side.get("entry_zone") or {}
    if isinstance(zone, dict):
        try:
            low = zone.get("low")
            high = zone.get("high")
            if low is not None and high is not None:
                return (float(low) + float(high)) / 2.0
        except Exception:
            pass
    return None


def _record_and_evaluate_prediction(snapshot):
    """
    Audit every qualifying BUY CE/PE signal globally.
    A prediction is a WIN when Target 1 is observed before the stop;
    a LOSS when the stop is observed first. OPEN signals remain pending.
    """
    if not isinstance(snapshot, dict) or snapshot.get("status") != "success":
        return {"created": 0, "evaluated": 0}

    chain = snapshot.get("option_chain") or {}
    expiry = chain.get("expiry")
    alerts = snapshot.get("alerts") or {}
    created = 0
    evaluated = 0

    # First update every open audit using its exact saved contract.
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT audit_id, option_type, strike_price, expiry, entry_price,
                       stop_loss, target1, target2
                FROM prediction_audit
                WHERE status='OPEN'
                ORDER BY audit_id
            """)
            open_rows = cur.fetchall()

            for row in open_rows:
                audit_id, typ, strike, saved_expiry, entry, stop, t1, t2 = row
                live = _exact_contract_price(snapshot, typ, strike, saved_expiry)
                if live is None:
                    continue
                pnl_points = float(live) - float(entry)
                status = "OPEN"
                result = None
                closed = False

                # Conservative evaluation: stop takes precedence if both appear crossed
                # between sparse refreshes.
                if stop is not None and live <= float(stop):
                    status, result, closed = "CLOSED", "LOSS", True
                elif t1 is not None and live >= float(t1):
                    status, result, closed = "CLOSED", "WIN", True

                cur.execute("""
                    UPDATE prediction_audit
                    SET current_price=%s, pnl_points=%s, status=%s, result=%s,
                        last_checked_at=CURRENT_TIMESTAMP,
                        closed_at=CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE closed_at END
                    WHERE audit_id=%s
                """, (live, pnl_points, status, result, closed, audit_id))
                evaluated += 1

        conn.commit()

    # Then record current qualifying BUY signals, deduped by contract + rounded minute.
    for typ, key in (("CE", "call"), ("PE", "put")):
        side = alerts.get(key) or {}
        signal = str(side.get("signal") or "").upper()
        if "BUY" not in signal:
            continue

        try:
            strike = float(side.get("strike"))
        except Exception:
            continue
        entry = _alert_entry_price(side)
        if entry is None:
            continue

        confidence = side.get("signal_strength_percent")
        try:
            confidence = float(confidence) if confidence is not None else None
        except Exception:
            confidence = None

        # One audit row per same contract / 15-minute window.
        bucket = datetime.now().strftime("%Y%m%d%H")
        minute_bucket = int(datetime.now().minute // 15)
        signal_key = f"{typ}|{expiry}|{strike:.2f}|{bucket}|{minute_bucket}"

        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO prediction_audit(
                        signal_key, model_version, prediction, option_type, expiry,
                        strike_price, nifty_price, entry_price, current_price,
                        stop_loss, target1, target2, confidence, status, generated_at,
                        last_checked_at
                    )
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'OPEN',
                           CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
                    ON CONFLICT(signal_key) DO NOTHING
                """, (
                    signal_key,
                    snapshot.get("model_version"),
                    snapshot.get("prediction"),
                    typ,
                    expiry,
                    strike,
                    snapshot.get("price"),
                    entry,
                    entry,
                    side.get("stop_loss"),
                    side.get("target_1"),
                    side.get("target_2"),
                    confidence
                ))
                created += cur.rowcount
            conn.commit()

    return {"created": created, "evaluated": evaluated}


def _accuracy_summary():
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE status='CLOSED') AS completed,
                    COUNT(*) FILTER (WHERE result='WIN') AS wins,
                    COUNT(*) FILTER (WHERE result='LOSS') AS losses,
                    COUNT(*) FILTER (WHERE status='OPEN') AS open_signals,
                    COALESCE(SUM(CASE WHEN result='WIN' THEN pnl_points ELSE 0 END),0) AS gross_win_pts,
                    ABS(COALESCE(SUM(CASE WHEN result='LOSS' THEN pnl_points ELSE 0 END),0)) AS gross_loss_pts
                FROM prediction_audit
            """)
            overall = cur.fetchone()

            cur.execute("""
                SELECT option_type,
                       COUNT(*) FILTER (WHERE status='CLOSED'),
                       COUNT(*) FILTER (WHERE result='WIN')
                FROM prediction_audit
                GROUP BY option_type
            """)
            side_rows = cur.fetchall()

            cur.execute("""
                SELECT
                  CASE
                    WHEN confidence >= 80 THEN '80%+'
                    WHEN confidence >= 70 THEN '70-79%'
                    WHEN confidence >= 60 THEN '60-69%'
                    ELSE '<60%'
                  END AS bucket,
                  COUNT(*) FILTER (WHERE status='CLOSED') AS completed,
                  COUNT(*) FILTER (WHERE result='WIN') AS wins
                FROM prediction_audit
                GROUP BY 1
                ORDER BY 1
            """)
            buckets = cur.fetchall()

    completed = int(overall[0] or 0)
    wins = int(overall[1] or 0)
    losses = int(overall[2] or 0)
    open_signals = int(overall[3] or 0)
    gross_win = float(overall[4] or 0)
    gross_loss = float(overall[5] or 0)

    by_side = {}
    for typ, total, side_wins in side_rows:
        total = int(total or 0)
        side_wins = int(side_wins or 0)
        by_side[typ] = {
            "completed": total,
            "wins": side_wins,
            "accuracy": round(side_wins / total * 100, 1) if total else 0.0
        }

    confidence_buckets = []
    for bucket, total, bwins in buckets:
        total = int(total or 0)
        bwins = int(bwins or 0)
        confidence_buckets.append({
            "bucket": bucket,
            "completed": total,
            "wins": bwins,
            "accuracy": round(bwins / total * 100, 1) if total else 0.0
        })

    return {
        "completed": completed,
        "wins": wins,
        "losses": losses,
        "open_signals": open_signals,
        "accuracy": round(wins / completed * 100, 1) if completed else 0.0,
        "profit_factor_points": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
        "ce_accuracy": by_side.get("CE", {}).get("accuracy", 0.0),
        "pe_accuracy": by_side.get("PE", {}).get("accuracy", 0.0),
        "by_side": by_side,
        "confidence_buckets": confidence_buckets,
        "note": "Accuracy is measured only on completed BUY signals: Target 1 observed first = WIN; stop observed first = LOSS."
    }


def setup_auth_whatsapp(app, fno_alert_provider=None):
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
            or path.startswith("/api/whatsapp")
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
                        whatsapp_enabled,
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
                "whatsapp_enabled":row[3],
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
                    SET whatsapp_enabled=%s
                    WHERE user_id=%s
                """, (
                    payload.whatsapp_enabled,
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
                        whatsapp_status,
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
                    "whatsapp_status":r[9],
                    "sent_at":r[10].isoformat() if r[10] else None
                }
                for r in rows
            ]
        }

    @app.post("/api/whatsapp/test")
    def test_whatsapp(request: Request):
        try:
            user = _current_user(request)

            sid = _send_whatsapp(
                user["mobile_number"],
                "NIFTY AI test alert: WhatsApp notifications are connected successfully."
            )

            return {
                "status":"success",
                "message_sid":sid
            }
        except Exception as e:
            return JSONResponse(
                {"status":"error","message":str(e)},
                status_code=400
            )

    @app.post("/api/whatsapp/evaluate")
    def evaluate_and_send(request: Request):
        if fno_alert_provider is None:
            return JSONResponse(
                {
                    "status":"error",
                    "message":"F&O alert provider is not connected."
                },
                status_code=500
            )

        try:
            user = _current_user(request)

            with _db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT
                            alert_type,
                            min_confidence
                        FROM fo_alert_settings
                        WHERE user_id=%s
                          AND is_active=TRUE
                        ORDER BY alert_id DESC
                        LIMIT 1
                    """, (user["user_id"],))
                    setting = cur.fetchone()

                    cur.execute("""
                        SELECT whatsapp_enabled
                        FROM app_users
                        WHERE user_id=%s
                    """, (user["user_id"],))
                    wa_row = cur.fetchone()

            if not setting:
                return {
                    "status":"wait",
                    "message":"No active alert settings."
                }

            if not wa_row or not wa_row[0]:
                return {
                    "status":"wait",
                    "message":"WhatsApp alerts are disabled."
                }

            result = fno_alert_provider()

            if (
                not isinstance(result, dict)
                or result.get("status") != "success"
            ):
                return {
                    "status":"wait",
                    "message":"F&O snapshot unavailable.",
                    "snapshot":result
                }

            alerts = (
                result.get("alerts")
                or result.get("fno_alerts")
                or {}
            )

            picked = _pick_trade(alerts)

            if not picked:
                return {
                    "status":"wait",
                    "message":"No BUY CE/PE signal right now."
                }

            option_type, item = picked
            configured_type = setting[0]
            min_confidence = float(setting[1])

            if (
                configured_type != "BOTH"
                and configured_type != option_type
            ):
                return {
                    "status":"wait",
                    "message":f"{option_type} signal ignored by user setting."
                }

            try:
                confidence = float(
                    item.get("signal_strength")
                    or item.get("confidence")
                    or result.get("confidence")
                    or 0
                )
            except Exception:
                confidence = 0.0

            if confidence <= 1:
                confidence *= 100

            if confidence < min_confidence:
                return {
                    "status":"wait",
                    "message":(
                        f"Signal confidence {confidence:.1f}% "
                        f"is below {min_confidence:.1f}%."
                    )
                }

            nifty_price = result.get("price")
            signal_key = _signal_key(
                option_type,
                item,
                nifty_price
            )

            if _already_sent(
                user["user_id"],
                signal_key
            ):
                return {
                    "status":"duplicate",
                    "message":"Same signal was already sent recently."
                }

            strike = (
                item.get("strike")
                or item.get("strike_price")
            )
            entry = (
                item.get("entry")
                or item.get("entry_price")
                or item.get("entry_zone")
            )
            stop = (
                item.get("stop_loss")
                or item.get("stop")
            )
            target1 = (
                item.get("target1")
                or item.get("target_1")
            )
            target2 = (
                item.get("target2")
                or item.get("target_2")
            )

            signal = str(
                item.get("signal")
                or f"BUY {option_type}"
            ).upper()

            text = (
                "NIFTY AI F&O ALERT\n"
                f"Signal: {signal}\n"
                f"NIFTY: {nifty_price}\n"
                f"Strike: {strike} {option_type}\n"
                f"Entry: {entry}\n"
                f"Stop Loss: {stop}\n"
                f"Target 1: {target1}\n"
                f"Target 2: {target2}\n"
                f"Confidence: {confidence:.1f}%\n"
                f"Time: {datetime.now().strftime('%d-%b-%Y %H:%M:%S')}"
            )

            sid = _send_whatsapp(
                user["mobile_number"],
                text
            )

            with _db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO fo_alert_history(
                            user_id,
                            signal,
                            nifty_price,
                            strike_price,
                            option_type,
                            entry_price,
                            stop_loss,
                            target1,
                            target2,
                            confidence,
                            whatsapp_status,
                            message_sid,
                            signal_key
                        )
                        VALUES(
                            %s,%s,%s,%s,%s,%s,%s,
                            %s,%s,%s,%s,%s,%s
                        )
                    """, (
                        user["user_id"],
                        signal,
                        _num(nifty_price),
                        _num(strike),
                        option_type,
                        _num(entry),
                        _num(stop),
                        _num(target1),
                        _num(target2),
                        confidence,
                        "SENT",
                        sid,
                        signal_key
                    ))
                conn.commit()

            return {
                "status":"sent",
                "signal":signal,
                "option_type":option_type,
                "confidence":round(confidence,1),
                "message_sid":sid
            }

        except Exception as e:
            return JSONResponse(
                {"status":"error","message":str(e)},
                status_code=400
            )

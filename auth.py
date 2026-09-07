import hashlib
import json
import math
import os
import secrets
from datetime import datetime, timezone

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
    "/", "/login", "/register",
    "/auth/register", "/auth/login", "/auth/logout",
    "/health", "/docs", "/openapi.json", "/redoc"
}


class RegisterPayload(BaseModel):
    mobile_number: str
    password: str
    confirm_password: str


class LoginPayload(BaseModel):
    mobile_number: str
    password: str


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
            cur.execute(
                "ALTER TABLE app_users "
                "ADD COLUMN IF NOT EXISTS password_hash TEXT"
            )

            cur.execute("""
                CREATE TABLE IF NOT EXISTS paper_accounts (
                    user_id BIGINT PRIMARY KEY
                        REFERENCES app_users(user_id) ON DELETE CASCADE,
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
                    user_id BIGINT NOT NULL
                        REFERENCES app_users(user_id) ON DELETE CASCADE,
                    signal VARCHAR(30) NOT NULL,
                    option_type VARCHAR(5) NOT NULL,
                    strike_price NUMERIC(12,2) NOT NULL,
                    nifty_price NUMERIC(12,2),
                    entry_price NUMERIC(12,2) NOT NULL,
                    current_price NUMERIC(12,2),
                    exit_price NUMERIC(12,2),
                    stop_loss NUMERIC(12,2),
                    target1 NUMERIC(12,2),
                    target2 NUMERIC(12,2),
                    confidence NUMERIC(5,2),
                    quantity INTEGER NOT NULL DEFAULT 75,
                    status VARCHAR(12) NOT NULL DEFAULT 'OPEN',
                    pnl NUMERIC(14,2) NOT NULL DEFAULT 0,
                    exit_reason VARCHAR(40),
                    expiry VARCHAR(30),
                    last_price_at TIMESTAMPTZ,
                    opened_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    closed_at TIMESTAMPTZ
                )
            """)
            cur.execute(
                "ALTER TABLE paper_trades "
                "ADD COLUMN IF NOT EXISTS expiry VARCHAR(30)"
            )
            cur.execute(
                "ALTER TABLE paper_trades "
                "ADD COLUMN IF NOT EXISTS last_price_at TIMESTAMPTZ"
            )

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
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt.encode(),
        250000
    ).hex()
    return f"{salt}${digest}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, expected = stored.split("$", 1)
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(),
            salt.encode(),
            250000
        ).hex()
        return secrets.compare_digest(actual, expected)
    except Exception:
        return False


def _create_token(user_id: int, mobile: str) -> str:
    if not JWT_SECRET or len(JWT_SECRET) < 24:
        raise RuntimeError(
            "JWT_SECRET must be configured with at least 24 characters."
        )

    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "mobile": mobile,
        "iat": int(now.timestamp()),
        "exp": int(now.timestamp()) + SESSION_DAYS * 86400
    }
    return jwt.encode(
        payload,
        JWT_SECRET,
        algorithm=JWT_ALGORITHM
    )


def _current_user(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None

    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM]
        )
        return {
            "user_id": int(payload["sub"]),
            "mobile_number": payload.get("mobile")
        }
    except Exception:
        return None


def _ensure_paper_account(user_id: int):
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO paper_accounts(user_id) VALUES(%s) "
                "ON CONFLICT(user_id) DO NOTHING",
                (user_id,)
            )
        conn.commit()


def _login_page():
    return """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NIFTY AI Login</title>
<style>
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:grid;place-items:center;
background:#07111f;color:#eef5ff;font-family:Inter,system-ui,sans-serif}
.card{width:min(430px,92vw);background:#0d1a2b;border:1px solid #22334c;
border-radius:22px;padding:28px;box-shadow:0 24px 80px rgba(0,0,0,.35)}
.logo{width:50px;height:50px;display:grid;place-items:center;border-radius:14px;
background:#eef5ff;color:#08111e;font-weight:900}
h1{margin:18px 0 6px}.sub,.status,.small{color:#91a3bb;line-height:1.5}
label{display:block;margin:15px 0 7px;color:#b9c8db;font-size:13px}
input{width:100%;padding:14px;border:1px solid #2c405d;border-radius:12px;
background:#081423;color:white;font-size:16px}
button{width:100%;margin-top:18px;padding:14px;border:0;border-radius:12px;
background:#eef5ff;color:#08111e;font-size:15px;font-weight:800}
.status{min-height:20px;margin-top:12px;font-size:13px}
.small{font-size:12px;margin-top:18px}a{color:#b8d0ff}
.tabs{display:flex;gap:8px;margin-top:18px}
.tabs button{margin:0;background:#102037;color:#d9e5f5;border:1px solid #2c405d}
.tabs button.active{background:#eef5ff;color:#08111e}
</style>
</head>
<body>
<div class="card">
<div class="logo">N</div>
<h1>NIFTY AI</h1>
<div class="sub">Login with your mobile number and password.</div>

<div class="tabs">
  <button id="loginTab" class="active" onclick="setMode('login')">Login</button>
  <button id="registerTab" onclick="setMode('register')">Create Account</button>
</div>

<label>Mobile number</label>
<input id="mobile" inputmode="tel" placeholder="+91 98765 43210">

<label>Password</label>
<input id="password" type="password" placeholder="Password">

<div id="confirmWrap" style="display:none">
<label>Confirm password</label>
<input id="confirm" type="password" placeholder="Confirm password">
</div>

<button id="submitBtn" onclick="submitForm()">Login</button>
<div class="status" id="status"></div>
</div>

<script>
let mode="login";
function setMode(v){
  mode=v;
  document.getElementById("confirmWrap").style.display=v==="register"?"block":"none";
  document.getElementById("submitBtn").textContent=v==="register"?"Create Account":"Login";
  document.getElementById("loginTab").classList.toggle("active",v==="login");
  document.getElementById("registerTab").classList.toggle("active",v==="register");
  document.getElementById("status").textContent="";
}
async function submitForm(){
  const payload={
    mobile_number:document.getElementById("mobile").value.trim(),
    password:document.getElementById("password").value
  };
  if(mode==="register"){
    payload.confirm_password=document.getElementById("confirm").value;
  }
  const r=await fetch("/auth/"+mode,{
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify(payload)
  });
  const d=await r.json();
  document.getElementById("status").textContent=d.message||d.detail||"";
  if(r.ok)location.href="/dashboard";
}
</script>
</body>
</html>
"""


def _exact_contract_price(snapshot, option_type, strike_price, expiry=None):
    if not isinstance(snapshot, dict):
        return None

    chain = (
        snapshot.get("option_chain")
        or (snapshot.get("signals") or {}).get("option_chain")
        or {}
    )

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
    if not isinstance(snapshot, dict) or snapshot.get("status") != "success":
        return {"created": 0, "evaluated": 0}

    signals = snapshot.get("signals") or {}
    chain = snapshot.get("option_chain") or signals.get("option_chain") or {}
    expiry = chain.get("expiry")

    alerts = snapshot.get("alerts") or snapshot.get("fno_alerts") or {}
    created = 0
    evaluated = 0

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT audit_id, option_type, strike_price, expiry,
                       entry_price, stop_loss, target1, target2
                FROM prediction_audit
                WHERE status='OPEN'
                ORDER BY audit_id
            """)
            open_rows = cur.fetchall()

            for row in open_rows:
                audit_id, typ, strike, saved_expiry, entry, stop, t1, t2 = row
                live = _exact_contract_price(
                    snapshot,
                    typ,
                    strike,
                    saved_expiry
                )
                if live is None:
                    continue

                pnl_points = float(live) - float(entry)
                status = "OPEN"
                result = None
                closed = False

                if stop is not None and live <= float(stop):
                    status, result, closed = "CLOSED", "LOSS", True
                elif t1 is not None and live >= float(t1):
                    status, result, closed = "CLOSED", "WIN", True

                cur.execute("""
                    UPDATE prediction_audit
                    SET current_price=%s,
                        pnl_points=%s,
                        status=%s,
                        result=%s,
                        last_checked_at=CURRENT_TIMESTAMP,
                        closed_at=CASE
                            WHEN %s THEN CURRENT_TIMESTAMP
                            ELSE closed_at
                        END
                    WHERE audit_id=%s
                """, (
                    live,
                    pnl_points,
                    status,
                    result,
                    closed,
                    audit_id
                ))
                evaluated += 1

        conn.commit()

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
            confidence = (
                float(confidence)
                if confidence is not None
                else None
            )
        except Exception:
            confidence = None

        now = datetime.now()
        signal_key = (
            f"{typ}|{expiry}|{strike:.2f}|"
            f"{now.strftime('%Y%m%d%H')}|{now.minute // 15}"
        )

        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO prediction_audit(
                        signal_key,
                        model_version,
                        prediction,
                        option_type,
                        expiry,
                        strike_price,
                        nifty_price,
                        entry_price,
                        current_price,
                        stop_loss,
                        target1,
                        target2,
                        confidence,
                        status,
                        generated_at,
                        last_checked_at
                    )
                    VALUES(
                        %s,%s,%s,%s,%s,%s,%s,%s,%s,
                        %s,%s,%s,%s,'OPEN',
                        CURRENT_TIMESTAMP,CURRENT_TIMESTAMP
                    )
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
                    COUNT(*) FILTER (WHERE status='CLOSED'),
                    COUNT(*) FILTER (WHERE result='WIN'),
                    COUNT(*) FILTER (WHERE result='LOSS'),
                    COUNT(*) FILTER (WHERE status='OPEN'),
                    COALESCE(
                        SUM(CASE WHEN result='WIN' THEN pnl_points ELSE 0 END),
                        0
                    ),
                    ABS(
                        COALESCE(
                            SUM(CASE WHEN result='LOSS' THEN pnl_points ELSE 0 END),
                            0
                        )
                    )
                FROM prediction_audit
            """)
            overall = cur.fetchone()

            cur.execute("""
                SELECT
                    option_type,
                    COUNT(*) FILTER (WHERE status='CLOSED'),
                    COUNT(*) FILTER (WHERE result='WIN')
                FROM prediction_audit
                GROUP BY option_type
            """)
            side_rows = cur.fetchall()

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
        by_side[typ] = (
            round(side_wins / total * 100, 1)
            if total
            else 0.0
        )

    return {
        "completed": completed,
        "wins": wins,
        "losses": losses,
        "open_signals": open_signals,
        "accuracy": (
            round(wins / completed * 100, 1)
            if completed
            else 0.0
        ),
        "ce_accuracy": by_side.get("CE", 0.0),
        "pe_accuracy": by_side.get("PE", 0.0),
        "profit_factor_points": (
            round(gross_win / gross_loss, 2)
            if gross_loss > 0
            else None
        )
    }


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

        protected = (
            path == "/dashboard"
            or path.startswith("/api/account")
            or path.startswith("/api/paper")
            or path.startswith("/api/accuracy")
        )

        if protected and not _current_user(request):
            if path == "/dashboard":
                return RedirectResponse("/login", status_code=303)

            return JSONResponse(
                {"status": "error", "message": "Authentication required."},
                status_code=401
            )

        return await call_next(request)

    @app.get("/login", response_class=HTMLResponse, include_in_schema=False)
    def login_page(request: Request):
        if _current_user(request):
            return RedirectResponse("/dashboard", status_code=303)
        return _login_page()

    @app.get("/register", response_class=HTMLResponse, include_in_schema=False)
    def register_page(request: Request):
        if _current_user(request):
            return RedirectResponse("/dashboard", status_code=303)
        return _login_page()

    @app.post("/auth/register")
    def register(payload: RegisterPayload):
        try:
            mobile = _normalize_mobile(payload.mobile_number)

            if payload.password != payload.confirm_password:
                return JSONResponse(
                    {"status": "error", "message": "Passwords do not match."},
                    status_code=400
                )

            password_hash = _hash_password(payload.password)

            with _db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT user_id,password_hash "
                        "FROM app_users WHERE mobile_number=%s",
                        (mobile,)
                    )
                    row = cur.fetchone()

                    if row and row[1]:
                        return JSONResponse(
                            {
                                "status": "error",
                                "message": "Account already exists. Please login."
                            },
                            status_code=409
                        )

                    if row:
                        cur.execute("""
                            UPDATE app_users
                            SET password_hash=%s,
                                last_login=CURRENT_TIMESTAMP
                            WHERE user_id=%s
                            RETURNING user_id
                        """, (password_hash, row[0]))
                    else:
                        cur.execute("""
                            INSERT INTO app_users(
                                mobile_number,
                                password_hash,
                                last_login
                            )
                            VALUES(%s,%s,CURRENT_TIMESTAMP)
                            RETURNING user_id
                        """, (mobile, password_hash))

                    user_id = cur.fetchone()[0]

                conn.commit()

            _ensure_paper_account(user_id)

            response = JSONResponse({
                "status": "success",
                "message": "Account created."
            })
            response.set_cookie(
                SESSION_COOKIE,
                _create_token(user_id, mobile),
                max_age=SESSION_DAYS * 86400,
                httponly=True,
                secure=True,
                samesite="lax",
                path="/"
            )
            return response

        except Exception as e:
            return JSONResponse(
                {"status": "error", "message": str(e)},
                status_code=400
            )

    @app.post("/auth/login")
    def password_login(payload: LoginPayload):
        try:
            mobile = _normalize_mobile(payload.mobile_number)

            with _db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT user_id,password_hash "
                        "FROM app_users WHERE mobile_number=%s",
                        (mobile,)
                    )
                    row = cur.fetchone()

                    if (
                        not row
                        or not row[1]
                        or not _verify_password(payload.password, row[1])
                    ):
                        return JSONResponse(
                            {
                                "status": "error",
                                "message": "Invalid mobile number or password."
                            },
                            status_code=401
                        )

                    user_id = row[0]
                    cur.execute(
                        "UPDATE app_users "
                        "SET last_login=CURRENT_TIMESTAMP "
                        "WHERE user_id=%s",
                        (user_id,)
                    )

                conn.commit()

            _ensure_paper_account(user_id)

            response = JSONResponse({
                "status": "success",
                "message": "Login successful."
            })
            response.set_cookie(
                SESSION_COOKIE,
                _create_token(user_id, mobile),
                max_age=SESSION_DAYS * 86400,
                httponly=True,
                secure=True,
                samesite="lax",
                path="/"
            )
            return response

        except Exception as e:
            return JSONResponse(
                {"status": "error", "message": str(e)},
                status_code=400
            )

    @app.post("/auth/logout")
    def logout():
        response = JSONResponse({"status": "success"})
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    @app.get("/api/account/me")
    def me(request: Request):
        user = _current_user(request)
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT user_id,mobile_number,last_login
                    FROM app_users
                    WHERE user_id=%s
                """, (user["user_id"],))
                row = cur.fetchone()

        if not row:
            return JSONResponse(
                {"status": "error", "message": "User not found."},
                status_code=404
            )

        return {
            "status": "success",
            "user": {
                "user_id": row[0],
                "mobile_number": row[1],
                "last_login": (
                    row[2].isoformat()
                    if row[2]
                    else None
                )
            }
        }

    @app.get("/api/paper/summary")
    def paper_summary(request: Request):
        user = _current_user(request)
        _ensure_paper_account(user["user_id"])

        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        starting_balance,
                        cash_balance,
                        auto_trade,
                        quantity,
                        min_confidence
                    FROM paper_accounts
                    WHERE user_id=%s
                """, (user["user_id"],))
                account = cur.fetchone()

                cur.execute("""
                    SELECT
                        COALESCE(
                            SUM(CASE WHEN status='OPEN' THEN pnl ELSE 0 END),
                            0
                        ),
                        COALESCE(
                            SUM(CASE WHEN status='CLOSED' THEN pnl ELSE 0 END),
                            0
                        ),
                        COUNT(*) FILTER (WHERE status='OPEN'),
                        COUNT(*) FILTER (WHERE status='CLOSED'),
                        COUNT(*) FILTER (
                            WHERE status='CLOSED' AND pnl>0
                        )
                    FROM paper_trades
                    WHERE user_id=%s
                """, (user["user_id"],))
                stats = cur.fetchone()

        closed = int(stats[3] or 0)
        wins = int(stats[4] or 0)

        return {
            "status": "success",
            "summary": {
                "starting_balance": float(account[0]),
                "cash_balance": float(account[1]),
                "equity": float(account[1]) + float(stats[0]),
                "open_pnl": float(stats[0]),
                "realized_pnl": float(stats[1]),
                "open_positions": int(stats[2] or 0),
                "win_rate": (
                    round(wins / closed * 100, 1)
                    if closed
                    else 0.0
                ),
                "auto_trade": account[2],
                "quantity": account[3],
                "min_confidence": float(account[4])
            }
        }

    @app.get("/api/paper/history")
    def paper_history(request: Request):
        user = _current_user(request)

        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        trade_id,signal,option_type,strike_price,
                        entry_price,current_price,exit_price,quantity,
                        status,pnl,exit_reason,opened_at,expiry,last_price_at
                    FROM paper_trades
                    WHERE user_id=%s
                    ORDER BY trade_id DESC
                    LIMIT 50
                """, (user["user_id"],))
                rows = cur.fetchall()

        return {
            "status": "success",
            "trades": [
                {
                    "trade_id": r[0],
                    "signal": r[1],
                    "option_type": r[2],
                    "strike_price": float(r[3]),
                    "entry_price": float(r[4]),
                    "current_price": (
                        float(r[5])
                        if r[5] is not None
                        else None
                    ),
                    "exit_price": (
                        float(r[6])
                        if r[6] is not None
                        else None
                    ),
                    "quantity": r[7],
                    "status": r[8],
                    "pnl": float(r[9]),
                    "exit_reason": r[10],
                    "opened_at": r[11].isoformat(),
                    "expiry": r[12],
                    "last_price_at": (
                        r[13].isoformat()
                        if r[13]
                        else None
                    )
                }
                for r in rows
            ]
        }

    @app.post("/api/paper/open")
    async def paper_open(request: Request):
        user = _current_user(request)
        data = await request.json()

        qty = max(1, int(data.get("quantity", 75)))
        entry = float(data["entry_price"])
        cost = entry * qty

        _ensure_paper_account(user["user_id"])

        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT cash_balance
                    FROM paper_accounts
                    WHERE user_id=%s
                    FOR UPDATE
                """, (user["user_id"],))
                cash = float(cur.fetchone()[0])

                if cost > cash:
                    return JSONResponse(
                        {
                            "status": "error",
                            "message": "Not enough paper balance."
                        },
                        status_code=400
                    )

                cur.execute("""
                    INSERT INTO paper_trades(
                        user_id,signal,option_type,strike_price,nifty_price,
                        entry_price,current_price,stop_loss,target1,target2,
                        confidence,quantity,expiry,last_price_at
                    )
                    VALUES(
                        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                        CURRENT_TIMESTAMP
                    )
                    RETURNING trade_id
                """, (
                    user["user_id"],
                    data.get("signal"),
                    data.get("option_type"),
                    data.get("strike_price"),
                    data.get("nifty_price"),
                    entry,
                    entry,
                    data.get("stop_loss"),
                    data.get("target1"),
                    data.get("target2"),
                    data.get("confidence"),
                    qty,
                    data.get("expiry")
                ))
                trade_id = cur.fetchone()[0]

                cur.execute("""
                    UPDATE paper_accounts
                    SET cash_balance=cash_balance-%s,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE user_id=%s
                """, (cost, user["user_id"]))

            conn.commit()

        return {
            "status": "success",
            "trade_id": trade_id
        }

    @app.post("/api/paper/close")
    async def paper_close(request: Request):
        user = _current_user(request)
        data = await request.json()

        trade_id = int(data["trade_id"])
        exit_price = float(data["exit_price"])

        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT entry_price,quantity,status
                    FROM paper_trades
                    WHERE trade_id=%s
                      AND user_id=%s
                    FOR UPDATE
                """, (trade_id, user["user_id"]))
                row = cur.fetchone()

                if not row or row[2] != "OPEN":
                    return JSONResponse(
                        {
                            "status": "error",
                            "message": "Open trade not found."
                        },
                        status_code=400
                    )

                pnl = (
                    exit_price - float(row[0])
                ) * int(row[1])
                proceeds = exit_price * int(row[1])

                cur.execute("""
                    UPDATE paper_trades
                    SET current_price=%s,
                        exit_price=%s,
                        pnl=%s,
                        status='CLOSED',
                        exit_reason='MANUAL',
                        closed_at=CURRENT_TIMESTAMP,
                        last_price_at=CURRENT_TIMESTAMP
                    WHERE trade_id=%s
                """, (
                    exit_price,
                    exit_price,
                    pnl,
                    trade_id
                ))

                cur.execute("""
                    UPDATE paper_accounts
                    SET cash_balance=cash_balance+%s,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE user_id=%s
                """, (
                    proceeds,
                    user["user_id"]
                ))

            conn.commit()

        return {
            "status": "success",
            "pnl": round(pnl, 2)
        }

    @app.post("/api/paper/sync")
    def paper_sync(request: Request):
        user = _current_user(request)

        if fno_alert_provider is None:
            return {
                "status": "success",
                "updated": 0,
                "message": "F&O provider unavailable."
            }

        try:
            snapshot = fno_alert_provider()

            if (
                not isinstance(snapshot, dict)
                or snapshot.get("status") != "success"
            ):
                return {
                    "status": "success",
                    "updated": 0,
                    "message": "Market snapshot unavailable."
                }

            audit_result = _record_and_evaluate_prediction(snapshot)
            updated = 0
            closed = 0

            with _db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT
                            trade_id,option_type,strike_price,
                            entry_price,quantity,stop_loss,
                            target1,target2,expiry
                        FROM paper_trades
                        WHERE user_id=%s
                          AND status='OPEN'
                        ORDER BY trade_id
                    """, (user["user_id"],))
                    rows = cur.fetchall()

                    for row in rows:
                        (
                            trade_id,
                            option_type,
                            strike,
                            entry,
                            qty,
                            stop,
                            target1,
                            target2,
                            expiry
                        ) = row

                        live = _exact_contract_price(
                            snapshot,
                            option_type,
                            strike,
                            expiry
                        )
                        if live is None:
                            continue

                        pnl = (
                            float(live) - float(entry)
                        ) * int(qty)

                        exit_reason = None
                        if stop is not None and live <= float(stop):
                            exit_reason = "STOP LOSS"
                        elif target2 is not None and live >= float(target2):
                            exit_reason = "TARGET 2"
                        elif target1 is not None and live >= float(target1):
                            exit_reason = "TARGET 1"

                        if exit_reason:
                            proceeds = float(live) * int(qty)

                            cur.execute("""
                                UPDATE paper_trades
                                SET current_price=%s,
                                    exit_price=%s,
                                    pnl=%s,
                                    status='CLOSED',
                                    exit_reason=%s,
                                    closed_at=CURRENT_TIMESTAMP,
                                    last_price_at=CURRENT_TIMESTAMP
                                WHERE trade_id=%s
                            """, (
                                live,
                                live,
                                pnl,
                                exit_reason,
                                trade_id
                            ))

                            cur.execute("""
                                UPDATE paper_accounts
                                SET cash_balance=cash_balance+%s,
                                    updated_at=CURRENT_TIMESTAMP
                                WHERE user_id=%s
                            """, (
                                proceeds,
                                user["user_id"]
                            ))
                            closed += 1

                        else:
                            cur.execute("""
                                UPDATE paper_trades
                                SET current_price=%s,
                                    pnl=%s,
                                    last_price_at=CURRENT_TIMESTAMP
                                WHERE trade_id=%s
                            """, (
                                live,
                                pnl,
                                trade_id
                            ))

                        updated += 1

                conn.commit()

            return {
                "status": "success",
                "updated": updated,
                "closed": closed,
                "audit_created": audit_result.get("created", 0),
                "audit_evaluated": audit_result.get("evaluated", 0)
            }

        except Exception as e:
            return {
                "status": "success",
                "updated": 0,
                "message": str(e)
            }

    @app.post("/api/paper/reset")
    def paper_reset(request: Request):
        user = _current_user(request)

        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM paper_trades WHERE user_id=%s",
                    (user["user_id"],)
                )
                cur.execute("""
                    UPDATE paper_accounts
                    SET cash_balance=starting_balance,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE user_id=%s
                """, (user["user_id"],))
            conn.commit()

        return {"status": "success"}

    @app.get("/api/accuracy/summary")
    def accuracy_summary(request: Request):
        try:
            if fno_alert_provider is not None:
                snapshot = fno_alert_provider()
                _record_and_evaluate_prediction(snapshot)

            return {
                "status": "success",
                "summary": _accuracy_summary()
            }
        except Exception as e:
            return JSONResponse(
                {"status": "error", "message": str(e)},
                status_code=400
            )

    @app.get("/api/accuracy/history")
    def accuracy_history(request: Request, limit: int = 30):
        limit = max(1, min(100, int(limit)))

        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        audit_id,prediction,option_type,expiry,
                        strike_price,entry_price,current_price,
                        stop_loss,target1,target2,confidence,
                        status,result,pnl_points,generated_at,closed_at
                    FROM prediction_audit
                    ORDER BY audit_id DESC
                    LIMIT %s
                """, (limit,))
                rows = cur.fetchall()

        return {
            "status": "success",
            "signals": [
                {
                    "audit_id": r[0],
                    "prediction": r[1],
                    "option_type": r[2],
                    "expiry": r[3],
                    "strike_price": float(r[4]),
                    "entry_price": float(r[5]),
                    "current_price": (
                        float(r[6])
                        if r[6] is not None
                        else None
                    ),
                    "stop_loss": (
                        float(r[7])
                        if r[7] is not None
                        else None
                    ),
                    "target1": (
                        float(r[8])
                        if r[8] is not None
                        else None
                    ),
                    "target2": (
                        float(r[9])
                        if r[9] is not None
                        else None
                    ),
                    "confidence": (
                        float(r[10])
                        if r[10] is not None
                        else None
                    ),
                    "status": r[11],
                    "result": r[12],
                    "pnl_points": float(r[13] or 0),
                    "generated_at": (
                        r[14].isoformat()
                        if r[14]
                        else None
                    ),
                    "closed_at": (
                        r[15].isoformat()
                        if r[15]
                        else None
                    )
                }
                for r in rows
            ]
        }

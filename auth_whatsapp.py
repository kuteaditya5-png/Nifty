import base64
import hashlib
import hmac
import json
import math
import os
import re
import time
from datetime import datetime
from typing import Optional

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel


DATABASE_URL = os.getenv("DATABASE_URL")
JWT_SECRET = os.getenv("JWT_SECRET", "")
SESSION_COOKIE = "nifty_ai_session"
SESSION_DAYS = 30

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_VERIFY_SERVICE_SID = os.getenv("TWILIO_VERIFY_SERVICE_SID")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM")
TWILIO_CONTENT_SID = os.getenv("TWILIO_CONTENT_SID")

PUBLIC_PATHS = {
    "/", "/login", "/auth/send-otp", "/auth/verify-otp",
    "/health", "/docs", "/openapi.json", "/redoc"
}


class PhonePayload(BaseModel):
    mobile_number: str


class VerifyPayload(BaseModel):
    mobile_number: str
    otp: str


class AlertSettingsPayload(BaseModel):
    alert_type: str = "BOTH"
    alert_time: Optional[str] = None
    min_confidence: float = 70.0
    whatsapp_enabled: bool = True


def _normalize_mobile(value: str) -> str:
    value = "".join(
        ch for ch in (value or "")
        if ch.isdigit() or ch == "+"
    )

    if not value:
        raise ValueError("Mobile number is required.")

    if value.startswith("+"):
        normalized = value
    elif len(value) == 10:
        normalized = "+91" + value
    elif value.startswith("91") and len(value) == 12:
        normalized = "+" + value
    else:
        raise ValueError(
            "Enter a valid mobile number, e.g. +919876543210."
        )

    digits = "".join(
        ch for ch in normalized
        if ch.isdigit()
    )

    if len(digits) < 10 or len(digits) > 15:
        raise ValueError("Invalid mobile number.")

    return "+" + digits


def _load_psycopg():
    try:
        import psycopg
        return psycopg
    except Exception as e:
        raise RuntimeError(
            "PostgreSQL driver could not load. "
            "Check psycopg[binary] in requirements.txt. "
            f"Original error: {e}"
        )


def _db():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not configured in Vercel Environment Variables."
        )

    psycopg = _load_psycopg()
    return psycopg.connect(
        DATABASE_URL,
        connect_timeout=8
    )


def _ensure_db():
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS app_users (
                    user_id BIGSERIAL PRIMARY KEY,
                    mobile_number VARCHAR(20) UNIQUE NOT NULL,
                    is_mobile_verified BOOLEAN NOT NULL DEFAULT FALSE,
                    whatsapp_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMPTZ
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS fo_alert_settings (
                    alert_id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL
                        REFERENCES app_users(user_id)
                        ON DELETE CASCADE,
                    alert_time TIME,
                    alert_type VARCHAR(10)
                        NOT NULL DEFAULT 'BOTH',
                    min_confidence NUMERIC(5,2)
                        NOT NULL DEFAULT 70,
                    is_active BOOLEAN
                        NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ
                        NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ
                        NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS
                uq_fo_alert_settings_user_active
                ON fo_alert_settings(user_id)
                WHERE is_active = TRUE
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS fo_alert_history (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT
                        REFERENCES app_users(user_id)
                        ON DELETE SET NULL,
                    signal VARCHAR(20),
                    nifty_price NUMERIC(12,2),
                    strike_price NUMERIC(12,2),
                    option_type VARCHAR(5),
                    entry_price NUMERIC(12,2),
                    stop_loss NUMERIC(12,2),
                    target1 NUMERIC(12,2),
                    target2 NUMERIC(12,2),
                    confidence NUMERIC(5,2),
                    whatsapp_status VARCHAR(40),
                    message_sid VARCHAR(80),
                    signal_key VARCHAR(160),
                    sent_at TIMESTAMPTZ
                        NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS
                ix_alert_history_user_sent
                ON fo_alert_history(
                    user_id,
                    sent_at DESC
                )
            """)

        conn.commit()


def _load_twilio():
    try:
        from twilio.rest import Client
        return Client
    except Exception as e:
        raise RuntimeError(
            "Twilio package could not load. "
            "Check twilio in requirements.txt. "
            f"Original error: {e}"
        )


def _twilio_client():
    if not TWILIO_ACCOUNT_SID:
        raise RuntimeError(
            "TWILIO_ACCOUNT_SID is not configured."
        )

    if not TWILIO_AUTH_TOKEN:
        raise RuntimeError(
            "TWILIO_AUTH_TOKEN is not configured."
        )

    Client = _load_twilio()

    return Client(
        TWILIO_ACCOUNT_SID,
        TWILIO_AUTH_TOKEN
    )


# ------------------------------------------------------------
# Small signed session token using Python standard library.
# This removes PyJWT as a startup dependency.
# ------------------------------------------------------------

def _b64encode(data: bytes) -> str:
    return (
        base64.urlsafe_b64encode(data)
        .decode("utf-8")
        .rstrip("=")
    )


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(
        value + padding
    )


def _create_token(
    user_id: int,
    mobile: str
) -> str:

    if not JWT_SECRET or len(JWT_SECRET) < 24:
        raise RuntimeError(
            "JWT_SECRET must be configured in Vercel "
            "with at least 24 characters."
        )

    payload = {
        "sub": int(user_id),
        "mobile": mobile,
        "exp": int(
            time.time()
            + SESSION_DAYS * 86400
        )
    }

    payload_part = _b64encode(
        json.dumps(
            payload,
            separators=(",", ":")
        ).encode("utf-8")
    )

    signature = hmac.new(
        JWT_SECRET.encode("utf-8"),
        payload_part.encode("utf-8"),
        hashlib.sha256
    ).digest()

    return (
        payload_part
        + "."
        + _b64encode(signature)
    )


def _decode_token(token: str):
    if not token or not JWT_SECRET:
        return None

    try:
        payload_part, signature_part = (
            token.split(".", 1)
        )

        expected = hmac.new(
            JWT_SECRET.encode("utf-8"),
            payload_part.encode("utf-8"),
            hashlib.sha256
        ).digest()

        supplied = _b64decode(
            signature_part
        )

        if not hmac.compare_digest(
            expected,
            supplied
        ):
            return None

        payload = json.loads(
            _b64decode(
                payload_part
            ).decode("utf-8")
        )

        if int(
            payload.get(
                "exp",
                0
            )
        ) < int(
            time.time()
        ):
            return None

        return payload

    except Exception:
        return None


def _current_user(
    request: Request
):
    payload = _decode_token(
        request.cookies.get(
            SESSION_COOKIE
        )
    )

    if not payload:
        return None

    try:
        return {
            "user_id": int(
                payload["sub"]
            ),
            "mobile_number": payload[
                "mobile"
            ],
        }
    except Exception:
        return None


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

body{
    margin:0;
    min-height:100vh;
    display:grid;
    place-items:center;
    padding:20px;
    font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif;
    background:
        radial-gradient(circle at 20% 0%,#16325a 0,transparent 38%),
        #06101d;
    color:#edf4ff
}

.card{
    width:min(94vw,430px);
    padding:30px;
    border:1px solid #253b58;
    border-radius:24px;
    background:rgba(11,25,43,.96);
    box-shadow:0 28px 90px rgba(0,0,0,.42)
}

.logo{
    width:48px;
    height:48px;
    display:grid;
    place-items:center;
    border-radius:14px;
    margin-bottom:18px;
    background:#ecf3ff;
    color:#081626;
    font-weight:900
}

.brand{
    font-size:30px;
    font-weight:850;
    letter-spacing:.3px
}

.sub{
    color:#95a9c2;
    margin:8px 0 25px;
    line-height:1.55
}

label{
    display:block;
    margin:14px 0 7px;
    color:#bdcce0;
    font-size:13px
}

input{
    width:100%;
    padding:14px 15px;
    border:1px solid #304968;
    border-radius:12px;
    outline:none;
    background:#071522;
    color:#fff;
    font-size:16px
}

input:focus{
    border-color:#72a4ff
}

button{
    width:100%;
    padding:14px 16px;
    margin-top:16px;
    border:0;
    border-radius:12px;
    cursor:pointer;
    font-size:15px;
    font-weight:800;
    background:#eff5ff;
    color:#071523
}

button.secondary{
    border:1px solid #304968;
    background:#13253b;
    color:#dce8f8
}

.hidden{
    display:none
}

.status{
    min-height:22px;
    margin-top:13px;
    font-size:13px;
    color:#a7bad1
}

.footer{
    margin-top:18px;
    font-size:12px;
    line-height:1.5;
    color:#7188a5
}
</style>
</head>

<body>

<div class="card">

    <div class="logo">N</div>

    <div class="brand">
        NIFTY AI
    </div>

    <div class="sub">
        Sign in with your mobile number.
        Your verified number is also used
        for enabled WhatsApp F&O alerts.
    </div>

    <div id="phoneBox">

        <label>
            Mobile number
        </label>

        <input
            id="mobile"
            inputmode="tel"
            placeholder="+91 98765 43210"
            autocomplete="tel"
        >

        <button onclick="sendOtp()">
            Send OTP
        </button>

    </div>

    <div
        id="otpBox"
        class="hidden"
    >

        <label>
            Enter OTP
        </label>

        <input
            id="otp"
            inputmode="numeric"
            maxlength="10"
            placeholder="OTP"
            autocomplete="one-time-code"
        >

        <button onclick="verifyOtp()">
            Verify & Login
        </button>

        <button
            class="secondary"
            onclick="changeNumber()"
        >
            Change number
        </button>

    </div>

    <div
        id="status"
        class="status"
    ></div>

    <div class="footer">
        Login verification is handled
        securely by the server.
    </div>

</div>

<script>

let selectedMobile = "";

const statusElement =
    document.getElementById(
        "status"
    );


function setStatus(
    message
){
    statusElement.textContent =
        message || "";
}


async function sendOtp(){

    const mobile =
        document.getElementById(
            "mobile"
        ).value.trim();

    if(!mobile){
        setStatus(
            "Enter your mobile number."
        );
        return;
    }

    setStatus(
        "Sending OTP..."
    );

    try{

        const response =
            await fetch(
                "/auth/send-otp",
                {
                    method:"POST",
                    headers:{
                        "Content-Type":
                            "application/json"
                    },
                    body:JSON.stringify({
                        mobile_number:mobile
                    })
                }
            );

        const data =
            await response.json();

        if(!response.ok){

            setStatus(
                data.message
                || data.detail
                || "Unable to send OTP."
            );

            return;
        }

        selectedMobile =
            data.mobile_number;

        document.getElementById(
            "phoneBox"
        ).classList.add(
            "hidden"
        );

        document.getElementById(
            "otpBox"
        ).classList.remove(
            "hidden"
        );

        setStatus(
            "OTP sent to "
            + selectedMobile
        );

    }
    catch(error){

        setStatus(
            "Connection error: "
            + error.message
        );

    }
}


async function verifyOtp(){

    const otp =
        document.getElementById(
            "otp"
        ).value.trim();

    if(!otp){

        setStatus(
            "Enter the OTP."
        );

        return;
    }

    setStatus(
        "Verifying OTP..."
    );

    try{

        const response =
            await fetch(
                "/auth/verify-otp",
                {
                    method:"POST",
                    headers:{
                        "Content-Type":
                            "application/json"
                    },
                    body:JSON.stringify({
                        mobile_number:
                            selectedMobile,
                        otp:otp
                    })
                }
            );

        const data =
            await response.json();

        if(!response.ok){

            setStatus(
                data.message
                || data.detail
                || "OTP verification failed."
            );

            return;
        }

        window.location.href =
            "/dashboard";

    }
    catch(error){

        setStatus(
            "Connection error: "
            + error.message
        );

    }
}


function changeNumber(){

    selectedMobile = "";

    document.getElementById(
        "phoneBox"
    ).classList.remove(
        "hidden"
    );

    document.getElementById(
        "otpBox"
    ).classList.add(
        "hidden"
    );

    setStatus("");

}

</script>

</body>
</html>
"""


def _pick_trade(alerts):
    if not isinstance(
        alerts,
        dict
    ):
        return None

    candidates = []

    for key, option_type in (
        ("call", "CE"),
        ("put", "PE")
    ):

        item = (
            alerts.get(key)
            or {}
        )

        signal = str(
            item.get(
                "signal"
            )
            or "WAIT"
        ).upper()

        try:
            strength = float(
                item.get(
                    "signal_strength"
                )
                or item.get(
                    "confidence"
                )
                or 0
            )
        except Exception:
            strength = 0.0

        if "BUY" in signal:

            candidates.append(
                (
                    strength,
                    option_type,
                    item
                )
            )

    if not candidates:
        return None

    candidates.sort(
        key=lambda x: x[0],
        reverse=True
    )

    return (
        candidates[0][1],
        candidates[0][2]
    )


def _signal_key(
    option_type,
    item,
    nifty_price
):

    strike = (
        item.get("strike")
        or item.get(
            "strike_price"
        )
    )

    signal = str(
        item.get("signal")
        or "WAIT"
    ).upper()

    try:
        rounded_nifty = round(
            float(
                nifty_price
                or 0
            ),
            -1
        )
    except Exception:
        rounded_nifty = 0

    return (
        f"{option_type}|"
        f"{strike}|"
        f"{signal}|"
        f"{rounded_nifty}"
    )


def _already_sent(
    user_id: int,
    signal_key: str,
    minutes: int = 45
):

    with _db() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT 1
                FROM fo_alert_history
                WHERE user_id=%s
                  AND signal_key=%s
                  AND sent_at
                    >= CURRENT_TIMESTAMP
                    - (%s * INTERVAL '1 minute')
                LIMIT 1
                """,
                (
                    user_id,
                    signal_key,
                    minutes
                )
            )

            return (
                cur.fetchone()
                is not None
            )


def _send_whatsapp(
    to_mobile: str,
    text: str
):

    if not TWILIO_WHATSAPP_FROM:

        raise RuntimeError(
            "TWILIO_WHATSAPP_FROM "
            "is not configured."
        )

    client = _twilio_client()

    kwargs = {
        "from_":
            TWILIO_WHATSAPP_FROM,
        "to":
            "whatsapp:"
            + to_mobile,
    }

    if TWILIO_CONTENT_SID:

        kwargs[
            "content_sid"
        ] = TWILIO_CONTENT_SID

        kwargs[
            "content_variables"
        ] = json.dumps(
            {
                "1": text
            },
            ensure_ascii=False
        )

    else:

        kwargs[
            "body"
        ] = text

    message = (
        client.messages.create(
            **kwargs
        )
    )

    return message.sid


def _num(value):

    try:

        if (
            isinstance(
                value,
                (
                    int,
                    float
                )
            )
            and math.isfinite(
                float(value)
            )
        ):
            return float(value)

        if value is None:
            return None

        match = re.search(
            r"-?\d+(?:\.\d+)?",
            str(value).replace(
                ",",
                ""
            )
        )

        return (
            float(
                match.group()
            )
            if match
            else None
        )

    except Exception:
        return None


def setup_auth_whatsapp(
    app,
    fno_alert_provider=None
):

    @app.middleware("http")
    async def nifty_auth_middleware(
        request: Request,
        call_next
    ):

        path = (
            request.url.path
        )

        if (
            path
            in PUBLIC_PATHS
            or path.startswith(
                "/static/"
            )
            or path.startswith(
                "/auth/"
            )
        ):
            return await call_next(
                request
            )

        if (
            path == "/dashboard"
            or path.startswith(
                "/api/account"
            )
            or path.startswith(
                "/api/whatsapp"
            )
        ):

            if not _current_user(
                request
            ):

                if (
                    path
                    == "/dashboard"
                ):
                    return RedirectResponse(
                        "/login",
                        status_code=303
                    )

                return JSONResponse(
                    {
                        "status":
                            "error",
                        "message":
                            "Authentication required."
                    },
                    status_code=401
                )

        return await call_next(
            request
        )


    @app.get(
        "/login",
        response_class=HTMLResponse,
        include_in_schema=False
    )
    def login_page(
        request: Request
    ):

        if _current_user(
            request
        ):
            return RedirectResponse(
                "/dashboard",
                status_code=303
            )

        return HTMLResponse(
            _login_page()
        )


    @app.get(
        "/auth/status"
    )
    def auth_status():

        return {
            "status":"success",
            "database_configured":
                bool(DATABASE_URL),
            "jwt_secret_configured":
                bool(
                    JWT_SECRET
                    and len(
                        JWT_SECRET
                    ) >= 24
                ),
            "twilio_account_configured":
                bool(
                    TWILIO_ACCOUNT_SID
                    and TWILIO_AUTH_TOKEN
                ),
            "verify_service_configured":
                bool(
                    TWILIO_VERIFY_SERVICE_SID
                ),
            "whatsapp_from_configured":
                bool(
                    TWILIO_WHATSAPP_FROM
                )
        }


    @app.post(
        "/auth/send-otp"
    )
    def send_otp(
        payload: PhonePayload
    ):

        try:

            mobile = (
                _normalize_mobile(
                    payload.mobile_number
                )
            )

            if not TWILIO_VERIFY_SERVICE_SID:

                return JSONResponse(
                    {
                        "status":
                            "error",
                        "message":
                            "TWILIO_VERIFY_SERVICE_SID "
                            "is not configured."
                    },
                    status_code=500
                )

            client = (
                _twilio_client()
            )

            verification = (
                client
                .verify
                .v2
                .services(
                    TWILIO_VERIFY_SERVICE_SID
                )
                .verifications
                .create(
                    to=mobile,
                    channel="sms"
                )
            )

            return {
                "status":
                    verification.status,
                "mobile_number":
                    mobile,
                "message":
                    "OTP sent."
            }

        except Exception as e:

            return JSONResponse(
                {
                    "status":"error",
                    "message":str(e)
                },
                status_code=400
            )


    @app.post(
        "/auth/verify-otp"
    )
    def verify_otp(
        payload: VerifyPayload
    ):

        try:

            mobile = (
                _normalize_mobile(
                    payload.mobile_number
                )
            )

            client = (
                _twilio_client()
            )

            check = (
                client
                .verify
                .v2
                .services(
                    TWILIO_VERIFY_SERVICE_SID
                )
                .verification_checks
                .create(
                    to=mobile,
                    code=payload.otp
                )
            )

            if (
                check.status
                != "approved"
            ):

                return JSONResponse(
                    {
                        "status":
                            "error",
                        "message":
                            "Invalid or expired OTP."
                    },
                    status_code=401
                )

            # Create DB only when verification succeeds.
            _ensure_db()

            with _db() as conn:

                with conn.cursor() as cur:

                    cur.execute(
                        """
                        INSERT INTO app_users(
                            mobile_number,
                            is_mobile_verified,
                            last_login
                        )
                        VALUES(
                            %s,
                            TRUE,
                            CURRENT_TIMESTAMP
                        )
                        ON CONFLICT(
                            mobile_number
                        )
                        DO UPDATE SET
                            is_mobile_verified=TRUE,
                            last_login=CURRENT_TIMESTAMP
                        RETURNING user_id
                        """,
                        (
                            mobile,
                        )
                    )

                    user_id = (
                        cur.fetchone()[0]
                    )

                conn.commit()

            token = (
                _create_token(
                    user_id,
                    mobile
                )
            )

            response = (
                JSONResponse(
                    {
                        "status":
                            "success",
                        "user_id":
                            user_id,
                        "mobile_number":
                            mobile
                    }
                )
            )

            response.set_cookie(
                SESSION_COOKIE,
                token,
                max_age=(
                    SESSION_DAYS
                    * 86400
                ),
                httponly=True,
                secure=True,
                samesite="lax",
                path="/"
            )

            return response

        except Exception as e:

            return JSONResponse(
                {
                    "status":"error",
                    "message":str(e)
                },
                status_code=400
            )


    @app.post(
        "/auth/logout"
    )
    def logout():

        response = JSONResponse(
            {
                "status":"success"
            }
        )

        response.delete_cookie(
            SESSION_COOKIE,
            path="/"
        )

        return response


    @app.get(
        "/api/account/me"
    )
    def me(
        request: Request
    ):

        user = (
            _current_user(
                request
            )
        )

        try:

            with _db() as conn:

                with conn.cursor() as cur:

                    cur.execute(
                        """
                        SELECT
                            user_id,
                            mobile_number,
                            is_mobile_verified,
                            whatsapp_enabled,
                            last_login
                        FROM app_users
                        WHERE user_id=%s
                        """,
                        (
                            user[
                                "user_id"
                            ],
                        )
                    )

                    row = (
                        cur.fetchone()
                    )

            if not row:

                return JSONResponse(
                    {
                        "status":
                            "error",
                        "message":
                            "User not found."
                    },
                    status_code=404
                )

            return {
                "status":"success",
                "user":{
                    "user_id":
                        row[0],
                    "mobile_number":
                        row[1],
                    "is_mobile_verified":
                        row[2],
                    "whatsapp_enabled":
                        row[3],
                    "last_login":
                        (
                            row[4]
                            .isoformat()
                            if row[4]
                            else None
                        )
                }
            }

        except Exception as e:

            return JSONResponse(
                {
                    "status":"error",
                    "message":str(e)
                },
                status_code=500
            )


    @app.get(
        "/api/account/alert-settings"
    )
    def get_alert_settings(
        request: Request
    ):

        user = (
            _current_user(
                request
            )
        )

        try:

            with _db() as conn:

                with conn.cursor() as cur:

                    cur.execute(
                        """
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
                        """,
                        (
                            user[
                                "user_id"
                            ],
                        )
                    )

                    row = (
                        cur.fetchone()
                    )

            if not row:
                return {
                    "status":
                        "success",
                    "settings":
                        None
                }

            return {
                "status":"success",
                "settings":{
                    "alert_id":
                        row[0],
                    "alert_time":
                        (
                            row[1]
                            .isoformat()
                            if row[1]
                            else None
                        ),
                    "alert_type":
                        row[2],
                    "min_confidence":
                        float(
                            row[3]
                        ),
                    "is_active":
                        row[4]
                }
            }

        except Exception as e:

            return JSONResponse(
                {
                    "status":"error",
                    "message":str(e)
                },
                status_code=500
            )


    @app.post(
        "/api/account/alert-settings"
    )
    def save_alert_settings(
        payload:
            AlertSettingsPayload,
        request:
            Request
    ):

        user = (
            _current_user(
                request
            )
        )

        try:

            alert_type = (
                payload
                .alert_type
                .upper()
            )

            if alert_type not in {
                "CE",
                "PE",
                "BOTH"
            }:

                return JSONResponse(
                    {
                        "status":
                            "error",
                        "message":
                            "alert_type must be "
                            "CE, PE or BOTH."
                    },
                    status_code=400
                )

            min_confidence = max(
                0,
                min(
                    100,
                    float(
                        payload
                        .min_confidence
                    )
                )
            )

            alert_time = None

            if payload.alert_time:

                alert_time = (
                    datetime
                    .strptime(
                        payload
                        .alert_time,
                        "%H:%M"
                    )
                    .time()
                )

            with _db() as conn:

                with conn.cursor() as cur:

                    cur.execute(
                        """
                        UPDATE fo_alert_settings
                        SET
                            is_active=FALSE,
                            updated_at=CURRENT_TIMESTAMP
                        WHERE user_id=%s
                          AND is_active=TRUE
                        """,
                        (
                            user[
                                "user_id"
                            ],
                        )
                    )

                    cur.execute(
                        """
                        INSERT INTO
                        fo_alert_settings(
                            user_id,
                            alert_time,
                            alert_type,
                            min_confidence,
                            is_active
                        )
                        VALUES(
                            %s,%s,%s,%s,TRUE
                        )
                        RETURNING alert_id
                        """,
                        (
                            user[
                                "user_id"
                            ],
                            alert_time,
                            alert_type,
                            min_confidence
                        )
                    )

                    alert_id = (
                        cur.fetchone()[0]
                    )

                    cur.execute(
                        """
                        UPDATE app_users
                        SET whatsapp_enabled=%s
                        WHERE user_id=%s
                        """,
                        (
                            payload
                            .whatsapp_enabled,
                            user[
                                "user_id"
                            ]
                        )
                    )

                conn.commit()

            return {
                "status":
                    "success",
                "alert_id":
                    alert_id
            }

        except Exception as e:

            return JSONResponse(
                {
                    "status":"error",
                    "message":str(e)
                },
                status_code=400
            )


    @app.get(
        "/api/account/alert-history"
    )
    def alert_history(
        request: Request,
        limit: int = 30
    ):

        user = (
            _current_user(
                request
            )
        )

        limit = max(
            1,
            min(
                100,
                limit
            )
        )

        try:

            with _db() as conn:

                with conn.cursor() as cur:

                    cur.execute(
                        """
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
                        """,
                        (
                            user[
                                "user_id"
                            ],
                            limit
                        )
                    )

                    rows = (
                        cur.fetchall()
                    )

            return {
                "status":
                    "success",
                "history":[
                    {
                        "signal":
                            row[0],
                        "nifty_price":
                            (
                                float(
                                    row[1]
                                )
                                if row[1]
                                is not None
                                else None
                            ),
                        "strike_price":
                            (
                                float(
                                    row[2]
                                )
                                if row[2]
                                is not None
                                else None
                            ),
                        "option_type":
                            row[3],
                        "entry_price":
                            (
                                float(
                                    row[4]
                                )
                                if row[4]
                                is not None
                                else None
                            ),
                        "stop_loss":
                            (
                                float(
                                    row[5]
                                )
                                if row[5]
                                is not None
                                else None
                            ),
                        "target1":
                            (
                                float(
                                    row[6]
                                )
                                if row[6]
                                is not None
                                else None
                            ),
                        "target2":
                            (
                                float(
                                    row[7]
                                )
                                if row[7]
                                is not None
                                else None
                            ),
                        "confidence":
                            (
                                float(
                                    row[8]
                                )
                                if row[8]
                                is not None
                                else None
                            ),
                        "whatsapp_status":
                            row[9],
                        "sent_at":
                            (
                                row[10]
                                .isoformat()
                                if row[10]
                                else None
                            )
                    }
                    for row in rows
                ]
            }

        except Exception as e:

            return JSONResponse(
                {
                    "status":"error",
                    "message":str(e)
                },
                status_code=500
            )


    @app.post(
        "/api/whatsapp/test"
    )
    def test_whatsapp(
        request: Request
    ):

        try:

            user = (
                _current_user(
                    request
                )
            )

            sid = (
                _send_whatsapp(
                    user[
                        "mobile_number"
                    ],
                    (
                        "NIFTY AI test alert: "
                        "WhatsApp notifications "
                        "are connected."
                    )
                )
            )

            return {
                "status":
                    "success",
                "message_sid":
                    sid
            }

        except Exception as e:

            return JSONResponse(
                {
                    "status":
                        "error",
                    "message":
                        str(e)
                },
                status_code=400
            )


    @app.post(
        "/api/whatsapp/evaluate"
    )
    def evaluate_and_send(
        request: Request
    ):

        if fno_alert_provider is None:

            return JSONResponse(
                {
                    "status":
                        "error",
                    "message":
                        "F&O alert provider "
                        "is not connected."
                },
                status_code=500
            )

        try:

            user = (
                _current_user(
                    request
                )
            )

            with _db() as conn:

                with conn.cursor() as cur:

                    cur.execute(
                        """
                        SELECT
                            alert_type,
                            min_confidence
                        FROM fo_alert_settings
                        WHERE user_id=%s
                          AND is_active=TRUE
                        ORDER BY alert_id DESC
                        LIMIT 1
                        """,
                        (
                            user[
                                "user_id"
                            ],
                        )
                    )

                    setting = (
                        cur.fetchone()
                    )

                    cur.execute(
                        """
                        SELECT
                            whatsapp_enabled
                        FROM app_users
                        WHERE user_id=%s
                        """,
                        (
                            user[
                                "user_id"
                            ],
                        )
                    )

                    wa_row = (
                        cur.fetchone()
                    )

            if not setting:

                return {
                    "status":
                        "wait",
                    "message":
                        "No active alert settings."
                }

            if (
                not wa_row
                or not wa_row[0]
            ):

                return {
                    "status":
                        "wait",
                    "message":
                        "WhatsApp alerts "
                        "are disabled."
                }

            result = (
                fno_alert_provider()
            )

            if (
                not isinstance(
                    result,
                    dict
                )
                or result.get(
                    "status"
                )
                != "success"
            ):

                return {
                    "status":
                        "wait",
                    "message":
                        "F&O snapshot unavailable."
                }

            alerts = (
                result.get(
                    "alerts"
                )
                or result.get(
                    "fno_alerts"
                )
                or {}
            )

            picked = (
                _pick_trade(
                    alerts
                )
            )

            if not picked:

                return {
                    "status":
                        "wait",
                    "message":
                        "No BUY CE/PE signal "
                        "right now."
                }

            (
                option_type,
                item
            ) = picked

            configured_type = (
                setting[0]
            )

            min_confidence = (
                float(
                    setting[1]
                )
            )

            if (
                configured_type
                != "BOTH"
                and configured_type
                != option_type
            ):

                return {
                    "status":
                        "wait",
                    "message":
                        f"{option_type} signal "
                        "ignored by user setting."
                }

            try:

                confidence = float(
                    item.get(
                        "signal_strength"
                    )
                    or item.get(
                        "confidence"
                    )
                    or result.get(
                        "confidence"
                    )
                    or 0
                )

            except Exception:

                confidence = 0.0

            if confidence <= 1:
                confidence *= 100

            if (
                confidence
                < min_confidence
            ):

                return {
                    "status":
                        "wait",
                    "message":
                        (
                            f"Signal confidence "
                            f"{confidence:.1f}% "
                            f"is below "
                            f"{min_confidence:.1f}%."
                        )
                }

            nifty_price = (
                result.get(
                    "price"
                )
            )

            signal_key = (
                _signal_key(
                    option_type,
                    item,
                    nifty_price
                )
            )

            if _already_sent(
                user[
                    "user_id"
                ],
                signal_key
            ):

                return {
                    "status":
                        "duplicate",
                    "message":
                        "Same signal was already "
                        "sent recently."
                }

            strike = (
                item.get(
                    "strike"
                )
                or item.get(
                    "strike_price"
                )
            )

            entry = (
                item.get(
                    "entry"
                )
                or item.get(
                    "entry_price"
                )
                or item.get(
                    "entry_zone"
                )
            )

            stop = (
                item.get(
                    "stop_loss"
                )
                or item.get(
                    "stop"
                )
            )

            target1 = (
                item.get(
                    "target1"
                )
                or item.get(
                    "target_1"
                )
            )

            target2 = (
                item.get(
                    "target2"
                )
                or item.get(
                    "target_2"
                )
            )

            signal = str(
                item.get(
                    "signal"
                )
                or f"BUY {option_type}"
            ).upper()

            text = (
                "NIFTY AI F&O ALERT\n"
                f"Signal: {signal}\n"
                f"NIFTY: {nifty_price}\n"
                f"Strike: {strike} "
                f"{option_type}\n"
                f"Entry: {entry}\n"
                f"Stop Loss: {stop}\n"
                f"Target 1: {target1}\n"
                f"Target 2: {target2}\n"
                f"Confidence: "
                f"{confidence:.1f}%\n"
                f"Time: "
                f"{datetime.now().strftime('%d-%b-%Y %H:%M:%S')}"
            )

            sid = (
                _send_whatsapp(
                    user[
                        "mobile_number"
                    ],
                    text
                )
            )

            with _db() as conn:

                with conn.cursor() as cur:

                    cur.execute(
                        """
                        INSERT INTO
                        fo_alert_history(
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
                            %s,%s,%s,%s,%s,
                            %s,%s,%s,%s,%s,
                            %s,%s,%s
                        )
                        """,
                        (
                            user[
                                "user_id"
                            ],
                            signal,
                            _num(
                                nifty_price
                            ),
                            _num(
                                strike
                            ),
                            option_type,
                            _num(
                                entry
                            ),
                            _num(
                                stop
                            ),
                            _num(
                                target1
                            ),
                            _num(
                                target2
                            ),
                            confidence,
                            "SENT",
                            sid,
                            signal_key
                        )
                    )

                conn.commit()

            return {
                "status":
                    "sent",
                "signal":
                    signal,
                "option_type":
                    option_type,
                "confidence":
                    round(
                        confidence,
                        1
                    ),
                "message_sid":
                    sid
            }

        except Exception as e:

            return JSONResponse(
                {
                    "status":
                        "error",
                    "message":
                        str(e)
                },
                status_code=400
            )

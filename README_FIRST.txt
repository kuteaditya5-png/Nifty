NIFTY AI v8.1 — VERCEL STARTUP FIX
===================================

WHAT WAS FIXED
--------------
The earlier auth_whatsapp.py imported these at Python startup:
- jwt
- psycopg
- twilio

A failure loading any one of them could crash the whole Vercel
serverless function before /login opened.

This build:
- removes PyJWT completely
- uses a signed standard-library session cookie
- lazy-loads psycopg only when PostgreSQL is needed
- lazy-loads Twilio only when OTP/WhatsApp is needed
- does NOT connect to PostgreSQL during application startup
- allows the login page/dashboard routing to start independently
- adds GET /auth/status so configuration can be checked safely
- does not fail startup if fno_alerts cannot be imported

UPLOAD
------
KEEP your existing working main.py.

Replace:
- auth_whatsapp.py
- vercel_entry.py
- requirements.txt
- vercel.json

You can also keep/use:
- schema.sql
- dashboard_whatsapp_ui_patch.html
- scheduled_alert_whatsapp_patch.js

VERCEL VARIABLES
----------------
For the LOGIN PAGE itself:
No Twilio or database connection is required just to render /login.

For actual OTP login:
- TWILIO_ACCOUNT_SID
- TWILIO_AUTH_TOKEN
- TWILIO_VERIFY_SERVICE_SID
- DATABASE_URL
- JWT_SECRET (24+ characters)

For WhatsApp:
- TWILIO_WHATSAPP_FROM
- TWILIO_CONTENT_SID when required by your approved template setup

TEST ORDER
----------
1. Deploy.
2. Open:
   /health

3. Open:
   /login

4. Open:
   /auth/status

Expected:
{
  "status": "success",
  ...
}

5. Only after those work, test Send OTP.

IMPORTANT
---------
Do not replace the working NIFTY prediction main.py with these support
files. main.py remains your existing v8.0 model.

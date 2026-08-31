NIFTY AI v8.1 — READY TO UPLOAD
================================

IMPORTANT
---------
This package fixes the missing login page issue.

You DO NOT need to run patch_main.py anymore.

KEEP YOUR CURRENT v8.0 main.py
------------------------------
Your deployment folder must contain your existing current NIFTY AI main.py.

Add these new files beside it:
- vercel_entry.py
- auth_whatsapp.py
- requirements.txt
- schema.sql
- .env.example
- vercel.json
- dashboard_whatsapp_ui_patch.html
- scheduled_alert_whatsapp_patch.js

WHY LOGIN WAS MISSING
---------------------
The previous package required:
    python patch_main.py

That step attached the login routes to the FastAPI app.

This new package instead uses:
    vercel_entry.py

Vercel loads vercel_entry.py, which imports your existing app from main.py
and automatically attaches the login + WhatsApp module.

AFTER DEPLOYMENT
----------------
Open:
    https://YOUR-VERCEL-DOMAIN/login

The root "/" in your old main.py may still redirect to /dashboard,
but /dashboard is now protected and will redirect unauthenticated users
to /login.

VERCEL ENVIRONMENT VARIABLES
----------------------------
Required:
    NEWS_API_KEY
    DATABASE_URL
    JWT_SECRET
    TWILIO_ACCOUNT_SID
    TWILIO_AUTH_TOKEN
    TWILIO_VERIFY_SERVICE_SID
    TWILIO_WHATSAPP_FROM

Optional / production template:
    TWILIO_CONTENT_SID

DATABASE
--------
Run schema.sql in your PostgreSQL database.

TEST
----
1. Deploy.
2. Open /login.
3. Enter mobile number.
4. Verify OTP.
5. Dashboard opens.
6. Test:
       POST /api/whatsapp/test

NOTE
----
Your EXISTING main.py is still required because it contains the NIFTY v8.0
prediction engine and /fno-alerts logic.

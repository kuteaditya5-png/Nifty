NIFTY AI v8.1 — VERCEL FIX 2
=============================

THIS FIX
--------
The previous build failed with:

Could not find a top-level "app", "application", or "handler"
in "vercel_entry.py".

This version exposes:

    app = main_app

at the TOP LEVEL of vercel_entry.py so Vercel can detect the FastAPI app.

UPLOAD
------
Keep your existing working main.py.

Replace these files with this package:
- vercel_entry.py
- auth_whatsapp.py
- requirements.txt
- vercel.json

You may also keep:
- schema.sql
- dashboard_whatsapp_ui_patch.html
- scheduled_alert_whatsapp_patch.js

TEST AFTER DEPLOY
-----------------
1. /health
2. /login
3. /auth/status

If those work, then configure/test OTP and WhatsApp.

NIFTY AI v8.1 — Mobile OTP Login + WhatsApp Alerts
==================================================

BASE VERSION
------------
Use this with your current NIFTY AI v8.0 main.py.

The v8.0 file already contains:
- /dashboard
- /prediction
- /fno-alerts
- EMA / RSI / MACD
- completed 5-minute candlestick confirmation
- 5m/15m price-action confirmation
- market breadth
- NIFTY futures positioning
- FII/DII
- global cues
- option-chain analysis
- lazy-loaded CE/PE alert engine

WHAT THIS UPDATE ADDS
---------------------
1. Mobile number login.
2. OTP verification using Twilio Verify.
3. Secure HttpOnly JWT login cookie.
4. Verified login number stored in PostgreSQL.
5. Same verified number used for WhatsApp alerts.
6. CE / PE / BOTH alert preference.
7. Minimum confidence preference.
8. Preferred alert time stored in database.
9. WhatsApp test endpoint.
10. Current-signal WhatsApp endpoint.
11. Alert history.
12. 45-minute duplicate-signal protection.
13. Logout.
14. /dashboard protection.

FILES
-----
auth_whatsapp.py
patch_main.py
requirements.txt
schema.sql
dashboard_whatsapp_ui_patch.html
scheduled_alert_whatsapp_patch.js
.env.example
vercel.json

INSTALL
-------
1. Copy these files into the same folder as your CURRENT v8.0 main.py.

2. Run:
       python patch_main.py

   The script first creates:
       main_before_login_whatsapp.py

3. Create PostgreSQL (for example Neon/Supabase PostgreSQL).

4. Run schema.sql if you want to create the tables manually.
   auth_whatsapp.py also uses CREATE TABLE IF NOT EXISTS.

5. Configure Vercel Environment Variables:
       NEWS_API_KEY
       DATABASE_URL
       JWT_SECRET
       TWILIO_ACCOUNT_SID
       TWILIO_AUTH_TOKEN
       TWILIO_VERIFY_SERVICE_SID
       TWILIO_WHATSAPP_FROM
       TWILIO_CONTENT_SID   (optional for sandbox; production templates recommended)

6. Install:
       pip install -r requirements.txt

7. Test:
       uvicorn main:app --reload

8. Open:
       http://127.0.0.1:8000/login

9. After login:
       POST /api/whatsapp/test

10. Save settings and test the model:
       POST /api/whatsapp/evaluate

DASHBOARD UI
------------
dashboard_whatsapp_ui_patch.html contains the UI block for:
- verified number
- CE / PE / BOTH
- minimum confidence
- alert time
- test WhatsApp
- check/send current signal
- logout

SCHEDULED ALERT CONNECTION
--------------------------
Your existing v8.0 scheduled browser alert calls:
    await loadFnoAlerts(true);

Add the line from scheduled_alert_whatsapp_patch.js immediately after it.
That will also ask the backend to send WhatsApp when the scheduled
browser alert fires.

IMPORTANT LIMITATION
--------------------
The saved alert_time does NOT by itself execute while the browser is closed.
Vercel/FastAPI needs a scheduler/worker/cron to run future alerts independently.

So this update has two modes:

A) Browser open:
   Existing scheduled alert fires -> WhatsApp endpoint is called.

B) Browser closed:
   Add an external scheduler/worker later for fully independent delivery.

SECURITY
--------
Do not put Twilio, DATABASE_URL or JWT_SECRET values in frontend code or GitHub.

WHATSAPP
--------
Twilio Sandbox is suitable for initial testing.
For business-initiated production alerts, use the approved WhatsApp/template
flow required by your WhatsApp provider.

TRADING
-------
This integration only sends model alerts. It does not place orders.

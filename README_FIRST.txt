NIFTY AI v9 - Password Login + Paper Trading

Replace these 5 files in GitHub root and redeploy Vercel.

1 main.py
2 auth_whatsapp.py
3 vercel_entry.py
4 requirements.txt
5 vercel.json

Twilio Verify/OTP is no longer used. TWILIO_VERIFY_SERVICE_SID can be removed.
Keep DATABASE_URL and JWT_SECRET. Keep Twilio Account/Auth/WhatsApp variables only if WhatsApp alerts are still required.

First-time login: choose Create Password on /login. Later login with mobile + password.
Paper account starts at Rs 100,000 and stores trades in your existing PostgreSQL database.

NIFTY AI v9.2 - BLANK DASHBOARD FIX

This build fixes the browser JavaScript syntax error that kept the whole dashboard at Loading... and -- values.

Replace these files in the GitHub repo root and redeploy Vercel:
- main.py
- auth_whatsapp.py
- vercel_entry.py
- requirements.txt
- vercel.json

Keep existing Vercel variables:
DATABASE_URL
JWT_SECRET
NEWS_API_KEY

Twilio Verify is not required for login. WhatsApp Twilio variables are optional unless WhatsApp alerts are enabled.

"""
Vercel entrypoint for NIFTY AI v8.1.

Keep your existing v8.0 main.py unchanged in the same folder.
This module imports the existing FastAPI app and attaches:
- /login
- OTP endpoints
- user session
- WhatsApp alert endpoints
- dashboard authentication
"""

from main import app, fno_alerts
from auth_whatsapp import setup_auth_whatsapp

setup_auth_whatsapp(
    app,
    fno_alert_provider=fno_alerts
)

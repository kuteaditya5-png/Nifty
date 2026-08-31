"""
NIFTY AI v8.1 Vercel entrypoint.

Vercel requires a top-level variable named app/application/handler.
"""

from main import app as main_app
from auth_whatsapp import setup_auth_whatsapp

try:
    from main import fno_alerts
except Exception:
    # Keep login/dashboard available even if alert provider is temporarily unavailable.
    fno_alerts = None

# Attach login + WhatsApp routes to the existing FastAPI application.
setup_auth_whatsapp(
    main_app,
    fno_alert_provider=fno_alerts
)

# IMPORTANT: top-level FastAPI app for Vercel detection.
app = main_app

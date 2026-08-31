"""
NIFTY AI v8.1 Vercel entrypoint.

This file intentionally keeps the startup layer very small.
"""

try:
    from main import app
except Exception as exc:
    raise RuntimeError(
        "Could not import FastAPI app from main.py. "
        f"Original error: {exc}"
    ) from exc

try:
    from main import fno_alerts
except Exception:
    # Login/dashboard can still load even if the F&O function
    # has been renamed or is temporarily unavailable.
    fno_alerts = None

try:
    from auth_whatsapp import setup_auth_whatsapp
except Exception as exc:
    raise RuntimeError(
        "Could not import auth_whatsapp.py. "
        f"Original error: {exc}"
    ) from exc

setup_auth_whatsapp(
    app,
    fno_alert_provider=fno_alerts
)

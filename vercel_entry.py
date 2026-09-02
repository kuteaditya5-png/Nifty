from main import app, fno_alerts
from auth_whatsapp import setup_auth_whatsapp
setup_auth_whatsapp(app, fno_alert_provider=fno_alerts)

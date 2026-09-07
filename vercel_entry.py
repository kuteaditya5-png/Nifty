from main import app, fno_alerts
from auth import setup_auth
setup_auth(app, fno_alert_provider=fno_alerts)

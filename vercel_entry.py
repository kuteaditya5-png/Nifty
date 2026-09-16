from main import app, fno_alerts
from auth import setup_auth
setup_auth(app, fno_alert_provider=fno_alerts)

from v1518 import setup_v1518
setup_v1518(app)

from v1519 import setup_v1519
setup_v1519(app)

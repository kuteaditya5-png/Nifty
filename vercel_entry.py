from main import app, fno_alerts
from auth import setup_auth
setup_auth(app, fno_alert_provider=fno_alerts)

from v1518 import setup_v1518
setup_v1518(app)

from v1519 import setup_v1519
setup_v1519(app)

from v1520 import setup_v1520
setup_v1520(app)

from v1521 import setup_v1521
setup_v1521(app)

from v1522 import setup_v1522
setup_v1522(app)

from v1523 import setup_v1523
setup_v1523(app)

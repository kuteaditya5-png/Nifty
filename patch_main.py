from pathlib import Path
import shutil

main = Path("main.py")

if not main.exists():
    raise SystemExit(
        "main.py was not found. Put this patcher beside your current NIFTY AI main.py."
    )

backup = Path("main_before_login_whatsapp.py")

if not backup.exists():
    shutil.copy2(main, backup)

text = main.read_text(encoding="utf-8")

marker = "# NIFTY_AI_AUTH_WHATSAPP_V8_1"

if marker in text:
    print("main.py is already patched.")
    raise SystemExit(0)

if "def fno_alerts(" not in text:
    raise SystemExit(
        "Could not find def fno_alerts() in main.py. Use the v8.0 main file."
    )

addition = r'''

# NIFTY_AI_AUTH_WHATSAPP_V8_1
# Mobile OTP login + verified-number WhatsApp alert integration.
from auth_whatsapp import setup_auth_whatsapp

setup_auth_whatsapp(
    app,
    fno_alert_provider=fno_alerts
)
'''

main.write_text(
    text.rstrip() + addition + "\n",
    encoding="utf-8"
)

print("Patched main.py successfully.")
print("Backup created:", backup)

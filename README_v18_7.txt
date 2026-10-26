NIFTY AI v18.7 — Free GitHub Actions scheduled entry confirmation

FILES TO ADD/REPLACE IN GITHUB:
- main.py (replace)
- auth.py (replace, unchanged from v18.6)
- entry_confirmation_v187.py (new)
- .github/workflows/nifty-monitor.yml (new, keep folder structure)

VERCEL ENVIRONMENT VARIABLE:
- NIFTY_MONITOR_SECRET = a long random secret (different from JWT_SECRET)
- DATABASE_URL must be configured (existing Neon DB)
Redeploy Vercel after setting the secret.

GITHUB REPOSITORY -> Settings -> Secrets and variables -> Actions -> New repository secret:
- NIFTY_SITE_URL = https://YOUR-DEPLOYMENT.vercel.app
- NIFTY_MONITOR_SECRET = exact same value as Vercel environment variable

GitHub Actions scheduled runs are NOT guaranteed exactly on time and can be delayed or skipped.
The cron runs every 5 minutes on weekdays (UTC window); API applies IST hours.
This is NOT real-time 1-minute monitoring. NSE holidays are not explicitly checked;
missing/closed-session data results in no eligible new entry after candle validation.

v18.7 endpoint: POST /api/v18.7/monitor (requires X-Monitor-Secret header).
Uses Yahoo NIFTY 5-minute candles; if stale/unavailable, no confirmed entry should be issued.
Stores one event per completed candle in Neon PostgreSQL; no trade orders or notifications.
Signals are experimental; only NEW crossing of the opening range on a completed candle
can generate BUY CE or BUY PE when aligned with the existing model.
Current /prediction and /fno-alerts are unchanged. No performance improvement is claimed.

IMPORTANT: This is an initial free worker implementation. GitHub Actions is best-effort.
For reliable time-critical alerts, use a paid scheduled worker with provider data and
proper holiday-calendar/stale-data validation. No Telegram/WhatsApp push is included.

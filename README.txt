NIFTY AI - Signal Journal / Chart PNG / Calls Excel - Add-on (not yet deployed)

IMPORTANT: This package is a PATCH for the restored pre-26-Oct repository, NOT a replacement main.py.
This version intentionally leaves existing prediction logic unchanged.

1. Back up your repo and use the restored pre-26-Oct version.
2. Copy signal_tracker.py, dashboard_addon.html, install_patch.py to repository root.
3. Run: python install_patch.py
4. Review main.py diff and commit main.py + signal_tracker.py.
5. Add openpyxl to requirements.txt (only for runtime XLSX generation).
6. Ensure DATABASE_URL already exists in Vercel; set SIGNAL_EXPORT_KEY to a long private random value in Vercel, redeploy.
7. Visit /dashboard. Download chart PNG or calls Excel. The Excel button asks for the private export key.
8. Check Vercel logs for errors and confirm records in PostgreSQL.

LIMITATIONS / SAFETY
- Calls are observed and stored ONLY while dashboard is open. There is no reliable autonomous collection yet.
- No subsequent 5/10/15/30 minute price outcomes or late-call analysis yet. These require a verified data feed and a scheduler.
- Logged timestamps are observation times, not guaranteed first signal times.
- No option premium is logged. NIFTY spot price is intentionally left empty rather than guessed.
- Public observation endpoint is not authenticated. Do not use records as trusted trading evidence without securing server-side collection.
- Chart PNG uses existing Lightweight Charts instance `chart` and may fail if the original dashboard changed variable names.
- XLSX export uses an authorization header; do not share your SIGNAL_EXPORT_KEY.
- The database table is created on first observation/export. No destructive schema changes.
- No workflow or v18.7 confirmation engine is installed.

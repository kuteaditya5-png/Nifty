NIFTY AI v18.8 — Dashboard-integrated entry confirmation

CHANGED
- Existing v18.6 indicators, scoring and raw directional setup preserved.
- Completed 5-minute opening-range breakout/rejection gate now filters dashboard CE WATCH/PE WATCH to WAIT unless confirmed.
- Final /prediction?include_alerts=true and /fno-alerts agree; WAIT suppresses actionable F&O alerts.
- Dashboard shows a small inline Entry Confirmation strip (no info icon), with reason and opening-range levels.
- Raw model setup is exposed as entry_confirmation.base_setup; final setup as entry_confirmation.final_setup.
- No database reset. Existing v18.7 monitor endpoint and GitHub Actions workflow remain.

INSTALL
1. Upload main.py and entry_confirmation_v187.py to GitHub Nifty repo root, replacing existing versions.
2. Keep existing auth.py, .github/workflows/nifty-monitor.yml and all other repo files unchanged.
3. Commit; check Vercel production deployment. No new secrets, database migration, or cron changes.
4. After 09:35 IST on an NSE trading day, open the dashboard and Refresh.
5. Check /prediction?include_alerts=true JSON for entry_confirmation.status/reason/base_setup/final_setup.
6. Check GitHub Actions monitoring logs and PostgreSQL storage separately; a successful API skip does not prove DB writes.

IMPORTANT LIMITATIONS
- This conservative gate only approves a fresh opening-range crossing seen in the latest four completed 5m bars. A later continuation may show WAIT.
- Uses Yahoo Finance NIFTY 5-minute data, which may be delayed/unavailable; WAIT is the safe fallback.
- No broker orders; this is research/paper trading.
- Does not claim higher accuracy until validated.
- Python syntax validated, not live NSE or Neon DB tested.
- This build is based on the v18.7 ZIP supplied in this conversation. If GitHub main.py has newer independent edits, compare before overwriting.

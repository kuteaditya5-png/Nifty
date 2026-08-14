# NIFTY AI V7.1 — Lazy F&O Side Panel + One-Time Scheduler

The main dashboard remains the old dashboard layout.

## Changes
- F&O CE / PE Alert Engine removed from the main dashboard body.
- Added a left-side drawer opened from the `☰` button.
- Normal `/prediction` does not calculate the F&O alert layer.
- `/fno-alerts` calculates it only when needed.
- Nearby option premiums are excluded from normal dashboard payloads.
- One active scheduled alert at a time.
- At the selected browser-local date/time, the page fetches `/fno-alerts`.
- The scheduled alert is automatically completed after firing.
- A new alert can then be scheduled.
- If the scheduled snapshot produces a BUY SIGNAL, CE/PE stop/target/invalidation
  lifecycle monitoring continues once per minute.

## Important
Scheduled browser alerts work only while the website remains open in a browser tab.
A closed-browser/mobile push alert will need a persistent backend notification worker.

## Deploy
Replace the current GitHub `app.py` with this package's `app.py`,
commit to `main`, and Vercel should redeploy automatically.

Keep the existing `NEWS_API_KEY` environment variable.

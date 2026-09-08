NIFTY AI v14.2 — Persistent Login Fix

WHY YOU WERE LOGGED OUT AFTER EVERY DEPLOY
Vercel generates a different deployment hostname for each deployment, e.g.
nifty-abc123-....vercel.app
nifty-def456-....vercel.app

Browser cookies cannot move between different hostnames. This is a browser
security rule, not a JWT bug.

FIX INCLUDED
1. Session lifetime increased to 90 days.
2. JWT_SECRET remains the key that keeps existing sessions valid.
3. New optional Vercel variable:
   NIFTY_CANONICAL_HOST

Set it to your ONE stable production domain, for example:
   nifty.vercel.app

Do NOT include https://

When anyone opens a temporary deployment URL, the app redirects to the stable
production hostname, where the existing login cookie remains available.

IMPORTANT
JWT_SECRET MUST NOT change between deployments. If it changes, all existing
login tokens become invalid and users must login again.

VERCEL SETUP
Project -> Settings -> Environment Variables

Keep:
DATABASE_URL
JWT_SECRET
NEWS_API_KEY

Add:
NIFTY_CANONICAL_HOST = your stable Production Domain shown in Vercel Domains

Then redeploy Production.

BEST PRACTICE
Always open/share the stable Production Domain, not the unique deployment URL.

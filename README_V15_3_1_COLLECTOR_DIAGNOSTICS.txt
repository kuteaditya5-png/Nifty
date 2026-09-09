NIFTY AI v15.3.1 — Historical Collector Diagnostics

Adds a safe Collector Diagnostics button before attempting another historical collection.
It checks whether UPSTOX_ACCESS_TOKEN is actually visible to the Production deployment,
reports only token presence/length (never the secret), probes Upstox with a small historical
request, and distinguishes missing token, rejected/expired token, rate limiting, provider errors,
and network errors.

Test order:
1. Deploy to Vercel Production.
2. Open Backtest.
3. Click Collector Diagnostics v15.3.1.
4. Only if probe = PASS, click Auto Collect History v15.3.
5. Then check Acquisition Progress v15.2.

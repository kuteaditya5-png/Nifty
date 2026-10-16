NIFTY AI v18.6 — Active Trend Indicators

Replace main.py and auth.py in GitHub, then commit for Vercel deployment.

Supertrend(10,3) + DI agreement contributes up to +/-0.09 to prediction score, scaled by ADX(14).
ADX below 20 or 5-minute ATR(14) above 0.5% of index price forces F&O setup to WAIT when indicators are available. Opposing Supertrend/DI direction also forces WAIT.
No changes to DB, history, or UI. API: signals.trend_observation_v185.active_prediction shows activation details (legacy field name retained for compatibility).
IMPORTANT: The separately computed /fno-alerts engine may still issue alerts independently of this F&O setup filter. No live trading or historical performance validation has been performed. These are experimental thresholds; review on paper trading first.

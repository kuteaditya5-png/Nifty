NIFTY AI v10 - Exact Paper P&L + Accuracy Tracker

WHAT IS FIXED
1. Paper P&L now tracks the exact saved option contract:
   expiry + strike + CE/PE.
2. It no longer depends on whatever ATM strike the next prediction chooses.
3. Open positions update current premium and P&L on dashboard refresh.
4. Paper trades automatically close when observed premium reaches Stop Loss,
   Target 1, or Target 2.
5. New Prediction Accuracy Tracker records qualifying BUY CE/PE signals globally.
6. Accuracy = Target 1 observed before Stop Loss.
7. CE accuracy, PE accuracy, wins/losses, open signals and profit factor are shown.
8. Login remains mobile number + password. No OTP login.

IMPORTANT
- This remains paper trading / validation only.
- Accuracy collection happens when the app is refreshed/synced. A Vercel background
  scheduler can be added later for continuous tracking while nobody has the page open.
- Sparse refreshes cannot know the exact intrabar order if both SL and target were touched
  between checks. The evaluator uses a conservative rule.

UPLOAD/REPLACE IN GITHUB ROOT
- main.py
- auth_whatsapp.py
- vercel_entry.py
- requirements.txt
- vercel.json

KEEP VERCEL ENVIRONMENT VARIABLES
- DATABASE_URL
- JWT_SECRET
- NEWS_API_KEY
- Twilio WhatsApp variables only if WhatsApp alerts are used.

No manual SQL migration is needed; missing columns/tables are created automatically.

NIFTY AI v9.1 FIXED

This package fixes the blank dashboard issue in v9.

CAUSE FIXED:
The previous main.py contained literal \n characters inside the dashboard JavaScript.
That caused the browser JavaScript to stop before prediction, chart and paper trading loaded.

REPLACE THESE FILES IN GITHUB ROOT:
- main.py
- auth_whatsapp.py
- vercel_entry.py
- requirements.txt
- vercel.json

Then redeploy Vercel.

KEEP:
DATABASE_URL
JWT_SECRET
NEWS_API_KEY

Twilio Verify is NOT required for login.
Twilio WhatsApp variables are only needed if WhatsApp alerts are enabled.

Expected after deploy:
- Mobile number + password login
- Prediction values populate
- Trade Plan values populate when F&O alert data is available
- Paper portfolio shows starting virtual balance
- Chart loads

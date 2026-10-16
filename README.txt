NIFTY AI v18.3 Paper Trading Fix

Replace root auth.py and main.py in GitHub; keep all other files and Vercel environment variables unchanged. Deploy latest commit.

Strict quote matching: only the option strike and expiry currently exposed by the F&O snapshot can update an open trade. Other contracts remain stale with a warning; they are NEVER assigned an invented or different contract price. For arbitrary strike/expiry quotes, a separate contract-specific quote API is still required.

Equity now includes marked value of open long option positions. Open P&L is separate. Existing trades and history are untouched. No live broker orders are placed.

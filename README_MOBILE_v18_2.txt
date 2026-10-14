NIFTY AI v18.2 Mobile Layout Repair

Replace main.py, auth.py, v18.py in GitHub root only if those match the v18.1 build you deployed. Commit and let Vercel deploy.

UI-only fixes: header clipping, nav overflow, prediction signal/confidence overlap, trade card sizing, chart overflow, WAIT reference-level label. Existing backend trading decisions unchanged.

TEST: iPhone 375/390px and Android 360/412px widths; login; header visible; swipe navigation; WAIT label; CE/PE states; scroll; chart; Backtest; paper trade history; desktop regression.

No live browser or Vercel deployment tests have been run.

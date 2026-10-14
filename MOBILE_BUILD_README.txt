NIFTY AI v18.1 — Mobile-First UI Patch

Contents: main.py, auth.py, v18.py.
Based on the previous v18 Modern Dark Horizontal UI build.

WHAT CHANGED
- Mobile header wraps without overflowing.
- Single horizontal navigation with swipe-to-scroll tabs; no sidebar.
- Prediction, trade setup and market cards stack vertically on phones.
- Entry/SL/target cards use a compact 2-column layout.
- Option-chain table can scroll horizontally without breaking page width.
- Backtest panel fits inside the mobile screen and scrolls vertically.
- Inputs and buttons have touch-friendly sizing.
- NIFTY AI branding and Made by Aditya retained; no crown.
- Existing Python trading calculations and API routes not modified.

DEPLOY
1. Save a backup of your current GitHub files.
2. Upload main.py, auth.py, v18.py to your repository root (replace existing files).
3. Commit, then wait for Vercel deployment to complete.
4. On your phone, refresh the page (use private tab if the old CSS is cached).

TEST ON PHONE
1. Login; verify dashboard opens without horizontal page scrolling.
2. Swipe the single navigation bar to see all tabs; each tab must work.
3. Check CE/PE/WAIT prediction, price, and market status load.
4. Scroll chart, change timeframes, and inspect candle visibility.
5. Check option-chain table scrolls sideways INSIDE its card.
6. Open Backtest; ensure controls and close button remain reachable.
7. Open Trading and History; check paper trades are unchanged.
8. Check portrait and landscape orientation.
9. Check at ~360px, 390px and 430px screen widths if possible.

NOTE: Syntax compilation passed. Actual Vercel/mobile-browser integration has not been tested.

"""Run from repo root: python install_patch.py. Idempotent for same source."""
from pathlib import Path
p=Path('main.py');s=p.read_text(encoding='utf-8')
needle='@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)'
if needle not in s: raise SystemExit('Expected dashboard route missing; do not modify automatically')
if 'signal_tracker.register(app)' not in s:
    s+='\n\n# Optional observational signal journal\nimport signal_tracker\nsignal_tracker.register(app)\n'
addon=Path('dashboard_addon.html').read_text(encoding='utf-8')
start=s.index(needle);close=s.find('</body>',start)
if close<0: raise SystemExit('Dashboard </body> not found; no file written')
if 'id="signalJournalTools"' not in s:s=s[:close]+addon+'\n'+s[close:]
compile(s,str(p),'exec');p.write_text(s,encoding='utf-8');print('Patched main.py; review diff and deploy main.py, signal_tracker.py, requirements update.')

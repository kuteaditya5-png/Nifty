"""Durable scheduled snapshots. Missing past decisions are never reconstructed as live."""
import hmac
import os
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from fastapi import HTTPException, Request
from psycopg.types.json import Jsonb
import signal_tracker

IST = ZoneInfo('Asia/Kolkata')
DDL = '''CREATE TABLE IF NOT EXISTS nifty_server_decisions (
 candle_at TIMESTAMPTZ PRIMARY KEY,
 recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 capture_status TEXT NOT NULL CHECK(capture_status IN ('CAPTURED','MISSING')),
 payload JSONB NOT NULL DEFAULT '{}'::jsonb
);'''

def expected_candles(now):
    now = now.astimezone(IST)
    if now.weekday() >= 5:
        return []
    start = datetime.combine(now.date(),time(9,15),IST)
    return [start+timedelta(minutes=5*i) for i in range(75)
            if start+timedelta(minutes=5*(i+1)) <= now]

def require_secret(request):
    key = os.getenv('NIFTY_MONITOR_SECRET','')
    supplied = request.headers.get('X-Monitor-Secret','')
    if not key or not hmac.compare_digest(key,supplied):
        raise HTTPException(403,'Monitor authorization required')

def collect(provider, now=None):
    now = now or datetime.now(IST)
    if now.weekday()>=5 or not time(9,20)<=now.time()<=time(15,35):
        return {'status':'skipped','reason':'Outside collection window'}
    expected = expected_candles(now)
    with signal_tracker.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)
            cur.execute('SELECT pg_try_advisory_xact_lock(1814001)')
            if not cur.fetchone()[0]:
                return {'status':'skipped','reason':'Collector already running'}
            cur.execute('SELECT capture_status FROM nifty_server_decisions WHERE candle_at=%s',(expected[-1],))
            existing = cur.fetchone()
            if existing and existing[0]=='CAPTURED':
                return {'status':'success','recorded':False,'reason':'Latest bucket already captured'}
            snapshot = provider(include_alerts=True)
            if snapshot.get('status')!='success':
                raise RuntimeError('Prediction unavailable; no live snapshot was recorded')
            at = datetime.fromisoformat(snapshot['candle_at']).astimezone(IST)
            completed_at = datetime.fromisoformat(snapshot['decision_completed_at']).astimezone(IST)
            # Source session is the evidence that this is a trading day (no fabricated holiday gaps).
            if at.date()!=now.date() or at not in expected or (now-at-timedelta(minutes=5)).total_seconds()>12*60:
                return {'status':'skipped','reason':'No fresh same-session source candle'}
            if (completed_at-at-timedelta(minutes=5)).total_seconds()>12*60:
                return {'status':'skipped','reason':'Prediction collection exceeded freshness limit'}
            for bucket in expected:
                cur.execute('''INSERT INTO nifty_server_decisions(candle_at,capture_status)
                    VALUES(%s,'MISSING') ON CONFLICT(candle_at) DO NOTHING''',(bucket,))
            snapshot['capture_delay_seconds'] = round((completed_at-at-timedelta(minutes=5)).total_seconds(),1)
            snapshot['source'] = 'server_monitor'
            cur.execute('''INSERT INTO nifty_server_decisions(candle_at,capture_status,payload)
                VALUES(%s,'CAPTURED',%s) ON CONFLICT(candle_at) DO UPDATE SET
                capture_status='CAPTURED',payload=EXCLUDED.payload,recorded_at=now()
                WHERE nifty_server_decisions.capture_status='MISSING' RETURNING candle_at''',(at,Jsonb(snapshot)))
            stored = cur.fetchone() is not None
    return {'status':'success','recorded':stored,'candle_at':at.isoformat()}

def export_rows(day=''):
    with signal_tracker.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)
            if day:
                cur.execute("SELECT candle_at,recorded_at,capture_status,payload FROM nifty_server_decisions WHERE (candle_at AT TIME ZONE 'Asia/Kolkata')::date=%s ORDER BY candle_at",(day,))
            else:
                cur.execute('SELECT candle_at,recorded_at,capture_status,payload FROM nifty_server_decisions ORDER BY candle_at DESC LIMIT 10000')
            return cur.fetchall()

def append_export(wb, day=''):
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    import json
    ws=wb.create_sheet('Server Decisions',0)
    ws.append(['Candle Start (IST)','Candle End (IST)','Captured At (IST)','Capture Status','Live WATCH Decision',
        'CE Alert','PE Alert','Shadow Decision','WAIT Reason','CE Failed WATCH Gates','PE Failed WATCH Gates',
        'Option Data Available','CE Strength','PE Strength','Base Score','Breakout Adjustment','Adjusted Score',
        'Breakout Direction','Confirmed Breakout','Quality Flags','Capture Delay Seconds','CE Warnings','PE Warnings'])
    rows=export_rows(day)
    counts={}
    for at,recorded,status,p in rows:
        alerts=p.get('fno_alerts') or {}; ce=alerts.get('call') or {};pe=alerts.get('put') or {}
        b=(p.get('breakout') or {}).get('latest') or {}; adj=p.get('breakout_adjustment') or {};g=p.get('failed_gates') or {}
        ws.append([at.astimezone(IST).replace(tzinfo=None),(at+timedelta(minutes=5)).astimezone(IST).replace(tzinfo=None),
            recorded.astimezone(IST).replace(tzinfo=None) if status=='CAPTURED' else None,status,
            p.get('fno_setup'),ce.get('signal'),pe.get('signal'),(p.get('shadow_decision') or {}).get('decision'),
            p.get('fno_setup_reason') if status=='CAPTURED' else 'No historical live snapshot; do not count as WAIT',
            ', '.join(g.get('CE',[])),', '.join(g.get('PE',[])),p.get('option_data_available'),
            ce.get('signal_strength_percent'),pe.get('signal_strength_percent'),adj.get('base_score'),adj.get('adjustment'),adj.get('adjusted_score'),
            b.get('direction'),b.get('confirmed'),', '.join(b.get('quality_flags',[])),p.get('capture_delay_seconds'),
            '; '.join(ce.get('warnings',[])), '; '.join(pe.get('warnings',[]))])
        date=str(at.astimezone(IST).date());counts.setdefault(date,{'CAPTURED':0,'MISSING':0})[status]+=1
    ws.freeze_panes='E2';ws.auto_filter.ref=ws.dimensions
    for c in ws[1]: c.font=Font(bold=True,color='FFFFFF');c.fill=PatternFill('solid',fgColor='16324F')
    for i in range(1,ws.max_column+1):ws.column_dimensions[get_column_letter(i)].width=26 if i not in (9,10,11,22,23) else 65
    for row in ws.iter_rows(min_row=2):
        for c in row[:3]:c.number_format='yyyy-mm-dd hh:mm:ss'
    coverage=wb.create_sheet('Collection Coverage',1);coverage.append(['Date','Captured','Missing','Coverage of elapsed buckets %'])
    for date,c in sorted(counts.items()):coverage.append([date,c['CAPTURED'],c['MISSING'],round(100*c['CAPTURED']/sum(c.values()),1)])
    coverage.append(['Note','Only sessions observed by collector appear. Absence of a session is not proof of a holiday.'])
    coverage.column_dimensions['A'].width=18;coverage.column_dimensions['B'].width=95

def register(app, provider):
    @app.post('/api/signal-journal/collect')
    def monitor(request: Request):
        require_secret(request)
        try:
            return collect(provider)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception('Completed-candle collector failed')
            raise HTTPException(503,'Collection failed; inspect server logs') from exc


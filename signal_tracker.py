"""NIFTY AI observational signal journal. Browser-triggered, not a trading execution engine."""
import os, io, csv, re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import psycopg
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

IST=ZoneInfo('Asia/Kolkata')
DDL='''CREATE TABLE IF NOT EXISTS nifty_signal_journal (
 id BIGSERIAL PRIMARY KEY, observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 market_date DATE NOT NULL, session_key TEXT NOT NULL,
 signal TEXT NOT NULL CHECK(signal IN ('BUY CE','BUY PE','WAIT')),
 nifty_price NUMERIC(14,2), confidence NUMERIC(6,2),
 suggested_option TEXT, source TEXT NOT NULL DEFAULT 'dashboard',
 UNIQUE(market_date,session_key,signal)
); CREATE INDEX IF NOT EXISTS ix_nifty_signal_journal_date ON nifty_signal_journal(market_date,observed_at);'''

def connect():
    dsn=os.getenv('DATABASE_URL')
    if not dsn: raise RuntimeError('DATABASE_URL is not configured')
    return psycopg.connect(dsn)

def setup():
    with connect() as conn:
        with conn.cursor() as cur: cur.execute(DDL)

def register(app):
    @app.post('/api/signal-journal/observe')
    async def observe(request: Request):
        # This records what a dashboard visitor saw. Do not interpret as a server-generated live signal.
        try:
            payload=await request.json()
            signal=str(payload.get('signal','')).strip().upper()
            if signal not in ('BUY CE','BUY PE','WAIT'): raise HTTPException(422,'Invalid signal')
            raw_price=payload.get('nifty_price'); raw_conf=payload.get('confidence')
            price=float(raw_price) if raw_price is not None else None
            conf=float(raw_conf) if raw_conf is not None else None
            if price is not None and not 1000 <= price <= 100000: raise HTTPException(422,'Invalid price')
            if conf is not None and not 0 <= conf <= 100: raise HTTPException(422,'Invalid confidence')
            option=re.sub(r'[^\w .\-/]','',str(payload.get('suggested_option','')))[:100]
            now=datetime.now(IST)
            # One observation per signal per five-minute bucket; retains transitions and avoids polling duplicates.
            bucket=now.strftime('%H:')+str((now.minute//5)*5).zfill(2)
            setup()
            with connect() as conn:
                with conn.cursor() as cur:
                    cur.execute('''INSERT INTO nifty_signal_journal(market_date,session_key,signal,nifty_price,confidence,suggested_option)
                      VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(market_date,session_key,signal) DO NOTHING RETURNING id''',
                      (now.date(),bucket,signal,price,conf,option))
                    row=cur.fetchone()
            return {'status':'success','recorded':bool(row),'note':'Browser-observed signal; timestamps are observation times, not first detection times.'}
        except HTTPException: raise
        except Exception as e: raise HTTPException(503,'Signal journal unavailable') from e

    @app.get('/api/signal-journal/export.csv')
    def export_csv(date: str=''):
        # Privacy: restrict export in production using existing app authentication before enabling for public use.
        if not os.getenv('SIGNAL_EXPORT_KEY'):
            raise HTTPException(503,'Set SIGNAL_EXPORT_KEY to enable export')
        # Authentication is handled by proxy in the install script below; this endpoint is intentionally disabled by default.
        raise HTTPException(403,'Use authenticated export endpoint')

    @app.get('/api/signal-journal/export.xlsx')
    def export_excel(request: Request, date: str=''):
        key=os.getenv('SIGNAL_EXPORT_KEY')
        if not key or request.headers.get('X-Signal-Export-Key')!=key: raise HTTPException(403,'Export authorization required')
        if date and not re.fullmatch(r'\d{4}-\d{2}-\d{2}',date): raise HTTPException(422,'Invalid date')
        try:
            setup()
            with connect() as conn:
                with conn.cursor() as cur:
                    if date: cur.execute('SELECT id,observed_at,market_date,session_key,signal,nifty_price,confidence,suggested_option,source FROM nifty_signal_journal WHERE market_date=%s ORDER BY observed_at',(date,))
                    else: cur.execute('SELECT id,observed_at,market_date,session_key,signal,nifty_price,confidence,suggested_option,source FROM nifty_signal_journal ORDER BY observed_at DESC LIMIT 10000')
                    rows=cur.fetchall()
            # openpyxl only used at request time to produce user-requested Excel export.
            from openpyxl import Workbook
            from openpyxl.styles import Font,PatternFill
            wb=Workbook();ws=wb.active;ws.title='Signal History'
            headers=['ID','Observed At (IST)','Market Date','5m Bucket','Call','NIFTY at Observation','Confidence %','Suggested Option','Source']
            ws.append(headers)
            for row in rows:
                rid,at,day,bucket,sig,price,conf,opt,src=row
                ws.append([rid,at.astimezone(IST).strftime('%Y-%m-%d %H:%M:%S'),str(day),bucket,sig,float(price) if price is not None else None,float(conf) if conf is not None else None,opt,src])
            ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
            for c in ws[1]:c.font=Font(bold=True,color='FFFFFF');c.fill=PatternFill('solid',fgColor='16324F')
            for col,width in {'A':10,'B':24,'C':16,'D':14,'E':14,'F':25,'G':18,'H':26,'I':18}.items():ws.column_dimensions[col].width=width
            output=io.BytesIO();wb.save(output);output.seek(0)
            return StreamingResponse(output,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':'attachment; filename="nifty_signal_history.xlsx"'})
        except HTTPException: raise
        except Exception as e: raise HTTPException(503,'Signal journal export unavailable') from e

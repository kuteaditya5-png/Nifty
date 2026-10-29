"""NIFTY AI observational signal journal. Browser-triggered, not a trading execution engine."""
import os, io, csv, re, hmac
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
            if now.weekday()>=5 or not ('09:15'<=now.strftime('%H:%M')<='15:30'):
                return {'status':'skipped','recorded':False,'note':'Outside regular market hours'}
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
        if not key or not hmac.compare_digest(request.headers.get('X-Signal-Export-Key',''),key): raise HTTPException(403,'Export authorization required')
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
            headers=['ID','Observed At (IST)','Market Date','5m Bucket','Call','NIFTY at Observation','Confidence %','Candidate Option (not trade)','Source','Trade Executable','Market Session']
            ws.append(headers)
            for row in rows:
                rid,at,day,bucket,sig,price,conf,opt,src=row
                ws.append([rid,at.astimezone(IST).strftime('%Y-%m-%d %H:%M:%S'),str(day),bucket,sig,float(price) if price is not None else None,float(conf) if conf is not None else None,opt,src,'NO' if sig=='WAIT' else 'SIGNAL ONLY','MARKET' if '09:15'<=at.astimezone(IST).strftime('%H:%M')<='15:30' else 'OUTSIDE MARKET'])
            ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
            for c in ws[1]:c.font=Font(bold=True,color='FFFFFF');c.fill=PatternFill('solid',fgColor='16324F')
            for col,width in {'A':10,'B':24,'C':16,'D':14,'E':14,'F':25,'G':18,'H':26,'I':18,'J':19,'K':20}.items():ws.column_dimensions[col].width=width
            notes=wb.create_sheet('Read Me')
            for item in [('Purpose','Browser-observed decisions, not executed trades'),('WAIT','No trade; displayed option is only a candidate'),('Price','NIFTY spot at observation when available; older observations may be blank'),('Accuracy','Do not infer trading accuracy from WAIT decisions'),('Coverage','Signals are logged only while dashboard is open; no automatic backfill'),('Time zone','Asia/Kolkata (IST)'),('Source','Dashboard observation; not independently verified')]:notes.append(item)
            notes.column_dimensions['A'].width=22;notes.column_dimensions['B'].width=95
            output=io.BytesIO();wb.save(output);output.seek(0)
            return StreamingResponse(output,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':'attachment; filename="nifty_signal_history.xlsx"'})
        except HTTPException: raise
        except Exception as e: raise HTTPException(503,'Signal journal export unavailable') from e

    @app.get('/api/signal-journal/candles.xlsx')
    def export_chart_candles(request: Request, date: str='', interval: str='5m'):
        """Export historical NIFTY OHLCV candles with exchange-local timestamps.
        This independently fetches market data; it does not export chart pixels.
        """
        key=os.getenv('SIGNAL_EXPORT_KEY')
        if not key or not hmac.compare_digest(request.headers.get('X-Signal-Export-Key',''),key):
            raise HTTPException(403,'Export authorization required')
        if interval not in ('1m','5m','15m'):
            raise HTTPException(422,'Interval must be 1m, 5m or 15m')
        from datetime import date as date_type, timedelta
        try:
            day=date_type.fromisoformat(date) if date else datetime.now(IST).date()
        except ValueError:
            raise HTTPException(422,'Date must be YYYY-MM-DD')
        if day>datetime.now(IST).date():
            raise HTTPException(422,'Future date is not available')
        if day < datetime.now(IST).date()-timedelta(days=6 if interval=='1m' else 58):
            raise HTTPException(422,'Date exceeds typical Yahoo intraday history window; use stored candle history if available')
        try:
            import yfinance as yf
            import pandas as pd
            start=datetime.combine(day,datetime.min.time(),tzinfo=IST)
            end=start+timedelta(days=1)
            df=yf.Ticker('^NSEI').history(start=start,end=end,interval=interval,auto_adjust=False)
            if df is None or df.empty:
                raise HTTPException(404,'No candles returned for this date (market closed or provider unavailable)')
            if df.index.tz is None:
                raise HTTPException(503,'Market data lacks timezone information; cannot safely label timestamps')
            df=df.sort_index()
            df.index=df.index.tz_convert(IST)
            df=df[df.index.date==day]
            now=pd.Timestamp.now(tz='Asia/Kolkata')
            duration=pd.Timedelta(minutes=int(interval[:-1]))
            df=df[(df.index+duration)<=now]
            df=df.between_time('09:15','15:29')
            if df.empty: raise HTTPException(404,'No completed market-session candles available')
            from openpyxl import Workbook
            from openpyxl.styles import Font, PatternFill
            from openpyxl.chart import StockChart, Reference
            wb=Workbook(); ws=wb.active; ws.title='NIFTY OHLCV'
            ws.append(['Candle Start (IST)','Candle End (IST)','Open','High','Low','Close','Volume'])
            for ts,row in df.iterrows():
                st=ts.to_pydatetime().replace(tzinfo=None)
                et=(ts+duration).to_pydatetime().replace(tzinfo=None)
                def val(k):
                    v=row.get(k)
                    return float(v) if v is not None and pd.notna(v) else None
                ws.append([st,et,val('Open'),val('High'),val('Low'),val('Close'),(val('Volume') if val('Volume') not in (0,None) else None)])
            ws.freeze_panes='C2';ws.auto_filter.ref=ws.dimensions
            for cell in ws[1]:
                cell.font=Font(bold=True,color='FFFFFF')
                cell.fill=PatternFill('solid',fgColor='16324F')
            for col in 'AB': ws.column_dimensions[col].width=24
            for col in 'CDEFG': ws.column_dimensions[col].width=16
            for row in ws.iter_rows(min_row=2):
                row[0].number_format='yyyy-mm-dd hh:mm:ss'
                row[1].number_format='yyyy-mm-dd hh:mm:ss'
                for c in row[2:6]: c.number_format='#,##0.00'
                row[6].number_format='#,##0'
            notes=wb.create_sheet('Source & Notes')
            for item in [
                ('Instrument','NIFTY 50 spot index (^NSEI)'),
                ('Provider','Yahoo Finance via yfinance'),
                ('Market date (IST)',str(day)),
                ('Interval',interval),
                ('Timestamp meaning','Start and end of each candle, Asia/Kolkata (IST)'),
                ('Completed candles only','Yes; incomplete current candle excluded'),
                ('Source limitation','Fetched at export time; may differ from chart feed or previously displayed candles'),
                ('Data limitations','Zero/unavailable index volume shown blank; no option premiums included'),
                ('Timezone','IST (UTC+05:30)'),
                ('Rows',len(df)),
            ]: notes.append(item)
            notes.column_dimensions['A'].width=30;notes.column_dimensions['B'].width=100
            output=io.BytesIO();wb.save(output);output.seek(0)
            filename=f'nifty_candles_{day}_{interval}.xlsx'
            return StreamingResponse(output,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':f'attachment; filename="{filename}"'})
        except HTTPException: raise
        except Exception as e:
            raise HTTPException(503,'Candle export unavailable; check market-data provider and server logs') from e

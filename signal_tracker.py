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
            headers=['Candle Start (IST)','Candle End (IST)','Open','High','Low','Close','Volume',
                'Volume Status','Candle Type','Body Points','Range Points','Upper Wick Points','Lower Wick Points',
                'Body %','Upper Wick %','Lower Wick %','Close Position %','Candle Change %',
                'Higher High','Higher Low','Lower High','Lower Low','Consecutive Bullish','Consecutive Bearish',
                'Previous 6 High','Previous 6 Low','Breakout Status','Inside/Outside Bar',
                'Range vs Prior 6 Avg','Candle Pattern','Candle Strength Score','Upper Rejection','Lower Rejection']
            ws.append(headers)
            history=[]; bullish_run=0; bearish_run=0
            def safe_pct(part,whole):
                return round(100.0*part/whole,2) if whole>0 else None
            for ts,row in df.iterrows():
                st=ts.to_pydatetime().replace(tzinfo=None)
                et=(ts+duration).to_pydatetime().replace(tzinfo=None)
                def val(k):
                    v=row.get(k)
                    return float(v) if v is not None and pd.notna(v) else None
                o,h,l,c,v=(val(k) for k in ('Open','High','Low','Close','Volume'))
                if any(x is None for x in (o,h,l,c)) or h<l or h<max(o,c) or l>min(o,c):
                    # Keep original provider values visible, but do not invent candle features.
                    ws.append([st,et,o,h,l,c,v,'UNAVAILABLE' if v in (None,0) else 'AVAILABLE'])
                    history.append(None);bullish_run=bearish_run=0
                    continue
                rng=max(0.0,h-l);body=abs(c-o);upper=max(0.0,h-max(o,c));lower=max(0.0,min(o,c)-l)
                candle_type='BULLISH' if c>o else 'BEARISH' if c<o else 'DOJI'
                bullish_run=bullish_run+1 if c>o else 0
                bearish_run=bearish_run+1 if c<o else 0
                prev=history[-1] if history else None
                valid_prior=[r for r in history[-6:] if r is not None]
                six_high=max((r['h'] for r in valid_prior),default=None) if len(valid_prior)==6 else None
                six_low=min((r['l'] for r in valid_prior),default=None) if len(valid_prior)==6 else None
                breakout=('ABOVE PRIOR 6 HIGH' if six_high is not None and c>six_high else
                          'BELOW PRIOR 6 LOW' if six_low is not None and c<six_low else 'NONE')
                relation=('INSIDE' if prev and h<=prev['h'] and l>=prev['l'] else
                          'OUTSIDE' if prev and h>=prev['h'] and l<=prev['l'] else 'NEITHER') if prev else 'N/A'
                avg_range=sum(r['range'] for r in valid_prior)/6 if len(valid_prior)==6 else None
                ratio=round(rng/avg_range,2) if avg_range and avg_range>0 else None
                body_pct=safe_pct(body,rng);up_pct=safe_pct(upper,rng);low_pct=safe_pct(lower,rng)
                close_pos=safe_pct(c-l,rng)
                # Heuristic shape labels, not confirmed reversals or trading signals.
                if rng==0: pattern='FLAT / ZERO RANGE'
                elif body_pct is not None and body_pct<=10: pattern='DOJI-LIKE'
                elif lower>=2*body and low_pct>=50 and up_pct<=20: pattern='HAMMER-LIKE / LONG LOWER WICK'
                elif upper>=2*body and up_pct>=50 and low_pct<=20: pattern='SHOOTING-STAR-LIKE / LONG UPPER WICK'
                elif body_pct>=80 and up_pct<=10 and low_pct<=10: pattern='MARUBOZU-LIKE'
                elif body_pct>=65: pattern='STRONG BODY'
                else: pattern='STANDARD'
                strength=round(body_pct * (close_pos/100 if c>o else (100-close_pos)/100 if c<o else 0),1) if body_pct is not None and close_pos is not None else None
                ws.append([st,et,o,h,l,c,v if v not in (None,0) else None,
                    'UNAVAILABLE (INDEX)' if v in (None,0) else 'AVAILABLE',candle_type,
                    round(body,2),round(rng,2),round(upper,2),round(lower,2),
                    body_pct,up_pct,low_pct,close_pos,round(100*(c-o)/o,4) if o else None,
                    'YES' if prev and h>prev['h'] else 'NO' if prev else 'N/A',
                    'YES' if prev and l>prev['l'] else 'NO' if prev else 'N/A',
                    'YES' if prev and h<prev['h'] else 'NO' if prev else 'N/A',
                    'YES' if prev and l<prev['l'] else 'NO' if prev else 'N/A',
                    bullish_run,bearish_run,six_high,six_low,breakout,relation,ratio,pattern,
                    strength,'YES' if up_pct is not None and up_pct>=50 else 'NO',
                    'YES' if low_pct is not None and low_pct>=50 else 'NO'])
                history.append({'h':h,'l':l,'range':rng})
            ws.freeze_panes='C2';ws.auto_filter.ref=ws.dimensions
            for cell in ws[1]:
                cell.font=Font(bold=True,color='FFFFFF')
                cell.fill=PatternFill('solid',fgColor='16324F')
            from openpyxl.utils import get_column_letter
            for idx,title in enumerate(headers,1):
                ws.column_dimensions[get_column_letter(idx)].width=(25 if 'Candle' in title or 'Pattern' in title or 'Status' in title else 20 if 'Rejection' in title or 'Breakout' in title else 17)
            for r in ws.iter_rows(min_row=2):
                for c in r[:2]:c.number_format='yyyy-mm-dd hh:mm:ss'
                for c in r[2:7]:c.number_format='#,##0.00'
                for idx in (10,11,12,13,25,26):r[idx-1].number_format='#,##0.00'
                for idx in (14,15,16,17,18,31):r[idx-1].number_format='0.00'
                r[6].number_format='#,##0'
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
                ('Candle features','Derived from completed OHLC candles only; no volume proxy or prediction changes'),
                ('Pattern labels','Shape heuristics only; not confirmed reversal or trading advice'),
                ('Strength score','0-100 body dominance weighted by close position in candle direction; not model confidence'),
                ('Prior 6 breakout','Uses exactly six preceding valid candles; blank until six exist'),
                ('Percent fields','Percentage-point numbers (e.g. 75 means 75%), not Excel percent fractions'),
                ('Missing data','Features left blank if OHLC is missing or inconsistent'),
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

"""Five-minute direction audit. Research output only; never changes live trade gates.

Predictions use prefix-only OHLC features. Outcomes are attached afterward.
Live payloads are immutable first captures; replay never fills a missing live call.
"""
import logging
import math
from datetime import datetime, timedelta
import pandas as pd
from psycopg.types.json import Jsonb
import breakout_v1814 as breakout
import prediction_v1812 as shadow
import signal_tracker

IST = breakout.IST
VERSION = '18.15-next-candle-audit'
HEADERS = [
    'EMA20','EMA50','RSI14','MACD','MACD Signal','MACD Histogram','ATR14',
    'OR High','OR Low','OR Breakout Direction','Breakout Confirmed','Breakout Distance Points',
    'Prediction Recorded At (IST)','Prediction Candle End (IST)','Next Candle Prediction',
    'Base Confidence %','Breakout Adjustment','Final Confidence %','Prediction Reason','Engine Version',
    'Trade Call','WAIT Reason','Failed Gates','Option Data Available',
    'Next Candle Start (IST)','Next Open','Next High','Next Low','Next Close','Next Candle Colour',
    'Next Close Change Points','Next Close Change %','Next Upward Excursion Points',
    'Next Downward Excursion Points','Actual Next Direction','Prediction Result','Prediction Source',
    'Prediction Data Age Seconds','Next Candle Quality Eligible','Evaluation Status','Neutral Threshold Points',
    'Live Market Prediction','Live Market Confidence %','Live Base Score','Live Breakout Score Adjustment',
    'Live Adjusted Score','Shadow Trade Call','Prediction Reference Close','Export Close Difference Points',
    'Breakout Direction','Next Candle Quality Flags','Audit Storage Status']
DDL = '''CREATE TABLE IF NOT EXISTS nifty_candle_audit_v1815 (
 candle_at TIMESTAMPTZ PRIMARY KEY,
 recorded_at TIMESTAMPTZ NOT NULL,
 payload JSONB NOT NULL
);'''

def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None

def timestamp(value):
    t = pd.Timestamp(value)
    if t.tzinfo is None:
        raise ValueError('Timezone is required')
    return t.tz_convert(IST)

def replay_predictions(frame):
    """Return research predictions, with no future values in their inputs/payloads."""
    if frame.empty:
        return {}
    df = breakout.completed(frame, timestamp(frame.index[-1]) + pd.Timedelta(minutes=5))
    records = breakout.analyze(df, df.index[-1] + pd.Timedelta(minutes=5))['records']
    # The shadow evaluator computes ex-post fields too. Only explicitly selected
    # current-candle features below may enter the audit prediction.
    shadow_rows, _ = shadow.evaluate(df, horizon=1)
    research = {timestamp(r['time']).isoformat(): r for r in shadow_rows}
    close = df.Close
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    macd = close.ewm(span=12, adjust=False).mean()-close.ewm(span=26, adjust=False).mean()
    signal = macd.ewm(span=9, adjust=False).mean()
    quality = breakout.quality_flags(df)
    result = {}
    for b in records:
        key = b['candle_at']; ts = timestamp(key); r = research.get(key)
        # A gap in the current session or a flagged bar in the last 50 bars
        # prevents indicator contamination from being presented as valid evidence.
        prefix = df.loc[:ts]; recent = prefix.tail(50)
        current_session = prefix[prefix.index.date == ts.date()]
        gap = any(d != pd.Timedelta(minutes=5) for d in current_session.index.to_series().diff().dropna())
        bad_context = any(quality.get(t.isoformat()) for t in recent.index)
        eligible = bool(r and not gap and not bad_context)
        base = (r['up_score']-r['down_score'])/4 if eligible else None
        if base is not None:
            adjusted, adj = breakout.adjust_score(base, {'eligible':True, 'latest':b})
            direction = 'UP' if adjusted > .125 else 'DOWN' if adjusted < -.125 else 'NEUTRAL'
            reason = f"Shadow evidence UP {r['up_score']}/4; DOWN {r['down_score']}/4. {b['reason']}"
        else:
            adjusted = None; adj = {'adjustment':None}; direction = None
            reason = 'Insufficient warm-up (50 prior candles), session gap or flagged indicator context'
        orb = next((e['direction'] for e in b['events'] if e['kind']=='ORB' and e['direction'] in ('UP','DOWN')), 'NONE')
        event = next((e for e in b['events'] if e['direction'] in ('UP','DOWN')), None)
        result[key] = {
            'engine_version':VERSION, 'candle_at':key, 'candle_end':b['candle_end'],
            'direction':direction, 'base_confidence':round(abs(base)*100,2) if base is not None else None,
            'adjustment':round((abs(adjusted)-abs(base))*100,2) if base is not None else None,
            'confidence':round(abs(adjusted)*100,2) if adjusted is not None else None,
            'reason':reason, 'reference_close':number(b['close']), 'neutral_threshold':2.0,
            'ema20':number(ema20.loc[ts]) if eligible else None, 'ema50':number(ema50.loc[ts]) if eligible else None,
            'rsi14':r['rsi'] if eligible else None, 'macd':number(macd.loc[ts]) if eligible else None,
            'macd_signal':number(signal.loc[ts]) if eligible else None,
            'macd_histogram':number(macd.loc[ts]-signal.loc[ts]) if eligible else None,
            'atr14':r['atr'] if eligible else None,
            'orb_high':b['orb_high'], 'orb_low':b['orb_low'], 'orb_direction':orb,
            'breakout_direction':b['direction'], 'confirmed':b['confirmed'],
            'distance':round(abs(b['close']-event['level']),2) if event else 0,
            'quality_flags':b['quality_flags'], 'shadow_trade':r['decision'] if eligible else None,
            'model_note':'Audit direction/strength only, not a calibrated next-candle probability or the live trade model.'}
    return result

def save_live(snapshot, recorded_at=None):
    """Persist the first complete server-generated prediction; never overwrite it."""
    if snapshot.get('status') != 'success' or not snapshot.get('next_candle_audit'):
        return 'NOT AVAILABLE'
    now = timestamp(recorded_at or datetime.now(IST)); at = timestamp(snapshot['candle_at'])
    if now.date() != at.date() or not 0 <= (now-at-pd.Timedelta(minutes=5)).total_seconds() < 300:
        return 'SKIPPED STALE OR OUTSIDE TARGET CANDLE'
    try:
        with signal_tracker.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(DDL)
                cur.execute('''INSERT INTO nifty_candle_audit_v1815(candle_at,recorded_at,payload)
                    VALUES(%s,%s,%s) ON CONFLICT(candle_at) DO NOTHING RETURNING candle_at''',
                    (at.to_pydatetime(),now.to_pydatetime(),Jsonb(snapshot)))
                saved = cur.fetchone() is not None
        return 'SAVED' if saved else 'FIRST CAPTURE ALREADY SAVED'
    except Exception:
        logging.getLogger(__name__).exception('Next-candle audit storage unavailable')
        return 'UNAVAILABLE: CHECK DATABASE_URL / SERVER LOGS'

def load_live(day):
    try:
        with signal_tracker.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(DDL)
                cur.execute('''SELECT candle_at,recorded_at,payload FROM nifty_candle_audit_v1815
                    WHERE (candle_at AT TIME ZONE 'Asia/Kolkata')::date=%s ORDER BY candle_at''',(day,))
                return {timestamp(at).isoformat():(at,recorded,payload) for at,recorded,payload in cur.fetchall()}, 'AVAILABLE'
    except Exception:
        logging.getLogger(__name__).exception('Next-candle audit read unavailable')
        return {}, 'UNAVAILABLE: export contains REPLAY only; check DATABASE_URL / server logs'

def joined_rows(frame, predictions, live=None, storage_status='AVAILABLE', mode='auto', now=None):
    """Attach an exact next 5m bar, never a later available bar or next session."""
    live = live or {}; now = timestamp(now or datetime.now(IST))
    flags = breakout.quality_flags(frame); output = {}
    for ts, candle in frame.iterrows():
        key = timestamp(ts).isoformat(); end = ts+pd.Timedelta(minutes=5)
        record = live.get(key) if mode != 'replay' else None
        payload = record[2] if record else {}
        audit = payload.get('next_candle_audit', {}) if record else predictions.get(key, {}) if mode != 'live' else {}
        direction = audit.get('direction')
        source = 'LIVE' if record else 'REPLAY' if audit else 'MISSING'
        captured = timestamp(record[1]) if record else None
        delay = (captured-end).total_seconds() if captured is not None else None
        ref = number(audit.get('reference_close'))
        exported = number(candle.Close)
        difference = round(exported-ref,6) if exported is not None and ref is not None else None
        next_at = end
        next_bar = frame.loc[next_at] if next_at in frame.index and next_at.date()==ts.date() else None
        next_flags = flags.get(next_at.isoformat(), []) if next_bar is not None else []
        usable = next_bar is not None and not next_flags
        if end.time() >= datetime.strptime('15:30','%H:%M').time():
            status = 'SESSION END'
        elif not direction:
            status = 'MISSING PREDICTION' if not audit else 'INSUFFICIENT VALID CONTEXT'
        elif flags.get(key) or audit.get('quality_flags') or next_flags:
            status = 'EXCLUDED DATA QUALITY'
        elif source == 'LIVE' and difference is not None and abs(difference) > .01:
            status = 'REVISED SOURCE DATA'
        elif captured is not None and delay < 0:
            status = 'INVALID CAPTURE TIME'
        elif captured is not None and delay > 0:
            status = 'LATE CAPTURE'
        elif next_bar is None:
            status = 'PENDING' if now < end+pd.Timedelta(minutes=5) else 'MISSING NEXT CANDLE'
        elif ref is None:
            status = 'EXCLUDED DATA QUALITY'
        else:
            status = 'EVALUATED'
        threshold = number(audit.get('neutral_threshold'))
        threshold = 2.0 if threshold is None else threshold
        delta = round(float(next_bar.Close)-ref,6) if usable and ref is not None else None
        actual = ('NEUTRAL' if abs(delta) <= threshold else 'UP' if delta>0 else 'DOWN') if delta is not None else None
        adj = payload.get('breakout_adjustment') or {}
        alerts = payload.get('fno_alerts') or {}
        ce = (alerts.get('call') or {}).get('signal'); pe = (alerts.get('put') or {}).get('signal')
        trade = ('BUY CE + BUY PE' if ce=='BUY CE' and pe=='BUY PE' else 'BUY CE' if ce=='BUY CE' else 'BUY PE' if pe=='BUY PE' else 'WAIT') if alerts else 'NOT RECORDED'
        gates = payload.get('failed_gates') or {}
        vals = {
            'EMA20':audit.get('ema20'), 'EMA50':audit.get('ema50'), 'RSI14':audit.get('rsi14'),
            'MACD':audit.get('macd'), 'MACD Signal':audit.get('macd_signal'),'MACD Histogram':audit.get('macd_histogram'),'ATR14':audit.get('atr14'),
            'OR High':audit.get('orb_high'),'OR Low':audit.get('orb_low'),'OR Breakout Direction':audit.get('orb_direction'),
            'Breakout Confirmed':('YES' if audit.get('confirmed') else 'NO') if audit else None,
            'Breakout Distance Points':audit.get('distance'),
            'Prediction Recorded At (IST)':captured.to_pydatetime().replace(tzinfo=None) if captured is not None else None,
            'Prediction Candle End (IST)':end.to_pydatetime().replace(tzinfo=None) if audit else None,
            'Next Candle Prediction':direction,'Base Confidence %':audit.get('base_confidence'),
            'Breakout Adjustment':audit.get('adjustment'),'Final Confidence %':audit.get('confidence'),
            'Prediction Reason':audit.get('reason'),'Engine Version':audit.get('engine_version'),
            'Trade Call':trade,'WAIT Reason':payload.get('fno_setup_reason') if trade=='WAIT' else None,
            'Failed Gates':'; '.join(f"{side}: {', '.join(names)}" for side,names in gates.items()) if gates else None,
            'Option Data Available':('YES' if payload.get('option_data_available') else 'NO') if record else None,
            'Next Candle Start (IST)':next_at.to_pydatetime().replace(tzinfo=None) if next_bar is not None else None,
            'Next Candle Colour':('BULLISH' if next_bar.Close>next_bar.Open else 'BEARISH' if next_bar.Close<next_bar.Open else 'DOJI') if usable else None,
            'Next Close Change Points':delta,'Next Close Change %':round(delta/ref*100,6) if delta is not None and ref else None,
            'Next Upward Excursion Points':max(0,float(next_bar.High)-ref) if usable and ref is not None else None,
            'Next Downward Excursion Points':max(0,ref-float(next_bar.Low)) if usable and ref is not None else None,
            'Actual Next Direction':actual,'Prediction Result':('CORRECT' if direction==actual else 'INCORRECT') if status=='EVALUATED' else None,
            'Prediction Source':source,'Prediction Data Age Seconds':round(delay,3) if delay is not None else None,
            'Next Candle Quality Eligible':('YES' if usable else 'NO') if next_bar is not None else None,
            'Evaluation Status':status,'Neutral Threshold Points':threshold,
            'Live Market Prediction':payload.get('prediction'),'Live Market Confidence %':payload.get('confidence'),
            'Live Base Score':adj.get('base_score'),'Live Breakout Score Adjustment':adj.get('adjustment'),'Live Adjusted Score':adj.get('adjusted_score'),
            'Shadow Trade Call':audit.get('shadow_trade'),'Prediction Reference Close':ref,'Export Close Difference Points':difference,
            'Breakout Direction':audit.get('breakout_direction'),'Next Candle Quality Flags':', '.join(next_flags) or ('OK' if next_bar is not None else None),
            'Audit Storage Status':storage_status}
        for name in ('Open','High','Low','Close'):
            vals['Next '+name] = number(next_bar[name]) if next_bar is not None else None
        output[key] = vals
    return output

def append_to_workbook(wb, ws, frame, context, day, mode='auto'):
    """Uses the application's existing Excel writer; does not alter original columns."""
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    live, storage_status = load_live(day) if mode != 'replay' else ({}, 'NOT REQUESTED (REPLAY MODE)')
    predictions = replay_predictions(context) if mode != 'live' else {}
    rows = joined_rows(frame, predictions, live, storage_status, mode)
    start = ws.max_column+1
    for c,name in enumerate(HEADERS,start):
        ws.cell(1,c,name)
        ws.cell(1,c).font=Font(bold=True,color='FFFFFF')
        ws.cell(1,c).fill=PatternFill('solid',fgColor='305E55')
        ws.cell(1,c).alignment=Alignment(wrap_text=True,vertical='center')
        ws.column_dimensions[get_column_letter(c)].width=28 if 'Reason' not in name and name!='Failed Gates' else 65
    for r,(ts,_) in enumerate(frame.iterrows(),2):
        for c,name in enumerate(HEADERS,start):
            value=rows[ts.isoformat()].get(name)
            # Never interpret provider strings or gate text as Excel formulas.
            if isinstance(value,str) and value.startswith(('=','+','-','@')): value="'"+value
            cell=ws.cell(r,c,value)
            if isinstance(value,datetime):cell.number_format='yyyy-mm-dd hh:mm:ss'
            elif isinstance(value,(int,float)):cell.number_format='0.00'
            if 'Reason' in name or name=='Failed Gates':cell.alignment=Alignment(wrap_text=True)
    ws.auto_filter.ref=ws.dimensions;ws.row_dimensions[1].height=48
    summary=wb.create_sheet('Prediction Review',0)
    summary.append(['Next five-minute candle direction review'])
    summary.append(['Scope','Audit direction model; LIVE and REPLAY kept separate. No option profit or trade win rate.'])
    summary.append(['Storage',storage_status])
    summary.append(['Mode',mode])
    summary.append(['Source','Rows','Evaluated','Correct','Incorrect','Accuracy %'])
    src=get_column_letter(start+HEADERS.index('Prediction Source'))
    status=get_column_letter(start+HEADERS.index('Evaluation Status'))
    result=get_column_letter(start+HEADERS.index('Prediction Result'))
    n=ws.max_row; sheet="'"+ws.title.replace("'","''")+"'!"
    for r,source in enumerate(('LIVE','REPLAY','MISSING'),6):
        summary.cell(r,1,source)
        summary.cell(r,2,f'=COUNTIF({sheet}{src}2:{src}{n},A{r})')
        summary.cell(r,3,f'=COUNTIFS({sheet}{src}2:{src}{n},A{r},{sheet}{status}2:{status}{n},"EVALUATED")')
        for c,label in [(4,'CORRECT'),(5,'INCORRECT')]:
            summary.cell(r,c,f'=COUNTIFS({sheet}{src}2:{src}{n},A{r},{sheet}{result}2:{result}{n},"{label}")')
        summary.cell(r,6,f'=IF(C{r}=0,"",D{r}/C{r}*100)').number_format='0.0'
    summary.append([])
    for line in [
        ('Direction model',VERSION+'; existing shadow evidence margin (UP minus DOWN)/4, plus bounded existing breakout adjustment.'),
        ('Direction cutoff','UP above +0.125, DOWN below -0.125, otherwise NEUTRAL. Research heuristic; live trade rules unchanged.'),
        ('Confidence','Absolute audit score x 100. Breakout Adjustment is the change in strength in percentage points, not a win probability.'),
        ('Outcome','Next close minus reference close; within ±2 points is NEUTRAL. This research threshold is versioned, not validated.'),
        ('Live timing','First snapshot is immutable. Capture after target candle begins is LATE CAPTURE and excluded from full-candle accuracy.'),
        ('Replay','As-of-candle-close OHLC-only calculation, with prior-session warm-up; no historical news/options reconstructed.'),
        ('Trade Call','Recorded live CE/PE alert only. NOT RECORDED when no alert snapshot exists; Shadow Trade Call is separate research output.'),
        ('Data checks','Exact next 5m bar only; session ends, missing bars, invalid context, source revisions and late captures are not scored.'),
        ('Collection','Dashboard predictions save snapshots when DATABASE_URL works. Configure existing monitor for dashboard-closed collection.'),
        ('Gaps','No historical live prediction is fabricated. Auto mode uses REPLAY for absent snapshots; live mode leaves them MISSING.'),
        ('Indicator warm-up','Export fetches preceding calendar days. Fewer than 50 prior candles or flagged recent context yields no direction.'),
        ('Source alignment','Joined by exact candle-start timestamp, never by observation minute or nearby price.'),
    ]: summary.append(line)
    summary.column_dimensions['A'].width=26; summary.column_dimensions['B'].width=46
    for c in 'CDEF':summary.column_dimensions[c].width=18
    for row in summary.iter_rows(min_row=10):
        summary.merge_cells(start_row=row[0].row,start_column=2,end_row=row[0].row,end_column=6)
        summary.cell(row[0].row,2).alignment=Alignment(wrap_text=True,vertical='center')
        summary.row_dimensions[row[0].row].height=34
    for r in (2,3,4):
        summary.merge_cells(start_row=r,start_column=2,end_row=r,end_column=6)
        summary.cell(r,2).alignment=Alignment(wrap_text=True);summary.row_dimensions[r].height=32
    for c in summary[5]:c.font=Font(bold=True,color='FFFFFF');c.fill=PatternFill('solid',fgColor='17365D')
    summary.freeze_panes='B6';summary.sheet_view.showGridLines=False
    return rows

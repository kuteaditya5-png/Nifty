"""v18.7 confirmed-candle entry gate. Research/paper alerts only; no orders."""
import os
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')

def evaluate(bars, prediction, now=None):
    now = now or datetime.now(IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    if bars is None or bars.empty:
        return {'status':'unavailable','action':'WAIT','reason':'No candles'}
    frame = bars.copy().sort_index()
    if frame.index.tz is None:
        frame.index = frame.index.tz_localize(IST)
    else:
        frame.index = frame.index.tz_convert(IST)
    frame = frame[frame.index + timedelta(minutes=5) <= now]
    frame = frame[frame.index.date == now.date()]
    if len(frame) < 4:
        return {'status':'unavailable','action':'WAIT','reason':'Not enough completed candles today'}
    if now.weekday() >= 5 or now.time() < time(9,30) or now.time() >= time(15,10):
        return {'status':'success','action':'WAIT','reason':'Outside new-entry window'}
    opening = frame[(frame.index.time >= time(9,15)) & (frame.index.time < time(9,30))]
    if len(opening) != 3:
        return {'status':'unavailable','action':'WAIT','reason':'Opening range incomplete or missing candles'}
    high, low = float(opening['High'].max()), float(opening['Low'].min())
    last = frame.iloc[-1]
    previous = frame.iloc[-2]
    close, prev_close = float(last['Close']), float(previous['Close'])
    candle_at = frame.index[-1].isoformat()
    raw = str(prediction.get('fno_setup') or prediction.get('prediction') or '').upper()
    # Never infer a CE/PE direction from an ambiguous prediction label.
    bullish = ('BUY CE' in raw or 'BUY_CALL' in raw or raw in ('BULLISH','CE WATCH'))
    bearish = ('BUY PE' in raw or 'BUY_PUT' in raw or raw in ('BEARISH','PE WATCH'))
    if bullish and bearish:
        bullish = bearish = False
    up = close > high and prev_close <= high
    down = close < low and prev_close >= low
    failed_up = float(last['High']) > high and close <= high
    failed_down = float(last['Low']) < low and close >= low
    if failed_up or failed_down:
        action, reason = 'WAIT', 'False breakout/rejection: candle closed back inside opening range'
    elif bullish and up:
        action, reason = 'BUY CE', 'Bullish prediction and completed 5m close above opening-range high'
    elif bearish and down:
        action, reason = 'BUY PE', 'Bearish prediction and completed 5m close below opening-range low'
    else:
        action, reason = 'WAIT', 'No new confirmed opening-range breakout aligned with prediction'
    return {'status':'success','action':action,'reason':reason,'opening_range_high':round(high,2),
            'opening_range_low':round(low,2),'last_close':round(close,2),
            'candle_at':candle_at,'base_prediction':raw,'false_breakout':bool(failed_up or failed_down),
            'source':'completed 5-minute NIFTY candles'}

def persist(result):
    import psycopg
    url = os.getenv('DATABASE_URL')
    if not url:
        return {'stored':False,'reason':'DATABASE_URL not configured'}
    if result.get('status') != 'success' or not result.get('candle_at'):
        return {'stored':False,'reason':'No eligible completed candle'}
    with psycopg.connect(url, connect_timeout=8) as conn:
        with conn.cursor() as cur:
            cur.execute('''CREATE TABLE IF NOT EXISTS nifty_v187_entry_events (
                candle_at timestamptz PRIMARY KEY, action text NOT NULL, reason text NOT NULL,
                payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now())''')
            from psycopg.types.json import Jsonb
            cur.execute('''INSERT INTO nifty_v187_entry_events(candle_at,action,reason,payload)
                VALUES (%s,%s,%s,%s) ON CONFLICT (candle_at) DO NOTHING RETURNING candle_at''',
                (result['candle_at'],result['action'],result['reason'],Jsonb(result)))
            inserted = cur.fetchone() is not None
    return {'stored':True,'new_event':inserted}

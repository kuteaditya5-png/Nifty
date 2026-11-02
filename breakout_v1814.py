"""Completed-candle breakout evidence. Scores are heuristics, not hit probabilities.

Opening-range reference: kuteaditya5-png/Stocklens lib/nifty-index.js,
commit 098c43aae37768479fc155138fe97aa685b39a01 (MIT).
Implementation adds rolling levels, rejection/quality checks and bounded confluence.
"""
from datetime import datetime, time
from zoneinfo import ZoneInfo
import math
import pandas as pd

IST = ZoneInfo('Asia/Kolkata')
VERSION = '18.14'

def completed(frame, now=None, minutes=5):
    now = pd.Timestamp(now or datetime.now(IST))
    now = now.tz_localize(IST) if now.tzinfo is None else now.tz_convert(IST)
    df = frame.copy().sort_index()
    if df.empty:
        return df
    if df.index.tz is None:
        raise ValueError('Candle timestamps must include a timezone')
    df.index = df.index.tz_convert(IST)
    if df.index.has_duplicates:
        raise ValueError('Duplicate candle timestamps')
    return df[(df.index + pd.Timedelta(minutes=minutes) <= now)].between_time('09:15', '15:29')

def quality_flags(frame):
    """Keep provider prices intact; flag, never repair, suspicious source bars."""
    flags = {}
    for i, (ts, r) in enumerate(frame.iterrows()):
        try:
            o,h,l,c = (float(r[k]) for k in ('Open','High','Low','Close'))
        except (TypeError, ValueError):
            flags[ts.isoformat()] = ['INVALID_OHLC']
            continue
        reasons = []
        if not all(math.isfinite(v) and v > 0 for v in (o,h,l,c)) or not l <= min(o,c) <= max(o,c) <= h:
            reasons.append('INVALID_OHLC')
        elif h == l:
            reasons.append('ZERO_RANGE')
        if i:
            prev = frame.iloc[i-1]
            prior = frame.iloc[max(0,i-6):i]
            typical = float((prior.High-prior.Low).median())
            # Specifically detect closing feed anomalies, not every large trend candle.
            if ts.time() >= time(15,15) and h-l > max(50, 4*typical):
                reasons.append('CLOSING_SPIKE_REVIEW')
            if abs(o-float(prev.Close)) > max(100, 6*typical) and ts.date() == frame.index[i-1].date():
                reasons.append('PRICE_GAP_REVIEW')
        flags[ts.isoformat()] = reasons
    return flags

def analyze(frame, now=None):
    now = pd.Timestamp(now or datetime.now(IST))
    now = now.tz_localize(IST) if now.tzinfo is None else now.tz_convert(IST)
    df = completed(frame, now)
    flags = quality_flags(df)
    records = []
    e9 = df.Close.ewm(span=9, adjust=False).mean()
    e21 = df.Close.ewm(span=21, adjust=False).mean()
    for day, session in df.groupby(df.index.date):
        opening_times = pd.date_range(pd.Timestamp(day, tz=IST)+pd.Timedelta(hours=9, minutes=15), periods=3, freq='5min')
        opening = session.reindex(opening_times)
        opening_ok = not opening[['Open','High','Low','Close']].isna().any().any() and not any(flags.get(t.isoformat()) for t in opening_times)
        for i, (ts,r) in enumerate(session.iterrows()):
            prior = session.iloc[max(0,i-6):i]
            contiguous = len(prior)==6 and all((session.index[j]-session.index[j-1])==pd.Timedelta(minutes=5) for j in range(i-5,i+1))
            prior_ok = contiguous and not any(flags[t.isoformat()] for t in prior.index)
            ph = float(prior.High.max()) if prior_ok else None
            pl = float(prior.Low.min()) if prior_ok else None
            ready = opening_ok and ts.time() >= time(9,30)
            oh = float(opening.High.max()) if ready else None
            ol = float(opening.Low.min()) if ready else None
            o,h,l,c = (float(r[k]) for k in ('Open','High','Low','Close'))
            q = flags[ts.isoformat()]
            typical = float((prior.High-prior.Low).mean()) if len(prior) else 0
            buffer = max(1.0, typical*.10)
            levels = [('ORB',oh,ol),('PRIOR6',ph,pl)]
            events = []
            prev_close = float(session.Close.iloc[i-1]) if i else c
            for kind, hi, lo in levels:
                if hi is None or q:
                    continue
                # Only a new cross is an event; remaining outside is context.
                if c > hi+buffer and prev_close <= hi+buffer:
                    events.append({'kind':kind,'direction':'UP','level':hi})
                elif c < lo-buffer and prev_close >= lo-buffer:
                    events.append({'kind':kind,'direction':'DOWN','level':lo})
                elif (h>hi and c<=hi) or (l<lo and c>=lo):
                    events.append({'kind':kind,'direction':'REJECTION','level':hi if h>hi and c<=hi else lo})
            direction = next((e['direction'] for e in events if e['direction']!='REJECTION'),'NONE')
            body = abs(c-o)/(h-l) if h>l else 0
            position = (c-l)/(h-l) if h>l else .5
            aligned = ((direction=='UP' and c>o and c>e9.loc[ts]>e21.loc[ts] and position>=.70)
                       or (direction=='DOWN' and c<o and c<e9.loc[ts]<e21.loc[ts] and position<=.30))
            confirmed = bool(direction!='NONE' and body>=.50 and aligned and not q and len(df.loc[:ts])>=21)
            records.append({'candle_at':ts.isoformat(),'candle_end':(ts+pd.Timedelta(minutes=5)).isoformat(),
                'time':int(ts.timestamp()),'close':c,'orb_high':oh,'orb_low':ol,'prior6_high':ph,'prior6_low':pl,
                'direction':direction,'confirmed':confirmed,'events':events,'quality_flags':q,
                'reason':'Completed breakout with body and EMA alignment' if confirmed else 'No confirmed breakout confluence',
                'buffer_points':round(buffer,2)})
    latest = records[-1] if records else None
    fresh = bool(latest and pd.Timestamp(latest['candle_at']).date()==now.date() and
                 0 <= (now-pd.Timestamp(latest['candle_end'])).total_seconds() <= 12*60)
    active = now.weekday()<5 and time(9,20)<=now.time()<=time(15,30)
    valid = bool(latest and not latest['quality_flags'])
    return {'version':VERSION,'latest':latest,'records':records,'fresh':fresh,'market_active':active,
            'eligible':bool(fresh and active and valid),'quality_flag_count':sum(bool(v) for v in flags.values()),
            'note':'Breakout strength is a rule score, not a calibrated probability. Index volume is not required.'}

def adjust_score(base, result):
    latest = result.get('latest') or {}
    delta = 0.0
    if result.get('eligible') and latest.get('confirmed'):
        side = 1 if latest['direction']=='UP' else -1
        # Correlated OHLC evidence gets one small adjustment, not two independent votes.
        if base*side >= .08:
            delta = .05*side
        elif base*side <= -.08:
            delta = .05*side  # reduce opposing conviction, never flip direction
    adjusted = max(-1.,min(1.,base+delta))
    return adjusted, {'base_score':round(base,4),'adjustment':round(adjusted-base,4),
                      'adjusted_score':round(adjusted,4),'calibrated_probability':False}

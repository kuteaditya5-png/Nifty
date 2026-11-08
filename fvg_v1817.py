"""Causal 5m FVG detection and bounded call/strength integration.

Zones are same-session only. A close beyond the far edge inverts once;
a subsequent close through the inverse far edge invalidates it.
"""
from copy import deepcopy
from datetime import datetime, time
import pandas as pd
import breakout_v1814 as breakout

VERSION = '18.17.1'
HEADERS = ['FVG Source', 'FVG Type', 'FVG Status', 'FVG Lower', 'FVG Upper',
           'FVG Midpoint', 'FVG Size Points', 'FVG Formed At', 'FVG Fill %',
           'FVG Retest Signal', 'FVG Active Count', 'FVG Quality']

def analyze(frame, now=None, min_gap=1.0):
    now = pd.Timestamp(now or datetime.now(breakout.IST))
    now = now.tz_localize(breakout.IST) if now.tzinfo is None else now.tz_convert(breakout.IST)
    df = breakout.completed(frame, now)
    flags = breakout.quality_flags(df)
    records, zones = [], []
    for day, session in df.groupby(df.index.date):
        zones = []
        for i, (ts, row) in enumerate(session.iterrows()):
            stamp = ts.isoformat()
            interrupted = i > 0 and ts-session.index[i-1] != pd.Timedelta(minutes=5)
            bad = bool(flags[stamp])
            signals = []
            if interrupted or bad:
                for z in zones:
                    if z['status'] not in ('INVALIDATED', 'DATA_REVIEW'):
                        z['status'] = 'DATA_REVIEW'
            for z in zones:
                if z['status'] in ('INVALIDATED', 'DATA_REVIEW') or bad:
                    continue
                was_filled = z['status'] == 'FILLED'
                lo, hi = z['lower'], z['upper']
                up = z['direction'] == 'UP'
                broken = row.Close < lo if up else row.Close > hi
                if broken:
                    if z['inverse']:
                        z['status'] = 'INVALIDATED'
                    else:
                        z.update(inverse=True, direction='DOWN' if up else 'UP',
                                 status='INVERTED', inverted_at=stamp, fill_pct=100.0,
                                 retested=False)
                    continue  # Inversion candle is not its own inverse retest.
                touched = row.Low <= hi and row.High >= lo
                if z['inverse']:
                    if touched:
                        z['status'] = 'RETESTED'
                else:
                    penetration = (hi-row.Low)/(hi-lo) if up else (row.High-lo)/(hi-lo)
                    z['fill_pct'] = max(z['fill_pct'], min(100., max(0., float(penetration)*100)))
                    z['status'] = 'FILLED' if z['fill_pct'] >= 100 else 'PARTIAL' if z['fill_pct'] > 0 else 'FRESH'
                rejection = touched and (row.Close > hi and row.Close > row.Open if up else row.Close < lo and row.Close < row.Open)
                if rejection and not was_filled and not z['retested']:
                    z['retested'] = True
                    signals.append({'zone_id': z['id'], 'direction': z['direction'], 'inverse': z['inverse']})
            if i >= 2 and not bad:
                triplet = session.iloc[i-2:i+1]
                valid = all(triplet.index[j]-triplet.index[j-1] == pd.Timedelta(minutes=5) for j in (1,2))
                valid = valid and not any(flags[t.isoformat()] for t in triplet.index)
                a, b = triplet.iloc[0], triplet.iloc[1]
                body = abs(b.Close-b.Open)/(b.High-b.Low) if b.High > b.Low else 0
                direction = None
                if valid and body >= .5:
                    if row.Low-a.High >= min_gap and b.Close > b.Open and b.Close > a.High:
                        direction, lo, hi = 'UP', float(a.High), float(row.Low)
                    elif a.Low-row.High >= min_gap and b.Close < b.Open and b.Close < a.Low:
                        direction, lo, hi = 'DOWN', float(row.High), float(a.Low)
                if direction:
                    zones.append({'id': stamp+'_'+direction, 'formed_at': stamp,
                                  'confirmed_at': (ts+pd.Timedelta(minutes=5)).isoformat(),
                                  'time': int(ts.timestamp()), 'direction': direction,
                                  'lower': lo, 'upper': hi, 'midpoint': (lo+hi)/2,
                                  'size_points': hi-lo, 'status': 'FRESH', 'inverse': False,
                                  'fill_pct': 0., 'retested': False})
            active = [z for z in zones if z['status'] not in ('FILLED','INVALIDATED','DATA_REVIEW')]
            signal_zone = next((z for z in reversed(zones) if signals and z['id']==signals[-1]['zone_id']), None)
            selected = signal_zone or (min(active, key=lambda z: abs(float(row.Close)-z['midpoint'])) if active else (zones[-1] if zones else None))
            records.append({'candle_at': stamp, 'zone': deepcopy(selected),
                            'active_count': len(active), 'signals': deepcopy(signals),
                            'quality': 'DATA_REVIEW' if bad or interrupted else 'OK'})
    latest = records[-1] if records else None
    fresh = bool(latest and pd.Timestamp(latest['candle_at']).date()==now.date() and
                 0 <= (now-pd.Timestamp(latest['candle_at'])-pd.Timedelta(minutes=5)).total_seconds() <= 720)
    eligible = fresh and now.weekday()<5 and time(9,20)<=now.time()<=time(15,30) and latest['quality']=='OK'
    return {'version': VERSION, 'records': records, 'latest': latest, 'zones': zones,
            'eligible': bool(eligible), 'note': 'Confirmed retests adjust call strength and filter opposing calls; no broker orders.'}

def export_fields(record, source='REPLAY'):
    record = record or {}; z = record.get('zone') or {}
    kind = ('BULLISH' if z.get('direction')=='UP' else 'BEARISH') + (' IFVG' if z.get('inverse') else ' FVG') if z else 'NONE'
    return dict(zip(HEADERS, [source, kind, z.get('status'), z.get('lower'), z.get('upper'),
        z.get('midpoint'), z.get('size_points'), z.get('formed_at'), z.get('fill_pct'),
        ', '.join(('BULLISH' if s['direction']=='UP' else 'BEARISH')+(' IFVG' if s['inverse'] else ' FVG') for s in record.get('signals', [])) or 'NONE',
        record.get('active_count', 0), record.get('quality', 'UNAVAILABLE')]))


def adjust_score(base, result, breakout_adjustment=0.0):
    """Current completed-candle retests only; bounded, direction-preserving score."""
    latest = result.get('latest') or {}
    sides = {s['direction'] for s in latest.get('signals', [])
             if s.get('direction') in ('UP', 'DOWN')} if result.get('eligible') and latest.get('quality') == 'OK' else set()
    blocked = ['CE','PE'] if len(sides) > 1 else ['PE'] if sides == {'UP'} else ['CE'] if sides == {'DOWN'} else []
    adjusted = base
    reason = 'No eligible completed-candle FVG retest; no FVG adjustment.'
    if len(sides) > 1:
        adjusted = (1 if base >= 0 else -1)*max(0.,abs(base)-.05)
        reason = 'Conflicting FVG retests: both calls blocked; strength reduced.'
    elif sides:
        sign = 1 if 'UP' in sides else -1
        if base*sign >= .08:
            allowance = max(0., .05-max(0., sign*breakout_adjustment))
            adjusted = base+sign*allowance
            reason = 'Confirmed FVG retest supports '+('CE' if sign==1 else 'PE')+'; shared breakout/FVG boost capped at 0.05.'
        elif base*sign < 0:
            adjusted = (1 if base>0 else -1)*max(0.,abs(base)-.05)
            reason = 'Confirmed opposing FVG retest: opposing call blocked and strength reduced.'
        else:
            reason = 'FVG retest present, but base direction too weak for a boost.'
    adjusted = max(-1.,min(1.,adjusted))
    return adjusted, {'base_score':round(base,6), 'adjustment':round(adjusted-base,6),
        'adjusted_score':round(adjusted,6), 'blocked_sides':blocked,
        'retest_directions':sorted(sides), 'reason':reason, 'calibrated_probability':False}


def filter_alerts(alerts, adjustment):
    if not alerts:
        return alerts
    for side,key in [('CE','call'),('PE','put')]:
        item = alerts.get(key)
        if not isinstance(item,dict):
            continue
        item['fvg_adjustment'] = adjustment
        if side in adjustment['blocked_sides']:
            item['signal'] = 'WAIT'
            item['reason'] = adjustment['reason']
            item.setdefault('warnings',[]).append(adjustment['reason'])
        elif adjustment['retest_directions']:
            item.setdefault('confirmations',[]).append(adjustment['reason'])
    return alerts

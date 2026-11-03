"""Display-only spot breakout levels; no change to option alerts or order rules."""
from datetime import datetime, time
import pandas as pd
from breakout_v1814 import IST

def build(frame, analysis, now=None):
    now=pd.Timestamp(now or datetime.now(IST))
    now=now.tz_localize(IST) if now.tzinfo is None else now.tz_convert(IST)
    empty={'status':'WAIT','direction':None,'show_levels':False,
           'reason':'Waiting for a confirmed completed 5m breakout.',
           'units':'NIFTY spot points','method':'Signal close entry; signal extreme + buffer stop; 1R / 2R targets'}
    if not analysis or not analysis.get('records') or frame.empty:return empty
    latest=analysis['records'][-1];day=pd.Timestamp(latest['candle_at']).date()
    records=[r for r in analysis['records'] if pd.Timestamp(r['candle_at']).date()==day]
    signals=[r for r in records if r.get('confirmed') and r.get('direction') in ('UP','DOWN')]
    if not signals:return empty
    signal=signals[-1];ts=pd.Timestamp(signal['candle_at']);bar=frame.loc[ts]
    sign=1 if signal['direction']=='UP' else -1
    entry=float(bar.Close);buffer=max(1.,float(signal.get('buffer_points') or 1))
    stop=float(bar.Low)-buffer if sign==1 else float(bar.High)+buffer
    risk=sign*(entry-stop)
    if risk<=0:return empty
    t1=entry+sign*risk;t2=entry+sign*2*risk
    future=frame[(frame.index>ts)&(frame.index.date==day)]
    status='ACTIVE';reason='Confirmed setup; projected targets are not guaranteed.';t1_hit=False
    expires=ts+pd.Timedelta(minutes=35) # Entry at close; next six full 5m candles.
    for at,row in future.iterrows():
        if at>=expires:
            status='EXPIRED';reason='30-minute setup window ended.';break
        if at != ts+pd.Timedelta(minutes=5*(list(future.index).index(at)+1)):
            status='DATA GAP';reason='Missing candle prevents reliable setup tracking.';break
        evidence=next((r for r in records if r['candle_at']==at.isoformat()),{})
        if evidence.get('quality_flags'):
            status='DATA REVIEW';reason='Flagged candle prevents reliable setup tracking.';break
        hit_stop=float(row.Low)<=stop if sign==1 else float(row.High)>=stop
        hit_t1=float(row.High)>=t1 if sign==1 else float(row.Low)<=t1
        hit_t2=float(row.High)>=t2 if sign==1 else float(row.Low)<=t2
        if hit_stop and hit_t1:
            status='AMBIGUOUS';reason='Stop and target touched in one candle; order is unknown.';break
        if hit_stop:
            status='STOP TOUCHED';reason='Spot reached the projected stop level.';break
        t1_hit=t1_hit or hit_t1
        if hit_t2:
            status='TARGET 2 TOUCHED';reason='Spot reached the second projected target.';break
    if status=='ACTIVE' and pd.Timestamp(latest['candle_end'])>=expires:
        status='EXPIRED';reason='30-minute setup window ended.'
    closed=now.date()!=day or now.time()>=time(15,30)
    if status=='ACTIVE' and closed:
        status='SESSION CLOSED';reason='Historical session setup; no active entry.'
    elif status=='ACTIVE' and not analysis.get('eligible'):
        status='STALE DATA';reason='Fresh, valid completed 5m data is required.'
    return {**empty,'status':status,'direction':signal['direction'],
            'show_levels':status not in ('DATA GAP','DATA REVIEW','STALE DATA'),
            'reason':reason,'signal_at':signal['candle_end'],'signal_time':signal['time'],
            'entry':round(entry,2),'stop_loss':round(stop,2),'target_1':round(t1,2),'target_2':round(t2,2),
            'risk_points':round(risk,2),'target_1_points':round(risk,2),'target_2_points':round(2*risk,2),
            'target_1_touched':t1_hit,'basis':', '.join(sorted({e['kind'] for e in signal.get('events',[]) if e['direction']==signal['direction']})),
            'expires_at':expires.isoformat()}

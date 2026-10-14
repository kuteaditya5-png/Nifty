"""v18 research-only challenger. No broker orders, no production strategy changes."""
import math
import pandas as pd

VERSION='18.0-research'

def _f(x, default=None):
    try:
        z=float(x)
        return z if math.isfinite(z) else default
    except (TypeError,ValueError): return default

def _patterns(df):
    if len(df)<3: return []
    a,b,c=[df.iloc[i] for i in (-3,-2,-1)]
    o,h,l,cl=map(float,(c.Open,c.High,c.Low,c.Close))
    body=abs(cl-o); rng=max(h-l,1e-8)
    out=[]
    if float(b.Close)<float(b.Open) and cl>o and o<=float(b.Close) and cl>=float(b.Open):out.append('BULLISH_ENGULFING')
    if float(b.Close)>float(b.Open) and cl<o and o>=float(b.Close) and cl<=float(b.Open):out.append('BEARISH_ENGULFING')
    if body/rng<.10:out.append('DOJI')
    if (min(o,cl)-l)>=2*max(body,1e-8) and (h-max(o,cl))<=body:out.append('HAMMER')
    if (h-max(o,cl))>=2*max(body,1e-8) and (min(o,cl)-l)<=body:out.append('SHOOTING_STAR')
    if float(a.Close)<float(a.Open) and abs(float(b.Close)-float(b.Open))<abs(float(a.Close)-float(a.Open))*.5 and cl>o and cl>(float(a.Open)+float(a.Close))/2:out.append('MORNING_STAR')
    if float(a.Close)>float(a.Open) and abs(float(b.Close)-float(b.Open))<abs(float(a.Close)-float(a.Open))*.5 and cl<o and cl<(float(a.Open)+float(a.Close))/2:out.append('EVENING_STAR')
    return out

def classify(df5,df15):
    """Uses only completed bars passed by caller. Never uses future data."""
    if len(df5)<30 or len(df15)<20:return {'decision':'WAIT','reason':'INSUFFICIENT_HISTORY'}
    c=df5.Close.astype(float); c15=df15.Close.astype(float)
    e20=c15.ewm(span=20,adjust=False).mean().iloc[-1]
    e50=c15.ewm(span=50,adjust=False).mean().iloc[-1]
    # Need enough bars for a meaningful slow EMA; mark weaker warmup explicitly.
    warm=len(df15)>=50
    atr=((df15.High-df15.Low).abs()).rolling(14).mean().iloc[-1]
    px=float(c.iloc[-1]); patterns=_patterns(df5)
    support=float(df5.Low.iloc[-21:-1].min()); resistance=float(df5.High.iloc[-21:-1].max())
    delta=c.diff(); up=delta.clip(lower=0).rolling(14).mean(); down=(-delta.clip(upper=0)).rolling(14).mean()
    rsi=float(100-100/(1+up.iloc[-1]/max(down.iloc[-1],1e-8)))
    vwap=None
    today=df5[df5.index.date==df5.index[-1].date()]
    if 'Volume' in today.columns and today.Volume.fillna(0).sum()>0:
        vwap=_f(((today.High+today.Low+today.Close)/3*today.Volume).sum()/today.Volume.sum())
    # Price-only trend proxy: does NOT claim to be the production ADX.
    trend_strength=abs(e20-e50)/max(_f(atr,1),1e-8)
    regime='TREND' if warm and trend_strength>=.6 else 'SIDEWAYS'
    bull=px>e20 and e20>e50 and rsi>=50 and (vwap is None or px>vwap)
    bear=px<e20 and e20<e50 and rsi<=50 and (vwap is None or px<vwap)
    bp=any(x in patterns for x in ('BULLISH_ENGULFING','HAMMER','MORNING_STAR'))
    sp=any(x in patterns for x in ('BEARISH_ENGULFING','SHOOTING_STAR','EVENING_STAR'))
    # Require a real pattern confirmation rather than treating an absent pattern as confirmation.
    near_support=(px-support)<=max(float(atr)*.45,px*.0005)
    near_resistance=(resistance-px)<=max(float(atr)*.45,px*.0005)
    decision='WAIT'; reason='NO_CONFIRMED_ENTRY'
    if regime=='TREND':
        if bull and bp and px<resistance:decision,reason='CE','TREND_BULLISH_CONFIRMED'
        elif bear and sp and px>support:decision,reason='PE','TREND_BEARISH_CONFIRMED'
    else:
        if near_support and bp and rsi<48:decision,reason='CE','RANGE_SUPPORT_REVERSAL'
        elif near_resistance and sp and rsi>52:decision,reason='PE','RANGE_RESISTANCE_REVERSAL'
    return {'decision':decision,'reason':reason,'regime':regime,'patterns':patterns,'rsi':round(rsi,2),'vwap':round(vwap,2) if vwap is not None else None,'vwap_available':vwap is not None,'support':round(support,2),'resistance':round(resistance,2),'trend_strength_proxy':round(trend_strength,3),'warmup_ok':warm,'close':round(px,2),'ema20_15m':round(float(e20),2),'ema50_15m':round(float(e50),2)}

def replay(df,point_cost=2.0):
    """10:00 IST classification using completed bars; underlying-point directional diagnostic ONLY."""
    if df.empty:return {'status':'error','message':'No historical 5-minute candles available'}
    data=df.copy().sort_index()
    if data.index.tz is not None:data.index=data.index.tz_convert('Asia/Kolkata').tz_localize(None)
    data=data.loc[~data.index.duplicated(keep='last')]
    # Assume index timestamps are bar starts: a 09:55 candle is complete at 10:00.
    # 15m resample anchored to 09:15 session, with left-labelled bars.
    fifteen=data.resample('15min',origin='start_day',offset='0min',label='left',closed='left').agg({'Open':'first','High':'max','Low':'min','Close':'last'})
    fifteen=fifteen.dropna()
    trades=[]; waits=0; diagnostics=[]
    for day,g in data.groupby(data.index.date):
        # At 10:00 use only bars whose opening timestamp is before 10:00.
        day10=pd.Timestamp(day)+pd.Timedelta(hours=10)
        dayend=pd.Timestamp(day)+pd.Timedelta(hours=15,minutes=20)
        if not (g.index<day10).any():continue
        hist5=data[data.index<day10]
        hist15=fifteen[fifteen.index+pd.Timedelta(minutes=15)<=day10]
        snap=classify(hist5,hist15)
        if snap['decision']=='WAIT':waits+=1;continue
        future=g[(g.index>=day10)&(g.index<dayend)]
        if future.empty:continue
        entry=float(future.Open.iloc[0]);exit_px=float(future.Close.iloc[-1])
        direction=1 if snap['decision']=='CE' else -1
        pnl_points=(exit_px-entry)*direction-point_cost
        trades.append({'date':str(day),'decision':snap['decision'],'entry_time':str(future.index[0]),'entry_nifty':round(entry,2),'exit_nifty':round(exit_px,2),'net_nifty_points_proxy':round(pnl_points,2),'reason':snap['reason'],'regime':snap['regime'],'patterns':snap['patterns']})
    # Chronological untouched last 30% diagnostic; no parameter fitting.
    split=int(len(trades)*.7);hold=trades[split:]
    def stats(t):
        return {'trades':len(t),'wins':sum(x['net_nifty_points_proxy']>0 for x in t),'win_rate_pct':round(100*sum(x['net_nifty_points_proxy']>0 for x in t)/len(t),2) if t else None,'net_nifty_points_proxy':round(sum(x['net_nifty_points_proxy'] for x in t),2)}
    return {'status':'success','version':VERSION,'mode':'RESEARCH_ONLY','point_cost_assumption':point_cost,'decision_time_ist':'10:00','trade_window_ist':'10:00-15:20','total_wait_days':waits,'all':stats(trades),'chronological_holdout_last_30pct':stats(hold),'trades':trades[-100:],'limitations':['This is NOT option P&L. CE/PE indicate direction only; option premium, theta, IV, OI, and spread history are unavailable.','This is a new candidate rule, not the production CE/PE/WAIT algorithm.','Volume-dependent VWAP is skipped when volume is missing.','No claims of improved accuracy without a clean out-of-sample comparison.'],'production_unchanged':True}

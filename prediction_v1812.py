"""v18.12 research-only 5m price-action engine; no order execution."""
from datetime import datetime
from zoneinfo import ZoneInfo
import math
import pandas as pd
from fastapi import HTTPException

def _ema(s, n): return s.ewm(span=n, adjust=False).mean()
def _rsi(s, n=14):
    d=s.diff(); up=d.clip(lower=0).ewm(alpha=1/n,adjust=False).mean(); down=(-d.clip(upper=0)).ewm(alpha=1/n,adjust=False).mean()
    return 100-100/(1+up/down.replace(0,float('nan')))
def evaluate(frame, horizon=3):
    """Only uses candles through each decision index. Horizon used for ex-post scoring only."""
    df=frame.copy().sort_index()
    if df.empty: return [], {'signals':0,'reason':'No candles'}
    for c in ('Open','High','Low','Close'): df[c]=pd.to_numeric(df[c],errors='coerce')
    df=df.dropna(subset=['Open','High','Low','Close'])
    close=df['Close']; e9=_ema(close,9);e21=_ema(close,21);e50=_ema(close,50)
    rsi=_rsi(close); macd=_ema(close,12)-_ema(close,26); macds=_ema(macd,9)
    atr=(pd.concat([(df.High-df.Low).abs(),(df.High-close.shift()).abs(),(df.Low-close.shift()).abs()],axis=1).max(axis=1)).ewm(alpha=1/14,adjust=False).mean()
    rows=[]
    for i in range(50,len(df)):
        # Breakout references exclude current candle to avoid look-ahead.
        prev_high=float(df.High.iloc[i-6:i].max());prev_low=float(df.Low.iloc[i-6:i].min())
        price=float(close.iloc[i]); vol=float(atr.iloc[i]); r=float(rsi.iloc[i])
        bullish=e9.iloc[i]>e21.iloc[i]>e50.iloc[i] and price>e9.iloc[i]
        bearish=e9.iloc[i]<e21.iloc[i]<e50.iloc[i] and price<e9.iloc[i]
        momentum_up=macd.iloc[i]>macds.iloc[i] and close.iloc[i]>close.iloc[i-1]
        momentum_down=macd.iloc[i]<macds.iloc[i] and close.iloc[i]<close.iloc[i-1]
        breakout_up=price>prev_high and float(df.Close.iloc[i])>float(df.Open.iloc[i])
        breakout_down=price<prev_low and float(df.Close.iloc[i])<float(df.Open.iloc[i])
        pullback_up=bullish and float(df.Low.iloc[i])<=float(e9.iloc[i])*1.001 and price>float(e9.iloc[i]) and price>float(df.Open.iloc[i])
        pullback_down=bearish and float(df.High.iloc[i])>=float(e9.iloc[i])*0.999 and price<float(e9.iloc[i]) and price<float(df.Open.iloc[i])
        up_score=sum([bullish,momentum_up,52<=r<=72,breakout_up or pullback_up])
        down_score=sum([bearish,momentum_down,28<=r<=48,breakout_down or pullback_down])
        decision='WAIT';setup='NONE'
        if up_score==4 and down_score<4: decision='BUY CE';setup='BREAKOUT' if breakout_up else 'PULLBACK'
        elif down_score==4 and up_score<4: decision='BUY PE';setup='BREAKDOWN' if breakout_down else 'PULLBACK'
        future=float(close.iloc[i+horizon]) if i+horizon<len(df) else None
        delta=round(future-price,2) if future is not None else None
        aligned=(delta>0 if decision=='BUY CE' else delta<0 if decision=='BUY PE' else None) if delta is not None else None
        rows.append({'time':str(df.index[i]),'decision':decision,'setup':setup,'nifty':round(price,2),'rsi':round(r,1),'ema9':round(float(e9.iloc[i]),2),'ema21':round(float(e21.iloc[i]),2),'score':max(up_score,down_score),'atr':round(vol,2),'after_15m_points':delta if horizon==3 else None,'future_points':delta,'direction_correct':aligned,'reason':'Trend + momentum + RSI + confirmed breakout/pullback' if decision!='WAIT' else 'Insufficient confluence'})
    trades=[r for r in rows if r['decision']!='WAIT']; evaluated=[r for r in trades if r['direction_correct'] is not None]
    summary={'candles':len(df),'observations':len(rows),'buy_ce':sum(r['decision']=='BUY CE' for r in trades),'buy_pe':sum(r['decision']=='BUY PE' for r in trades),'wait':sum(r['decision']=='WAIT' for r in rows),'evaluated':len(evaluated),'directional_hit_rate_percent':round(100*sum(r['direction_correct'] for r in evaluated)/len(evaluated),1) if evaluated else None,'note':'Research-only direction test, not option premium P&L. Overlapping signals and costs are not adjusted.'}
    return rows,summary

def register(app):
    @app.get('/api/v18-12/shadow')
    def shadow():
        import yfinance as yf
        data=yf.Ticker('^NSEI').history(period='5d',interval='5m')
        if data.empty: raise HTTPException(503,'NIFTY candles unavailable')
        # Yahoo current bar can be unfinished; conservatively discard last bar during session.
        now=datetime.now(ZoneInfo('Asia/Kolkata'))
        if now.weekday()<5 and (9,15)<=(now.hour,now.minute)<(15,30): data=data.iloc[:-1]
        rows,summary=evaluate(data)
        return {'status':'success','version':'18.12-shadow','latest':rows[-1] if rows else None,'summary':summary,'warning':'Experimental shadow signal. Does not replace live F&O decision or confirm option availability.'}
    @app.get('/api/v18-12/replay')
    def replay(date: str | None=None):
        import yfinance as yf
        data=yf.Ticker('^NSEI').history(period='5d',interval='5m')
        if data.empty: raise HTTPException(503,'NIFTY candles unavailable')
        if date: data=data[data.index.strftime('%Y-%m-%d')==date]
        rows,summary=evaluate(data)
        return {'status':'success','version':'18.12-shadow','date':date,'summary':summary,'signals':[r for r in rows if r['decision']!='WAIT'],'warning':'Exploratory in-sample replay. Do not infer profitability or deploy without out-of-sample testing.'}

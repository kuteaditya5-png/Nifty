import os
from datetime import datetime, time
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import requests
from fastapi.responses import HTMLResponse

VERSION = "18.2"
IST = ZoneInfo("Asia/Kolkata")
NIFTY_KEY = "NSE_INDEX|Nifty 50"

def _rsi(close, period=14):
    d=close.diff(); gain=d.clip(lower=0).ewm(alpha=1/period,adjust=False).mean(); loss=(-d.clip(upper=0)).ewm(alpha=1/period,adjust=False).mean()
    rs=gain/loss.replace(0,np.nan); return 100-(100/(1+rs))

def _request_candles(url, token):
    r=requests.get(url,headers={"Accept":"application/json","Content-Type":"application/json","Authorization":f"Bearer {token}"},timeout=12)
    try: payload=r.json()
    except Exception: payload={}
    if r.status_code!=200:
        msg=(payload.get("errors") or payload.get("message") or r.text[:350])
        raise RuntimeError(f"Upstox HTTP {r.status_code}: {msg}")
    return (payload.get("data") or {}).get("candles") or []

def _rows_to_df(rows):
    df=pd.DataFrame(rows,columns=["ts","open","high","low","close","volume","oi"])
    df["ts"]=pd.to_datetime(df["ts"],utc=True).dt.tz_convert(IST)
    for c in ["open","high","low","close","volume"]: df[c]=pd.to_numeric(df[c],errors="coerce")
    return df.sort_values("ts").dropna(subset=["open","high","low","close"]).drop_duplicates("ts")

def _fetch():
    token=os.getenv("UPSTOX_ACCESS_TOKEN")
    if not token: raise RuntimeError("UPSTOX_ACCESS_TOKEN is not configured in Vercel")
    key=requests.utils.quote(NIFTY_KEY,safe="")
    now=datetime.now(IST)
    intraday=f"https://api.upstox.com/v3/historical-candle/intraday/{key}/minutes/5"
    rows=_request_candles(intraday,token)
    source="UPSTOX_INTRADAY"
    # Intraday V3 is current-trading-day data. At night/weekends/holidays it can be empty,
    # so use the documented Historical V3 endpoint to display the latest completed session.
    if not rows:
        to_date=now.date()
        from_date=to_date-pd.Timedelta(days=10)
        historical=f"https://api.upstox.com/v3/historical-candle/{key}/minutes/5/{to_date.isoformat()}/{from_date.isoformat()}"
        rows=_request_candles(historical,token)
        source="UPSTOX_HISTORICAL_FALLBACK"
    if not rows: raise RuntimeError("Upstox returned no 5-minute NIFTY candles from intraday or historical V3")
    df=_rows_to_df(rows)
    df=df[df.ts+pd.Timedelta(minutes=5)<=now]
    if df.empty: raise RuntimeError("Upstox returned candles, but none are completed yet")
    df.attrs["data_source"]=source
    return df

def _calc(df):
    if len(df)<55: raise RuntimeError("Need at least 55 completed 5-minute candles")
    source=df.attrs.get("data_source","UPSTOX")
    x=df.copy(); x.attrs["data_source"]=source; x["ema20"]=x.close.ewm(span=20,adjust=False).mean(); x["ema50"]=x.close.ewm(span=50,adjust=False).mean(); x["rsi14"]=_rsi(x.close)
    typical=(x.high+x.low+x.close)/3; day=x.ts.dt.date
    x["vwap"]=(typical*x.volume).groupby(day).cumsum()/x.volume.groupby(day).cumsum().replace(0,np.nan)
    x["volavg"]=x.volume.rolling(20).mean(); x["prior_high"]=x.high.shift(1).rolling(3).max(); x["prior_low"]=x.low.shift(1).rolling(3).min()
    c=x.iloc[-1]; candle_time=c.ts.time(); is_today=c.ts.date()==datetime.now(IST).date(); window=is_today and time(9,25)<=candle_time<=time(11,15); vol=bool(c.volume>c.volavg)
    bull={"EMA 20 > EMA 50":bool(c.ema20>c.ema50),"Price > VWAP":bool(c.close>c.vwap),"RSI (14) > 55":bool(c.rsi14>55),"Volume > Avg":vol,"Breakout confirmed":bool(c.close>c.prior_high)}
    bear={"EMA 20 < EMA 50":bool(c.ema20<c.ema50),"Price < VWAP":bool(c.close<c.vwap),"RSI (14) < 45":bool(c.rsi14<45),"Volume > Avg":vol,"Breakdown confirmed":bool(c.close<c.prior_low)}
    sig="NO TRADE"; checks=bull if sum(bull.values())>=sum(bear.values()) else bear
    if window and all(bull.values()): sig="BUY CE"; checks=bull
    elif window and all(bear.values()): sig="BUY PE"; checks=bear
    entry=float(c.close); sl=t1=t2=None
    if sig=="BUY CE": sl=float(min(c.low,x.iloc[-4:-1].low.min())); risk=max(entry-sl,.05); t1=entry+2*risk; t2=entry+3*risk
    elif sig=="BUY PE": sl=float(max(c.high,x.iloc[-4:-1].high.max())); risk=max(sl-entry,.05); t1=entry-2*risk; t2=entry-3*risk
    candles=[{"t":r.ts.strftime("%H:%M"),"o":round(float(r.open),2),"h":round(float(r.high),2),"l":round(float(r.low),2),"c":round(float(r.close),2),"v":int(r.volume),"e20":round(float(r.ema20),2),"e50":round(float(r.ema50),2),"vw":round(float(r.vwap),2)} for _,r in x.tail(60).iterrows()]
    return {"status":"success","version":VERSION,"data_source":df.attrs.get("data_source","UPSTOX"),"signal":sig,"market_window_active":window,"last_completed_candle":c.ts.isoformat(),"price":round(entry,2),"ema20":round(float(c.ema20),2),"ema50":round(float(c.ema50),2),"vwap":round(float(c.vwap),2),"rsi14":round(float(c.rsi14),2),"volume":int(c.volume),"volume_avg":round(float(c.volavg),2),"entry":round(entry,2) if sig!="NO TRADE" else None,"stop_loss":round(sl,2) if sl else None,"target1":round(t1,2) if t1 else None,"target2":round(t2,2) if t2 else None,"checks":checks,"candles":candles,"execution_enabled":False}

def setup_v180(app):
    @app.get("/api/v18/intraday-signal")
    def signal():
        try:
            result = _calc(_fetch())
            # Force Python-native JSON-safe values before FastAPI serialization.
            def safe(v):
                if isinstance(v, dict): return {str(k): safe(x) for k,x in v.items()}
                if isinstance(v, list): return [safe(x) for x in v]
                if isinstance(v, (np.bool_,)): return bool(v)
                if isinstance(v, (np.integer,)): return int(v)
                if isinstance(v, (np.floating,)): return None if np.isnan(v) else float(v)
                if isinstance(v, (pd.Timestamp, datetime)): return v.isoformat()
                return v
            return safe(result)
        except Exception as e:
            return {"status":"error","version":VERSION,"message":f"{type(e).__name__}: {e}","execution_enabled":False}

    @app.get("/api/v18/status")
    def status():
        return {"status":"success","version":VERSION,"mode":"PAPER_SIGNAL_ONLY","instrument":NIFTY_KEY,"timeframe":"5m","execution_enabled":False}

    @app.get("/intraday-setup",response_class=HTMLResponse)
    def page():
        return HTMLResponse(r'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>NIFTY Intraday Setup</title><script src="https://cdn.jsdelivr.net/npm/chart.js"></script><style>
*{box-sizing:border-box}body{margin:0;background:#07111e;color:#dbe7f3;font-family:Arial,sans-serif}.head{height:70px;border-bottom:1px solid #203247;display:flex;align-items:center;padding:0 28px}.brand{font-size:25px;font-weight:900}.brand b{color:#21d4e8}.live{margin-left:auto;color:#35df87}.sidebar{position:fixed;left:12px;top:92px;width:82px;display:flex;flex-direction:column;gap:8px;z-index:10}.sidebar button{width:82px;min-height:64px;border:1px solid #203650;border-radius:12px;background:#091625;color:#c9d6e4;font-weight:700}.sidebar .active{background:linear-gradient(135deg,#2865ff,#6637db);color:#fff}.ico{display:block;font-size:19px;margin-bottom:5px}.wrap{padding:18px 18px 18px 108px}.market{display:flex;gap:28px;align-items:end;margin-bottom:12px}.price{font-size:29px;font-weight:900}.muted{color:#8fa3b8}.badge{padding:5px 9px;border:1px solid #29405a;border-radius:8px;font-size:12px}.grid{display:grid;grid-template-columns:minmax(0,3fr) 1.2fr;gap:12px}.panel{background:#0b1726;border:1px solid #203247;border-radius:10px}.chart{padding:12px;height:650px}.side{display:flex;flex-direction:column;gap:10px}.signal,.conditions{padding:16px}.sig{font-size:29px;font-weight:900;margin:8px 0}.green,.ok{color:#31e087}.red,.bad{color:#ff5964}.row{display:flex;justify-content:space-between;padding:9px 0;border-bottom:1px solid #1b2b3d}.footer{font-size:12px;color:#7e92a8;margin-top:10px}@media(max-width:850px){.head{height:58px;padding:0 15px}.sidebar{left:5px;top:auto;bottom:8px;width:calc(100vw - 10px);flex-direction:row;background:#071423;padding:6px;border:1px solid #203650;border-radius:14px}.sidebar button{width:auto;flex:1;min-height:48px}.wrap{padding:12px 10px 78px}.grid{grid-template-columns:1fr}.chart{height:430px}.market{flex-wrap:wrap}.brand{font-size:21px}}
</style></head><body><div class="head"><div class="brand">NIFTY <b>AI</b></div><div class="live">● Live</div></div><div class="sidebar"><button onclick="location.href='/dashboard'"><span class="ico">⌂</span>Dashboard</button><button class="active"><span class="ico">⚡</span>Intraday</button><button onclick="location.href='/dashboard#backtest'"><span class="ico">↺</span>Backtest</button></div><div class="wrap"><div class="market"><div><div class="muted">NIFTY 50</div><div class="price" id="price">--</div></div><div class="muted">5-minute • EMA 20/50 • VWAP • RSI 14 • Volume</div><div class="badge" id="source">Loading data…</div></div><div class="grid"><div class="panel chart"><canvas id="chart"></canvas></div><div class="side"><div class="panel signal"><div class="muted">LIVE SIGNAL</div><div class="sig" id="sig">LOADING</div><div class="row"><span>Entry</span><b id="entry">--</b></div><div class="row"><span>Stop Loss</span><b class="red" id="sl">--</b></div><div class="row"><span>Target 1 (2R)</span><b class="green" id="t1">--</b></div><div class="row"><span>Target 2 (3R)</span><b class="green" id="t2">--</b></div><div class="row"><span>RSI 14</span><b id="rsi">--</b></div><div class="row"><span>VWAP</span><b id="vwap">--</b></div><div class="row"><span>Last candle</span><b id="last">--</b></div></div><div class="panel conditions"><b>Setup Conditions</b><div id="checks"></div></div></div></div><div class="footer">V18.1 • Paper signal only • No automatic order placement • Historical fallback is display/analysis only and never creates a live trade signal.</div></div><script>
let chart;const $=id=>document.getElementById(id);async function load(){try{let r=await fetch('/api/v18/intraday-signal',{cache:'no-store'});let d=await r.json();if(d.status!=='success'){ $('sig').textContent='DATA ERROR';$('sig').className='sig red';$('checks').innerHTML='<div class="red">'+(d.message||'Unknown data error')+'</div>';$('source').textContent='Upstox error';return}$('price').textContent=Number(d.price).toFixed(2);$('source').textContent=d.data_source==='UPSTOX_HISTORICAL_FALLBACK'?'Latest completed session':'Current trading day';$('sig').textContent=d.signal;$('sig').className='sig '+(d.signal==='BUY CE'?'green':d.signal==='BUY PE'?'red':'muted');$('entry').textContent=d.entry??'--';$('sl').textContent=d.stop_loss??'--';$('t1').textContent=d.target1??'--';$('t2').textContent=d.target2??'--';$('rsi').textContent=d.rsi14;$('vwap').textContent=d.vwap;$('last').textContent=new Date(d.last_completed_candle).toLocaleString('en-IN',{timeZone:'Asia/Kolkata'});$('checks').innerHTML=Object.entries(d.checks).map(([k,v])=>'<div class="row"><span>'+k+'</span><b class="'+(v?'ok':'bad')+'">'+(v?'✓':'✕')+'</b></div>').join('');let c=d.candles,data={labels:c.map(x=>x.t),datasets:[{label:'Close',data:c.map(x=>x.c),borderWidth:2,pointRadius:0},{label:'EMA 20',data:c.map(x=>x.e20),borderWidth:1,pointRadius:0},{label:'EMA 50',data:c.map(x=>x.e50),borderWidth:1,pointRadius:0},{label:'VWAP',data:c.map(x=>x.vw),borderWidth:1,pointRadius:0}]};if(chart)chart.destroy();chart=new Chart($('chart'),{type:'line',data,options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},plugins:{legend:{labels:{color:'#c9d6e4'}}},scales:{x:{ticks:{color:'#8398ad',maxTicksLimit:12},grid:{color:'#142337'}},y:{ticks:{color:'#8398ad'},grid:{color:'#142337'}}}}})}catch(e){$('sig').textContent='DATA ERROR';$('checks').innerHTML='<div class="red">'+e.message+'</div>'}}load();setInterval(load,30000);
</script></body></html>''')

import os
from datetime import datetime, time
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import requests
from fastapi.responses import HTMLResponse

VERSION = "18.4"
IST = ZoneInfo("Asia/Kolkata")
NIFTY_KEY = "NSE_INDEX|Nifty 50"

def _rsi(close, period=14):
    d=close.diff(); gain=d.clip(lower=0).ewm(alpha=1/period,adjust=False).mean(); loss=(-d.clip(upper=0)).ewm(alpha=1/period,adjust=False).mean()
    loss_safe=loss.replace(0,np.nan); rs=gain/loss_safe; out=100-(100/(1+rs)); out=out.mask((loss==0)&(gain>0),100.0); out=out.mask((loss==0)&(gain==0),50.0); return out

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

def _fetch_key(key_value, token):
    key=requests.utils.quote(key_value,safe="")
    now=datetime.now(IST)
    intraday=f"https://api.upstox.com/v3/historical-candle/intraday/{key}/minutes/5"
    rows=_request_candles(intraday,token)
    source="UPSTOX_INTRADAY"
    if not rows:
        to_date=now.date()
        from_date=to_date-pd.Timedelta(days=10)
        historical=f"https://api.upstox.com/v3/historical-candle/{key}/minutes/5/{to_date.isoformat()}/{from_date.isoformat()}"
        rows=_request_candles(historical,token)
        source="UPSTOX_HISTORICAL_FALLBACK"
    if not rows: raise RuntimeError(f"Upstox returned no 5-minute candles for {key_value}")
    df=_rows_to_df(rows)
    df=df[df.ts+pd.Timedelta(minutes=5)<=now]
    if df.empty: raise RuntimeError(f"Upstox returned candles for {key_value}, but none are completed yet")
    df.attrs["data_source"]=source
    return df

def _find_nifty_future(token):
    url="https://api.upstox.com/v2/instruments/search"
    params={"query":"NIFTY","exchanges":"NSE","segments":"FUT","expiry":"current_month","page_number":1,"records":30}
    r=requests.get(url,params=params,headers={"Accept":"application/json","Authorization":f"Bearer {token}"},timeout=12)
    try: payload=r.json()
    except Exception: payload={}
    if r.status_code!=200:
        raise RuntimeError(f"Upstox instrument search HTTP {r.status_code}: {payload.get('message') or r.text[:300]}")
    items=payload.get("data") or []
    candidates=[]
    for z in items:
        symbol=str(z.get("trading_symbol") or "").upper()
        name=str(z.get("name") or "").upper()
        itype=str(z.get("instrument_type") or "").upper()
        if itype=="FUT" and ("NIFTY" in symbol or "NIFTY 50" in name) and "BANKNIFTY" not in symbol and "FINNIFTY" not in symbol:
            candidates.append(z)
    if not candidates:
        raise RuntimeError("Could not discover current-month NIFTY futures instrument from Upstox")
    candidates.sort(key=lambda z:str(z.get("expiry") or "9999-99-99"))
    z=candidates[0]
    return z.get("instrument_key"), z.get("trading_symbol") or "NIFTY FUT"

def _fetch():
    token=os.getenv("UPSTOX_ACCESS_TOKEN")
    if not token: raise RuntimeError("UPSTOX_ACCESS_TOKEN is not configured in Vercel")
    spot=_fetch_key(NIFTY_KEY,token)
    fut_key,fut_symbol=_find_nifty_future(token)
    fut=_fetch_key(fut_key,token)
    return spot,fut,fut_key,fut_symbol

def _calc(inputs):
    spot,fut,fut_key,fut_symbol=inputs
    if len(spot)<55 or len(fut)<20: raise RuntimeError("Need at least 55 spot candles and 20 futures candles")
    source=spot.attrs.get("data_source","UPSTOX")
    x=spot.copy(); x.attrs["data_source"]=source
    x["ema20"]=x.close.ewm(span=20,adjust=False).mean()
    x["ema50"]=x.close.ewm(span=50,adjust=False).mean()
    x["rsi14"]=_rsi(x.close)
    x["prior_high"]=x.high.shift(1).rolling(3).max()
    x["prior_low"]=x.low.shift(1).rolling(3).min()

    f=fut.copy()
    typical=(f.high+f.low+f.close)/3
    day=f.ts.dt.date
    volsum=f.volume.groupby(day).cumsum()
    f["vwap"]=(typical*f.volume).groupby(day).cumsum()/volsum.replace(0,np.nan)
    f["volavg"]=f.volume.rolling(20).mean()

    c=x.iloc[-1]
    # Match futures candle at/before latest spot candle.
    fm=f[f.ts<=c.ts]
    if fm.empty: raise RuntimeError("No NIFTY futures candle aligned with latest NIFTY spot candle")
    fc=fm.iloc[-1]
    required={"spot_close":c.close,"ema20":c.ema20,"ema50":c.ema50,"rsi14":c.rsi14,"prior_high":c.prior_high,"prior_low":c.prior_low,
              "futures_close":fc.close,"futures_vwap":fc.vwap,"futures_volume":fc.volume,"futures_volavg":fc.volavg}
    bad=[k for k,v in required.items() if pd.isna(v) or (isinstance(v,(float,np.floating)) and not np.isfinite(v))]
    if bad: raise RuntimeError("Indicator values unavailable: "+", ".join(bad))

    candle_time=c.ts.time()
    is_today=c.ts.date()==datetime.now(IST).date()
    window=is_today and time(9,25)<=candle_time<=time(11,15)
    vol=bool(fc.volume>fc.volavg)
    bull={"EMA 20 > EMA 50":bool(c.ema20>c.ema50),"Futures Price > VWAP":bool(fc.close>fc.vwap),"RSI (14) > 55":bool(c.rsi14>55),"Futures Volume > Avg":vol,"Spot breakout confirmed":bool(c.close>c.prior_high)}
    bear={"EMA 20 < EMA 50":bool(c.ema20<c.ema50),"Futures Price < VWAP":bool(fc.close<fc.vwap),"RSI (14) < 45":bool(c.rsi14<45),"Futures Volume > Avg":vol,"Spot breakdown confirmed":bool(c.close<c.prior_low)}
    bull_score=sum(bull.values()); bear_score=sum(bear.values())
    sig="NO TRADE"; setup_state="NO TRADE"; checks=bull if bull_score>=bear_score else bear
    if window and all(bull.values()): sig="BUY CE"; setup_state="BUY CE CONFIRMED"; checks=bull
    elif window and all(bear.values()): sig="BUY PE"; setup_state="BUY PE CONFIRMED"; checks=bear
    elif window and bull_score>=3 and bull_score>bear_score: setup_state="BULLISH SETUP FORMING"; checks=bull
    elif window and bear_score>=3 and bear_score>bull_score: setup_state="BEARISH SETUP FORMING"; checks=bear

    entry=float(c.close); sl=t1=t2=None
    if sig=="BUY CE":
        sl=float(min(c.low,x.iloc[-4:-1].low.min())); risk=max(entry-sl,.05); t1=entry+2*risk; t2=entry+3*risk
    elif sig=="BUY PE":
        sl=float(max(c.high,x.iloc[-4:-1].high.max())); risk=max(sl-entry,.05); t1=entry-2*risk; t2=entry-3*risk

    candles=[]
    for _,r in x.tail(60).iterrows():
        candles.append({"t":r.ts.strftime("%H:%M"),"o":round(float(r.open),2),"h":round(float(r.high),2),"l":round(float(r.low),2),"c":round(float(r.close),2),
                        "e20":round(float(r.ema20),2),"e50":round(float(r.ema50),2)})
    return {"status":"success","version":VERSION,"data_source":spot.attrs.get("data_source","UPSTOX"),
            "signal":sig,"setup_state":setup_state,"bull_score":bull_score,"bear_score":bear_score,"market_window_active":window,
            "last_completed_candle":c.ts.isoformat(),"price":round(entry,2),"ema20":round(float(c.ema20),2),"ema50":round(float(c.ema50),2),
            "rsi14":round(float(c.rsi14),2),"futures_symbol":fut_symbol,"futures_instrument_key":fut_key,
            "futures_price":round(float(fc.close),2),"vwap":round(float(fc.vwap),2),"volume":int(fc.volume),"volume_avg":round(float(fc.volavg),2),
            "entry":round(entry,2) if sig!="NO TRADE" else None,"stop_loss":round(sl,2) if sl is not None else None,
            "target1":round(t1,2) if t1 is not None else None,"target2":round(t2,2) if t2 is not None else None,
            "checks":checks,"candles":candles,"execution_enabled":False}

def setup_v180(app):
    @app.get("/api/v18/intraday-signal")
    def signal():
        try:return _calc(_fetch())
        except Exception as e:return {"status":"error","version":VERSION,"error_type":type(e).__name__,"message":str(e),"execution_enabled":False}

    @app.get("/api/v18/status")
    def status():
        return {"status":"success","version":VERSION,"mode":"PAPER_SIGNAL_ONLY","instrument":NIFTY_KEY,"confirmation_source":"CURRENT_MONTH_NIFTY_FUTURES","timeframe":"5m","execution_enabled":False}

    @app.get("/intraday-setup",response_class=HTMLResponse)
    def page():
        return HTMLResponse(r'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>NIFTY Intraday Setup</title><script src="https://cdn.jsdelivr.net/npm/chart.js"></script><style>
*{box-sizing:border-box}body{margin:0;background:#07111e;color:#dbe7f3;font-family:Arial,sans-serif}.head{height:70px;border-bottom:1px solid #203247;display:flex;align-items:center;padding:0 28px}.brand{font-size:25px;font-weight:900}.brand b{color:#21d4e8}.live{margin-left:auto;color:#35df87}.sidebar{position:fixed;left:12px;top:92px;width:82px;display:flex;flex-direction:column;gap:8px;z-index:10}.sidebar button{width:82px;min-height:64px;border:1px solid #203650;border-radius:12px;background:#091625;color:#c9d6e4;font-weight:700}.sidebar .active{background:linear-gradient(135deg,#2865ff,#6637db);color:#fff}.ico{display:block;font-size:19px;margin-bottom:5px}.wrap{padding:18px 18px 18px 108px}.market{display:flex;gap:28px;align-items:end;margin-bottom:12px}.price{font-size:29px;font-weight:900}.muted{color:#8fa3b8}.badge{padding:5px 9px;border:1px solid #29405a;border-radius:8px;font-size:12px}.grid{display:grid;grid-template-columns:minmax(0,3fr) 1.2fr;gap:12px}.panel{background:#0b1726;border:1px solid #203247;border-radius:10px}.chart{padding:12px;height:650px}.side{display:flex;flex-direction:column;gap:10px}.signal,.conditions{padding:16px}.sig{font-size:29px;font-weight:900;margin:8px 0}.green,.ok{color:#31e087}.red,.bad{color:#ff5964}.row{display:flex;justify-content:space-between;padding:9px 0;border-bottom:1px solid #1b2b3d}.footer{font-size:12px;color:#7e92a8;margin-top:10px}@media(max-width:850px){.head{height:58px;padding:0 15px}.sidebar{left:5px;top:auto;bottom:8px;width:calc(100vw - 10px);flex-direction:row;background:#071423;padding:6px;border:1px solid #203650;border-radius:14px}.sidebar button{width:auto;flex:1;min-height:48px}.wrap{padding:12px 10px 78px}.grid{grid-template-columns:1fr}.chart{height:430px}.market{flex-wrap:wrap}.brand{font-size:21px}}
</style></head><body><div class="head"><div class="brand">NIFTY <b>AI</b></div><div class="live">● Live</div></div><div class="sidebar"><button onclick="location.href='/dashboard'"><span class="ico">⌂</span>Dashboard</button><button class="active"><span class="ico">⚡</span>Intraday</button><button onclick="location.href='/dashboard#backtest'"><span class="ico">↺</span>Backtest</button></div><div class="wrap"><div class="market"><div><div class="muted">NIFTY 50</div><div class="price" id="price">--</div></div><div class="muted">5-minute • EMA 20/50 • VWAP • RSI 14 • Volume</div><div class="badge" id="source">Loading data…</div></div><div class="grid"><div class="panel chart"><canvas id="chart"></canvas></div><div class="side"><div class="panel signal"><div class="muted">LIVE SIGNAL</div><div class="sig" id="sig">LOADING</div><div class="row"><span>Entry</span><b id="entry">--</b></div><div class="row"><span>Stop Loss</span><b class="red" id="sl">--</b></div><div class="row"><span>Target 1 (2R)</span><b class="green" id="t1">--</b></div><div class="row"><span>Target 2 (3R)</span><b class="green" id="t2">--</b></div><div class="row"><span>RSI 14</span><b id="rsi">--</b></div><div class="row"><span>VWAP</span><b id="vwap">--</b></div><div class="row"><span>Last candle</span><b id="last">--</b></div></div><div class="panel conditions"><b>Setup Conditions</b><div id="checks"></div></div></div></div><div class="footer">V18.4 • Paper signal only • No automatic order placement • Historical fallback is display/analysis only and never creates a live trade signal.</div></div><script>
let chart;const $=id=>document.getElementById(id);async function load(){try{let r=await fetch('/api/v18/intraday-signal',{cache:'no-store'});let d=await r.json();if(d.status!=='success'){ $('sig').textContent='DATA ERROR';$('sig').className='sig red';$('checks').innerHTML='<div class="red">'+(d.message||'Unknown data error')+'</div>';$('source').textContent='Upstox error';return}$('price').textContent=Number(d.price).toFixed(2);$('source').textContent=d.data_source==='UPSTOX_HISTORICAL_FALLBACK'?'Latest completed session':'Current trading day';$('sig').textContent=d.setup_state||d.signal;$('sig').className='sig '+(d.signal==='BUY CE'||d.setup_state==='BULLISH SETUP FORMING'?'green':d.signal==='BUY PE'||d.setup_state==='BEARISH SETUP FORMING'?'red':'muted');$('entry').textContent=d.entry??'--';$('sl').textContent=d.stop_loss??'--';$('t1').textContent=d.target1??'--';$('t2').textContent=d.target2??'--';$('rsi').textContent=d.rsi14;$('vwap').textContent=d.vwap;$('last').textContent=new Date(d.last_completed_candle).toLocaleString('en-IN',{timeZone:'Asia/Kolkata'});$('checks').innerHTML=Object.entries(d.checks).map(([k,v])=>'<div class="row"><span>'+k+'</span><b class="'+(v?'ok':'bad')+'">'+(v?'✓':'✕')+'</b></div>').join('');let c=d.candles,data={labels:c.map(x=>x.t),datasets:[{label:'Close',data:c.map(x=>x.c),borderWidth:2,pointRadius:0},{label:'EMA 20',data:c.map(x=>x.e20),borderWidth:1,pointRadius:0},{label:'EMA 50',data:c.map(x=>x.e50),borderWidth:1,pointRadius:0}]};if(chart)chart.destroy();chart=new Chart($('chart'),{type:'line',data,options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},plugins:{legend:{labels:{color:'#c9d6e4'}}},scales:{x:{ticks:{color:'#8398ad',maxTicksLimit:12},grid:{color:'#142337'}},y:{ticks:{color:'#8398ad'},grid:{color:'#142337'}}}}})}catch(e){$('sig').textContent='DATA ERROR';$('checks').innerHTML='<div class="red">'+e.message+'</div>'}}load();setInterval(load,30000);
</script></body></html>''')
        

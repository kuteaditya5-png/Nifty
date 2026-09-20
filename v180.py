import os
from datetime import datetime, time
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import requests
from fastapi.responses import HTMLResponse

VERSION = "18.0"
IST = ZoneInfo("Asia/Kolkata")
NIFTY_KEY = "NSE_INDEX|Nifty 50"

def _rsi(close, period=14):
    d=close.diff(); gain=d.clip(lower=0).ewm(alpha=1/period,adjust=False).mean(); loss=(-d.clip(upper=0)).ewm(alpha=1/period,adjust=False).mean()
    rs=gain/loss.replace(0,np.nan); return 100-(100/(1+rs))

def _fetch():
    token=os.getenv("UPSTOX_ACCESS_TOKEN")
    if not token: raise RuntimeError("UPSTOX_ACCESS_TOKEN is not configured")
    key=requests.utils.quote(NIFTY_KEY,safe="")
    url=f"https://api.upstox.com/v3/historical-candle/intraday/{key}/minutes/5"
    r=requests.get(url,headers={"Accept":"application/json","Authorization":f"Bearer {token}"},timeout=10)
    if r.status_code!=200: raise RuntimeError(f"Upstox {r.status_code}: {r.text[:250]}")
    rows=(r.json().get("data") or {}).get("candles") or []
    if not rows: raise RuntimeError("No Upstox candles returned")
    df=pd.DataFrame(rows,columns=["ts","open","high","low","close","volume","oi"])
    df["ts"]=pd.to_datetime(df["ts"],utc=True).dt.tz_convert(IST)
    for c in ["open","high","low","close","volume"]: df[c]=pd.to_numeric(df[c],errors="coerce")
    df=df.sort_values("ts").dropna(subset=["open","high","low","close"])
    now=datetime.now(IST)
    return df[df.ts+pd.Timedelta(minutes=5)<=now]

def _calc(df):
    if len(df)<55: raise RuntimeError("Need at least 55 completed 5-minute candles")
    x=df.copy(); x["ema20"]=x.close.ewm(span=20,adjust=False).mean(); x["ema50"]=x.close.ewm(span=50,adjust=False).mean(); x["rsi14"]=_rsi(x.close)
    typical=(x.high+x.low+x.close)/3; day=x.ts.dt.date
    x["vwap"]=(typical*x.volume).groupby(day).cumsum()/x.volume.groupby(day).cumsum().replace(0,np.nan)
    x["volavg"]=x.volume.rolling(20).mean(); x["prior_high"]=x.high.shift(1).rolling(3).max(); x["prior_low"]=x.low.shift(1).rolling(3).min()
    c=x.iloc[-1]; now=datetime.now(IST); window=time(9,25)<=now.time()<=time(11,15); vol=bool(c.volume>c.volavg)
    bull={"EMA 20 > EMA 50":bool(c.ema20>c.ema50),"Price > VWAP":bool(c.close>c.vwap),"RSI (14) > 55":bool(c.rsi14>55),"Volume > Avg":vol,"Breakout confirmed":bool(c.close>c.prior_high)}
    bear={"EMA 20 < EMA 50":bool(c.ema20<c.ema50),"Price < VWAP":bool(c.close<c.vwap),"RSI (14) < 45":bool(c.rsi14<45),"Volume > Avg":vol,"Breakdown confirmed":bool(c.close<c.prior_low)}
    sig="NO TRADE"; checks=bull if sum(bull.values())>=sum(bear.values()) else bear
    if window and all(bull.values()): sig="BUY CE"; checks=bull
    elif window and all(bear.values()): sig="BUY PE"; checks=bear
    entry=float(c.close); sl=t1=t2=None
    if sig=="BUY CE": sl=float(min(c.low,x.iloc[-4:-1].low.min())); risk=max(entry-sl,.05); t1=entry+2*risk; t2=entry+3*risk
    elif sig=="BUY PE": sl=float(max(c.high,x.iloc[-4:-1].high.max())); risk=max(sl-entry,.05); t1=entry-2*risk; t2=entry-3*risk
    candles=[{"t":r.ts.strftime("%H:%M"),"o":round(float(r.open),2),"h":round(float(r.high),2),"l":round(float(r.low),2),"c":round(float(r.close),2),"v":int(r.volume),"e20":round(float(r.ema20),2),"e50":round(float(r.ema50),2),"vw":round(float(r.vwap),2)} for _,r in x.tail(60).iterrows()]
    return {"status":"success","version":VERSION,"signal":sig,"market_window_active":window,"last_completed_candle":c.ts.isoformat(),"price":round(entry,2),"ema20":round(float(c.ema20),2),"ema50":round(float(c.ema50),2),"vwap":round(float(c.vwap),2),"rsi14":round(float(c.rsi14),2),"volume":int(c.volume),"volume_avg":round(float(c.volavg),2),"entry":round(entry,2) if sig!="NO TRADE" else None,"stop_loss":round(sl,2) if sl else None,"target1":round(t1,2) if t1 else None,"target2":round(t2,2) if t2 else None,"checks":checks,"candles":candles,"execution_enabled":False}

def setup_v180(app):
    @app.get("/api/v18/intraday-signal")
    def signal():
        try:return _calc(_fetch())
        except Exception as e:return {"status":"error","version":VERSION,"message":str(e),"execution_enabled":False}

    @app.get("/intraday-setup",response_class=HTMLResponse)
    def page():
        return HTMLResponse('''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>NIFTY Intraday Setup</title><script src="https://cdn.jsdelivr.net/npm/chart.js"></script><style>
*{box-sizing:border-box}body{margin:0;background:#07111e;color:#dbe7f3;font-family:Arial,sans-serif}.top{height:58px;background:#0b1726;border-bottom:1px solid #203247;display:flex;align-items:center;padding:0 22px;gap:28px}.brand{font-size:21px;font-weight:800}.nav{color:#9fb0c3}.active{background:#34206b;color:#fff;padding:10px 15px;border-radius:7px}.live{margin-left:auto;color:#35df87}.wrap{padding:14px}.market{display:flex;gap:28px;align-items:end;margin-bottom:10px}.price{font-size:27px;font-weight:800}.grid{display:grid;grid-template-columns:minmax(0,3fr) 1.25fr;gap:12px}.panel{background:#0b1726;border:1px solid #203247;border-radius:9px}.chart{padding:12px;height:610px}.side{display:flex;flex-direction:column;gap:10px}.signal{padding:16px}.sig{font-size:27px;font-weight:900;margin:8px 0}.green{color:#31e087}.red{color:#ff5964}.muted{color:#8fa3b8}.row{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #1b2b3d}.conditions{padding:14px}.ok{color:#31e087}.bad{color:#ff5964}.footer{font-size:12px;color:#7e92a8;margin-top:10px}@media(max-width:850px){.grid{grid-template-columns:1fr}.chart{height:430px}.nav{display:none}}
</style></head><body><div class="top"><div class="brand">↗ NIFTY AI</div><div class="nav">Dashboard</div><div class="nav">1-Month Picks</div><div class="nav">F&O Alerts</div><div class="active">Intraday Setup</div><div class="nav">Validation</div><div class="live">● Live</div></div><div class="wrap"><div class="market"><div><div class="muted">NIFTY 50</div><div class="price" id="price">--</div></div><div class="muted">5-minute • EMA 20/50 • VWAP • RSI 14 • Volume</div></div><div class="grid"><div class="panel chart"><canvas id="chart"></canvas></div><div class="side"><div class="panel signal"><div class="muted">LIVE SIGNAL</div><div class="sig" id="sig">LOADING</div><div class="row"><span>Entry</span><b id="entry">--</b></div><div class="row"><span>Stop Loss</span><b class="red" id="sl">--</b></div><div class="row"><span>Target 1 (2R)</span><b class="green" id="t1">--</b></div><div class="row"><span>Target 2 (3R)</span><b class="green" id="t2">--</b></div><div class="row"><span>RSI 14</span><b id="rsi">--</b></div><div class="row"><span>VWAP</span><b id="vwap">--</b></div></div><div class="panel conditions"><b>Setup Conditions</b><div id="checks"></div></div></div></div><div class="footer">V18.0 • Paper signal only • No automatic order placement. Signals use completed 5-minute candles.</div></div><script>
let chart;async function load(){let r=await fetch('/api/v18/intraday-signal');let d=await r.json();if(d.status!=='success'){document.getElementById('sig').textContent='DATA ERROR';document.getElementById('checks').innerHTML='<div class="red">'+d.message+'</div>';return}price.textContent=d.price.toFixed(2);sig.textContent=d.signal;sig.className='sig '+(d.signal==='BUY CE'?'green':d.signal==='BUY PE'?'red':'muted');entry.textContent=d.entry??'--';sl.textContent=d.stop_loss??'--';t1.textContent=d.target1??'--';t2.textContent=d.target2??'--';rsi.textContent=d.rsi14;vwap.textContent=d.vwap;checks.innerHTML=Object.entries(d.checks).map(([k,v])=>'<div class="row"><span>'+k+'</span><b class="'+(v?'ok':'bad')+'">'+(v?'✓':'✕')+'</b></div>').join('');let c=d.candles;let data={labels:c.map(x=>x.t),datasets:[{label:'Close',data:c.map(x=>x.c),borderWidth:2,pointRadius:0},{label:'EMA 20',data:c.map(x=>x.e20),borderWidth:1,pointRadius:0},{label:'EMA 50',data:c.map(x=>x.e50),borderWidth:1,pointRadius:0},{label:'VWAP',data:c.map(x=>x.vw),borderWidth:1,pointRadius:0}]};if(chart)chart.destroy();chart=new Chart(document.getElementById('chart'),{type:'line',data,options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},plugins:{legend:{labels:{color:'#c9d6e4'}}},scales:{x:{ticks:{color:'#8398ad',maxTicksLimit:12},grid:{color:'#142337'}},y:{ticks:{color:'#8398ad'},grid:{color:'#142337'}}}}})}load();setInterval(load,30000);
</script></body></html>''')

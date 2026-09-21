import os
from datetime import datetime, time
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import requests
from fastapi.responses import HTMLResponse

VERSION = "18.7.1"
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

    # Align futures confirmation data onto spot timestamps for charting.
    fa=f[["ts","close","vwap","volume","volavg"]].rename(columns={"close":"fut_close","volume":"fut_volume","volavg":"fut_volavg"})
    xa=pd.merge_asof(x.sort_values("ts"),fa.sort_values("ts"),on="ts",direction="backward",tolerance=pd.Timedelta(minutes=5))
    xa["cross_up"]=(xa.ema20>xa.ema50)&(xa.ema20.shift(1)<=xa.ema50.shift(1))
    xa["cross_down"]=(xa.ema20<xa.ema50)&(xa.ema20.shift(1)>=xa.ema50.shift(1))
    candles=[]
    for _,r in xa.tail(90).iterrows():
        def safe(v, digits=2):
            return None if pd.isna(v) or not np.isfinite(float(v)) else round(float(v),digits)
        candles.append({"ts":r.ts.isoformat(),"t":r.ts.strftime("%H:%M"),"o":safe(r.open),"h":safe(r.high),"l":safe(r.low),"c":safe(r.close),
                        "e20":safe(r.ema20),"e50":safe(r.ema50),"rsi":safe(r.rsi14),"fvwap":safe(r.vwap),
                        "fut":safe(r.fut_close),"vol":safe(r.fut_volume,0),"vavg":safe(r.fut_volavg,0),
                        "cross_up":bool(r.cross_up),"cross_down":bool(r.cross_down)})
    return {"status":"success","version":VERSION,"data_source":spot.attrs.get("data_source","UPSTOX"),
            "signal":sig,"setup_state":setup_state,"bull_score":bull_score,"bear_score":bear_score,"market_window_active":window,
            "last_completed_candle":c.ts.isoformat(),"price":round(entry,2),"ema20":round(float(c.ema20),2),"ema50":round(float(c.ema50),2),
            "rsi14":round(float(c.rsi14),2),"futures_symbol":fut_symbol,"futures_instrument_key":fut_key,
            "futures_price":round(float(fc.close),2),"vwap":round(float(fc.vwap),2),"volume":int(fc.volume),"volume_avg":round(float(fc.volavg),2),
            "entry":round(entry,2) if sig!="NO TRADE" else None,"stop_loss":round(sl,2) if sl is not None else None,
            "target1":round(t1,2) if t1 is not None else None,"target2":round(t2,2) if t2 is not None else None,
            "checks":checks,"candles":candles,"execution_enabled":False}

def _historical_spot(days=45, from_date=None, to_date=None):
    token=os.getenv("UPSTOX_ACCESS_TOKEN")
    if not token: raise RuntimeError("UPSTOX_ACCESS_TOKEN is not configured in Vercel")
    today=datetime.now(IST).date()
    if from_date is not None and to_date is not None:
        start=pd.Timestamp(from_date).date(); end=pd.Timestamp(to_date).date()
    else:
        end=today; start=end-pd.Timedelta(days=days)
    if end>today: end=today
    if start>end: raise RuntimeError("From date cannot be after To date")
    if (end-start).days>89: raise RuntimeError("Maximum selectable calendar range is 90 days")
    key=requests.utils.quote(NIFTY_KEY,safe="")
    frames=[]; cur=start
    while cur<=end:
        chunk_end=min(cur+pd.Timedelta(days=6),end)
        url=f"https://api.upstox.com/v3/historical-candle/{key}/minutes/5/{chunk_end.isoformat()}/{cur.isoformat()}"
        rows=_request_candles(url,token)
        if rows: frames.append(_rows_to_df(rows))
        cur=chunk_end+pd.Timedelta(days=1)
    if not frames: raise RuntimeError("No NIFTY candles available for the selected period")
    x=pd.concat(frames,ignore_index=True).sort_values("ts").drop_duplicates("ts")
    return x.reset_index(drop=True)

def _ema_cross_backtest(days=45, from_date=None, to_date=None):
    x=_historical_spot(days,from_date,to_date)
    actual_from=x.ts.min().date().isoformat(); actual_to=x.ts.max().date().isoformat()
    trading_days=int(x.ts.dt.date.nunique())
    x["ema20"]=x.close.ewm(span=20,adjust=False).mean(); x["ema50"]=x.close.ewm(span=50,adjust=False).mean()
    x["up"]=(x.ema20>x.ema50)&(x.ema20.shift(1)<=x.ema50.shift(1)); x["dn"]=(x.ema20<x.ema50)&(x.ema20.shift(1)>=x.ema50.shift(1))
    signals=x[x.up|x.dn].copy()
    capital=50000.0; start_capital=capital; peak=capital; maxdd=0.0; trades=[]
    # Conservative research proxy: 20% of equity allocated per trade, underlying % move applied to allocation.
    # T1/T2/SL cannot be truthfully reconstructed without historical option-premium OHLC.
    rows=list(signals.iterrows())
    for i in range(len(rows)-1):
        _,r=rows[i]; _,n=rows[i+1]; side="CE" if r.up else "PE"
        entry=float(r.close); exitp=float(n.close)
        move=((exitp-entry)/entry) if side=="CE" else ((entry-exitp)/entry)
        allocated=capital*0.20; pnl=allocated*move; capital+=pnl; peak=max(peak,capital); maxdd=max(maxdd,peak-capital)
        trades.append({"side":side,"entry":round(entry,2),"stop_loss":None,"target1":None,"target2":None,
                       "target1_hit":None,"target2_hit":None,"stop_loss_hit":None,"exit":round(exitp,2),
                       "pnl":round(pnl,2),"balance":round(capital,2),"reason":"OPPOSITE EMA CROSS"})
    wins=sum(t["pnl"]>0 for t in trades); losses=len(trades)-wins
    grosswin=sum(max(t["pnl"],0) for t in trades); grossloss=abs(sum(min(t["pnl"],0) for t in trades))
    return {"status":"success","version":VERSION,"strategy":"EMA20/EMA50 CROSS - ₹50K COMPOUNDING RESEARCH PROXY",
            "actual_from":actual_from,"actual_to":actual_to,"trading_days":trading_days,"starting_capital":start_capital,"ending_capital":round(capital,2),"net_pnl":round(capital-start_capital,2),
            "return_percent":round((capital/start_capital-1)*100,2),"trades":len(trades),"wins":wins,"losses":losses,
            "win_rate":round(wins/len(trades)*100,2) if trades else 0,"profit_factor":round(grosswin/grossloss,2) if grossloss else None,
            "max_drawdown":round(maxdd,2),"max_drawdown_percent":round(maxdd/peak*100,2) if peak else 0,
            "target1_hits":None,"target2_hits":None,"stop_loss_hits":None,
            "note":"₹50,000 compounds trade-by-trade. This is a conservative underlying-return research proxy. T1/T2/SL hit status is intentionally N/A because the current project source does not provide historical option-premium OHLC needed to determine those events honestly.",
            "history":trades[-100:]}

def setup_v180(app):
    @app.get("/api/v18/intraday-signal")
    def signal():
        try:return _calc(_fetch())
        except Exception as e:return {"status":"error","version":VERSION,"error_type":type(e).__name__,"message":str(e),"execution_enabled":False}

    @app.get("/api/v18/option-chain")
    def option_chain():
        try:
            from main import fno_alerts
            data=fno_alerts()
            if not isinstance(data,dict): raise RuntimeError("Dashboard F&O engine returned an unexpected response")
            return data
        except Exception as e:
            return {"status":"error","version":VERSION,"error_type":type(e).__name__,"message":str(e)}

    @app.get("/api/v18/backtest")
    def backtest(days:int=45, from_date:str=None, to_date:str=None):
        try:
            if from_date or to_date:
                if not (from_date and to_date): raise RuntimeError("Both from_date and to_date are required")
                return _ema_cross_backtest(from_date=from_date,to_date=to_date)
            return _ema_cross_backtest(max(1,min(days,90)))
        except Exception as e:return {"status":"error","version":VERSION,"error_type":type(e).__name__,"message":str(e)}

    @app.get("/api/v18/status")
    def status():
        return {"status":"success","version":VERSION,"mode":"PAPER_TRADING_EMA_CROSS","instrument":NIFTY_KEY,"confirmation_source":"CURRENT_MONTH_NIFTY_FUTURES","timeframe":"5m","execution_enabled":False}

    @app.get("/intraday-setup",response_class=HTMLResponse)
    def page():
        return HTMLResponse(r"""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NIFTY Intraday V18.5</title><script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>*{box-sizing:border-box}body{margin:0;background:#07111e;color:#dbe7f3;font-family:Arial,sans-serif}.head{height:66px;border-bottom:1px solid #203247;display:flex;align-items:center;padding:0 26px}.brand{font-size:24px;font-weight:900}.brand b{color:#21d4e8}.live{margin-left:auto;color:#35df87}.sideNav{display:none!important;position:fixed;left:10px;top:88px;width:84px;display:flex;flex-direction:column;gap:8px}.sideNav button{min-height:62px;border:1px solid #203650;border-radius:12px;background:#091625;color:#c9d6e4;font-weight:700}.sideNav .active{background:linear-gradient(135deg,#2865ff,#6637db);color:white}.wrap{padding:16px 22px 30px 22px;max-width:1600px;margin:auto}.market{display:flex;gap:22px;align-items:end;flex-wrap:wrap;margin-bottom:12px}.price{font-size:28px;font-weight:900}.muted{color:#8fa3b8}.badge{padding:5px 9px;border:1px solid #29405a;border-radius:8px}.grid{display:grid;grid-template-columns:minmax(0,3fr) 1.15fr;gap:12px}.panel{background:#0b1726;border:1px solid #203247;border-radius:10px}.chartPanel{padding:10px;height:440px}.smallChart{padding:8px;height:180px;margin-top:10px}.right{display:flex;flex-direction:column;gap:10px}.box{padding:14px}.sig{font-size:27px;font-weight:900;margin:7px 0}.green,.ok{color:#31e087}.red,.bad{color:#ff5964}.yellow{color:#ffd166}.row{display:flex;justify-content:space-between;gap:10px;padding:7px 0;border-bottom:1px solid #1b2b3d}.paper{margin-top:12px;padding:14px}.paperGrid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.stat{background:#091522;border:1px solid #1d3045;border-radius:8px;padding:10px}.stat b{display:block;font-size:18px;margin-top:4px}.table{width:100%;border-collapse:collapse;font-size:12px;margin-top:10px}.table td,.table th{padding:7px;border-bottom:1px solid #1b2b3d;text-align:left}.footer{font-size:12px;color:#7e92a8;margin-top:10px}@media(max-width:900px){.sideNav{position:static;width:auto;flex-direction:row;margin:8px}.sideNav button{flex:1}.wrap{padding:8px}.grid{grid-template-columns:1fr}.chartPanel{height:360px}.paperGrid{grid-template-columns:repeat(2,1fr)}}</style></head>
<body><div class="head"><div class="brand">NIFTY <b>AI</b></div><div class="live">● Paper engine</div></div>
<div class="sideNav"><button onclick="location.href='/dashboard'">⌂<br>Dashboard</button><button class="active">⚡<br>Intraday</button><button onclick="document.getElementById('bt').scrollIntoView()">↺<br>Backtest</button></div>
<div class="wrap"><div class="market"><div><div class="muted">NIFTY 50</div><div class="price" id="price">--</div></div><div class="muted">5m • EMA20/50 • Futures VWAP/Volume • RSI14 • EMA Cross Paper Trading</div><div class="badge" id="source">Loading…</div></div>
<div class="grid"><div><div class="panel chartPanel"><canvas id="priceChart"></canvas></div><div class="panel smallChart"><canvas id="volChart"></canvas></div><div class="panel smallChart"><canvas id="rsiChart"></canvas></div></div>
<div class="right"><div class="panel box"><div class="muted">LIVE SETUP</div><div class="sig" id="sig">LOADING</div><div class="row"><span>EMA20</span><b id="e20">--</b></div><div class="row"><span>EMA50</span><b id="e50">--</b></div><div class="row"><span>Futures VWAP</span><b id="vwap">--</b></div><div class="row"><span>Futures price</span><b id="fut">--</b></div><div class="row"><span>RSI14</span><b id="rsi">--</b></div><div class="row"><span>Bull / Bear score</span><b id="score">--</b></div><div class="row"><span>Last candle</span><b id="last">--</b></div></div>
<div class="panel box"><b>Setup conditions</b><div id="checks"></div></div>
<div class="panel box"><b>₹50,000 Paper Trading</b><div class="row"><span>Position</span><b id="ppos">NONE</b></div><div class="row"><span>Contract</span><b id="pcontract">--</b></div><div class="row"><span>Qty</span><b id="pqty">--</b></div><div class="row"><span>Entry premium</span><b id="pentry">--</b></div><div class="row"><span>Current premium</span><b id="pcurrent">--</b></div><div class="row"><span>SL / T1 / T2</span><b id="plevels">--</b></div><div class="row"><span>Cash</span><b id="pcash">₹50,000</b></div><div class="row"><span>Equity</span><b id="pequity">₹50,000</b></div><div class="row"><span>Open P&L</span><b id="ppnl">₹0.00</b></div><div class="muted" style="font-size:11px;margin-top:7px">Paper only. Uses Dashboard option premium and target levels. No broker order is sent.</div></div></div></div>
<div class="panel paper" id="oc"><b>Option Chain + Dashboard Targets</b><div class="muted" id="ocmeta" style="margin-top:6px">Loading existing Dashboard F&O engine…</div>
<div class="paperGrid" style="margin-top:10px"><div class="stat">CE Setup<b id="ceSetup">--</b><span id="ceLevels"></span></div><div class="stat">PE Setup<b id="peSetup">--</b><span id="peLevels"></span></div><div class="stat">ATM Strike<b id="atm">--</b></div><div class="stat">Expiry<b id="expiry">--</b></div></div>
<table class="table"><thead><tr><th>CE LTP</th><th>CE OI</th><th>Strike</th><th>PE OI</th><th>PE LTP</th></tr></thead><tbody id="och"></tbody></table></div>
<div class="panel paper" id="bt"><b>₹50,000 Compounding Strategy Backtest</b>
<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:end;margin:12px 0">
<button onclick="quickBT(0)" class="badge">Today</button><button onclick="quickBT(5)" class="badge">5D</button><button onclick="quickBT(10)" class="badge">10D</button><button onclick="quickBT(30)" class="badge">30D</button>
<label class="muted">From<br><input id="btFrom" type="date" style="background:#091522;color:#dbe7f3;border:1px solid #29405a;padding:7px;border-radius:7px"></label>
<label class="muted">To<br><input id="btTo" type="date" style="background:#091522;color:#dbe7f3;border:1px solid #29405a;padding:7px;border-radius:7px"></label>
<button onclick="customBT()" class="badge">Run Backtest</button></div>
<div class="muted" style="margin-bottom:10px">Select one date by setting From and To to the same day. Custom ranges can include weekends/holidays; only dates with market candles are counted. Maximum selectable calendar range: <b>90 days</b>.</div>
<div class="muted" id="btperiod" style="margin-bottom:10px">Period: --</div><div class="paperGrid"><div class="stat">Starting Capital<b>₹50,000</b></div><div class="stat">Ending Capital<b id="btend">--</b></div><div class="stat">Net P&L<b id="btn">--</b></div><div class="stat">Return<b id="btret">--</b></div><div class="stat">Trades<b id="btt">--</b></div><div class="stat">Win Rate<b id="btw">--</b></div><div class="stat">T1 Hit<b id="btt1">--</b></div><div class="stat">T2 Hit<b id="btt2">--</b></div><div class="stat">SL Hit<b id="btsl">--</b></div><div class="stat">Max Drawdown<b id="btdd">--</b></div></div><div class="muted" id="btnote" style="margin-top:8px"></div><table class="table"><thead><tr><th>Side</th><th>Entry</th><th>SL</th><th>T1</th><th>T2</th><th>T1 Hit</th><th>T2 Hit</th><th>SL Hit</th><th>Exit</th><th>P&L</th><th>Balance</th></tr></thead><tbody id="bth"></tbody></table></div>
<div class="footer">V18.7.1 • Paper trading only • EMA crossover uses completed 5-minute candles • Backtest reports NIFTY underlying points, not option-premium P&amp;L.</div></div>
<script>
const $=x=>document.getElementById(x);let pc,vc,rc,lastSignal=null,lastFno=null;
function paperState(){try{return JSON.parse(localStorage.getItem('nifty_v187_paper'))||{cash:50000,pos:null,trades:[],lastCross:null}}catch(e){return{cash:50000,pos:null,trades:[],lastCross:null}}}
function savePaper(s){localStorage.setItem('nifty_v187_paper',JSON.stringify(s))}
function optionRow(chain,strike){return (chain.nearby_strikes||[]).find(x=>Number(x.strike)===Number(strike))}
function runPaper(d,fd){let s=paperState(),cs=[...d.candles].reverse().find(x=>x.cross_up||x.cross_down);let alerts=fd.alerts||{},oc=fd.option_chain||{};let desired=cs?(cs.cross_up?'CE':'PE'):null;
 if(cs&&cs.ts!==s.lastCross&&desired){let ad=desired==='CE'?alerts.call:alerts.put;if(ad&&ad.ltp&&ad.strike){
  if(s.pos&&s.pos.side!==desired){let row=optionRow(oc,s.pos.strike),px=row?(s.pos.side==='CE'?row.call_ltp:row.put_ltp):s.pos.entry;closePaper(s,Number(px),cs.ts,'OPPOSITE EMA CROSS')}
  if(!s.pos){let premium=Number(ad.ltp),lot=65,qty=Math.floor(s.cash/(premium*lot))*lot;if(qty>=lot){s.pos={side:desired,strike:ad.strike,entry:premium,qty,sl:Number(ad.stop_loss),t1:Number(ad.target_1),t2:Number(ad.target_2),entryTime:cs.ts,t1Hit:false,t2Hit:false,slHit:false};s.cash-=premium*qty}}
  s.lastCross=cs.ts;savePaper(s)}}
 if(s.pos){let row=optionRow(oc,s.pos.strike),cur=row?Number(s.pos.side==='CE'?row.call_ltp:row.put_ltp):null;if(Number.isFinite(cur)){if(cur<=s.pos.sl){s.pos.slHit=true;closePaper(s,cur,new Date().toISOString(),'STOP LOSS')}else if(cur>=s.pos.t2){s.pos.t1Hit=true;s.pos.t2Hit=true;closePaper(s,cur,new Date().toISOString(),'TARGET 2')}else if(cur>=s.pos.t1){s.pos.t1Hit=true;savePaper(s)}
  renderPaper(s,cur);return}}
 renderPaper(s,null)}
function closePaper(s,px,t,reason){let p=s.pos;if(!p)return;s.cash+=px*p.qty;let pnl=(px-p.entry)*p.qty;s.trades.push({...p,exit:px,exitTime:t,pnl,reason,balance:s.cash});s.pos=null;savePaper(s)}
function renderPaper(s,cur){let p=s.pos;$('ppos').textContent=p?'BUY '+p.side:'NONE';$('pcontract').textContent=p?(p.strike+' '+p.side):'--';$('pqty').textContent=p?p.qty:'--';$('pentry').textContent=p?'₹'+p.entry.toFixed(2):'--';$('pcurrent').textContent=Number.isFinite(cur)?'₹'+cur.toFixed(2):'--';$('plevels').textContent=p?('₹'+p.sl.toFixed(2)+' / ₹'+p.t1.toFixed(2)+' / ₹'+p.t2.toFixed(2)):'--';let open=p&&Number.isFinite(cur)?(cur-p.entry)*p.qty:0,equity=s.cash+(p&&Number.isFinite(cur)?cur*p.qty:0);$('pcash').textContent='₹'+s.cash.toFixed(2);$('pequity').textContent='₹'+equity.toFixed(2);$('ppnl').textContent='₹'+open.toFixed(2);$('ppnl').className=open>0?'green':open<0?'red':''}
function mkChart(el,type,data,opts){return new Chart(el,{type,data,options:{responsive:true,maintainAspectRatio:false,animation:false,interaction:{mode:'index',intersect:false},plugins:{legend:{labels:{color:'#c9d6e4'}}},scales:{x:{ticks:{color:'#8398ad',maxTicksLimit:12},grid:{color:'#142337'}},y:{ticks:{color:'#8398ad'},grid:{color:'#142337'}}},...opts}})}
async function load(){try{let r=await fetch('/api/v18/intraday-signal',{cache:'no-store'}),d=await r.json();if(d.status!=='success')throw Error(d.message||'Data error');
$('price').textContent=Number(d.price).toFixed(2);$('source').textContent=d.futures_symbol||d.data_source;$('sig').textContent=d.setup_state||d.signal;$('sig').className='sig '+((d.signal==='BUY CE'||d.setup_state==='BULLISH SETUP FORMING')?'green':(d.signal==='BUY PE'||d.setup_state==='BEARISH SETUP FORMING')?'red':'muted');
$('e20').textContent=d.ema20;$('e50').textContent=d.ema50;$('vwap').textContent=d.vwap;$('fut').textContent=d.futures_price;$('rsi').textContent=d.rsi14;$('score').textContent=d.bull_score+' / '+d.bear_score;$('last').textContent=new Date(d.last_completed_candle).toLocaleString('en-IN',{timeZone:'Asia/Kolkata'});
$('checks').innerHTML=Object.entries(d.checks).map(([k,v])=>'<div class="row"><span>'+k+'</span><b class="'+(v?'ok':'bad')+'">'+(v?'✓':'✕')+'</b></div>').join('');
let c=d.candles,L=c.map(x=>x.t);if(pc)pc.destroy();if(vc)vc.destroy();if(rc)rc.destroy();
pc=mkChart($('priceChart'),'line',{labels:L,datasets:[{label:'Close',data:c.map(x=>x.c),borderWidth:2,pointRadius:c.map(x=>x.cross_up||x.cross_down?5:0),pointStyle:c.map(x=>x.cross_up?'triangle':x.cross_down?'rectRot':'circle')},{label:'EMA 20',data:c.map(x=>x.e20),borderWidth:1,pointRadius:0},{label:'EMA 50',data:c.map(x=>x.e50),borderWidth:1,pointRadius:0},{label:'NIFTY FUT',data:c.map(x=>x.fut),borderWidth:1,pointRadius:0,borderDash:[4,4]},{label:'Futures VWAP',data:c.map(x=>x.fvwap),borderWidth:1,pointRadius:0,borderDash:[7,4]}]},{});
vc=mkChart($('volChart'),'bar',{labels:L,datasets:[{label:'Futures volume',data:c.map(x=>x.vol)},{label:'20-bar avg',type:'line',data:c.map(x=>x.vavg),pointRadius:0,borderWidth:1}]},{});
rc=mkChart($('rsiChart'),'line',{labels:L,datasets:[{label:'RSI 14',data:c.map(x=>x.rsi),pointRadius:0,borderWidth:2},{label:'55',data:c.map(()=>55),pointRadius:0,borderWidth:1,borderDash:[5,5]},{label:'45',data:c.map(()=>45),pointRadius:0,borderWidth:1,borderDash:[5,5]}]},{scales:{y:{min:0,max:100,ticks:{color:'#8398ad'},grid:{color:'#142337'}}}});
lastSignal=d;if(lastFno)runPaper(d,lastFno)}catch(e){$('sig').textContent='DATA ERROR';$('sig').className='sig red';$('checks').innerHTML='<div class="red">'+e.message+'</div>'}}
async function optionChain(){try{let r=await fetch('/api/v18/option-chain',{cache:'no-store'}),d=await r.json();if(d.status!=='success')throw Error(d.message||'Option chain unavailable');lastFno=d;if(lastSignal)runPaper(lastSignal,d);let o=d.option_chain||{},a=d.alerts||{},ce=a.call||{},pe=a.put||{};$('atm').textContent=o.atm_strike??'--';$('expiry').textContent=o.expiry??'--';$('ocmeta').textContent='NIFTY '+(d.price??'--')+' • Dashboard option-chain/target engine • '+(o.bias||'');
function lv(x){if(!x)return '--';return '₹'+(x.ltp??'--')+' | SL ₹'+(x.stop_loss??'--')+' | T1 ₹'+(x.target_1??'--')+' | T2 ₹'+(x.target_2??'--')}
$('ceSetup').textContent=(ce.strike??'--')+' CE';$('ceLevels').textContent=lv(ce);$('peSetup').textContent=(pe.strike??'--')+' PE';$('peLevels').textContent=lv(pe);
$('och').innerHTML=(o.nearby_strikes||[]).map(x=>'<tr><td>₹'+(x.call_ltp??'--')+'</td><td>'+(x.call_oi??'--')+'</td><td><b>'+x.strike+'</b></td><td>'+(x.put_oi??'--')+'</td><td>₹'+(x.put_ltp??'--')+'</td></tr>').join('')}catch(e){$('ocmeta').textContent='Option-chain error: '+e.message}}
function isoLocal(d){let y=d.getFullYear(),m=String(d.getMonth()+1).padStart(2,'0'),day=String(d.getDate()).padStart(2,'0');return y+'-'+m+'-'+day}
function quickBT(n){let now=new Date(),to=isoLocal(now),from;if(n===0)from=to;else{let d=new Date(now);d.setDate(d.getDate()-(n-1));from=isoLocal(d)}$('btFrom').value=from;$('btTo').value=to;backtest(from,to)}
function customBT(){let f=$('btFrom').value,t=$('btTo').value;if(!f||!t){$('btnote').textContent='Select both From and To dates.';return}let diff=(new Date(t)-new Date(f))/86400000;if(diff<0){$('btnote').textContent='From date cannot be after To date.';return}if(diff>89){$('btnote').textContent='Maximum selectable calendar range is 90 days.';return}backtest(f,t)}
async function backtest(fromDate=null,toDate=null){try{let url='/api/v18/backtest?days=45';if(fromDate&&toDate)url='/api/v18/backtest?from_date='+encodeURIComponent(fromDate)+'&to_date='+encodeURIComponent(toDate);let r=await fetch(url,{cache:'no-store'}),d=await r.json();if(d.status!=='success')throw Error(d.message);let money=x=>'₹'+Number(x).toLocaleString('en-IN',{maximumFractionDigits:2});$('btperiod').textContent='Period: '+d.actual_from+' → '+d.actual_to+' • '+d.trading_days+' trading day'+(d.trading_days===1?'':'s');$('btend').textContent=money(d.ending_capital);$('btn').textContent=money(d.net_pnl);$('btret').textContent=d.return_percent+'%';$('btt').textContent=d.trades;$('btw').textContent=d.win_rate+'%';$('btt1').textContent=d.target1_hits==null?'N/A':d.target1_hits;$('btt2').textContent=d.target2_hits==null?'N/A':d.target2_hits;$('btsl').textContent=d.stop_loss_hits==null?'N/A':d.stop_loss_hits;$('btdd').textContent=money(d.max_drawdown)+' ('+d.max_drawdown_percent+'%)';$('btnote').textContent=d.note;$('bth').innerHTML=d.history.slice(-20).reverse().map(t=>'<tr><td>'+t.side+'</td><td>'+t.entry+'</td><td>'+(t.stop_loss??'N/A')+'</td><td>'+(t.target1??'N/A')+'</td><td>'+(t.target2??'N/A')+'</td><td>'+(t.target1_hit==null?'N/A':t.target1_hit?'✓':'✕')+'</td><td>'+(t.target2_hit==null?'N/A':t.target2_hit?'✓':'✕')+'</td><td>'+(t.stop_loss_hit==null?'N/A':t.stop_loss_hit?'✓':'✕')+'</td><td>'+t.exit+'</td><td class="'+(t.pnl>0?'green':'red')+'">'+money(t.pnl)+'</td><td>'+money(t.balance)+'</td></tr>').join('')}catch(e){$('btnote').textContent='Backtest error: '+e.message}}
load();optionChain();backtest();setInterval(()=>{load();optionChain()},30000);
</script></body></html>""")

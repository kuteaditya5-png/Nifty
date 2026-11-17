"""Read-only five-minute candles for the nearest unexpired NIFTY future."""
import gzip
import json
import math
import os
from datetime import datetime, timedelta
from functools import lru_cache
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests
from fastapi.responses import JSONResponse

IST = ZoneInfo("Asia/Kolkata")
MASTER = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
API = "https://api.upstox.com/v3/historical-candle"

@lru_cache(maxsize=2)
def contract(day):
    response = requests.get(MASTER, timeout=(3, 15))
    response.raise_for_status()
    rows = json.loads(gzip.decompress(response.content))
    eligible = (r for r in rows if r.get("segment") == "NSE_FO"
                and r.get("instrument_type") == "FUT"
                and r.get("underlying_symbol") == "NIFTY"
                and datetime.fromtimestamp(r["expiry"]/1000, IST).date() >= day)
    return min(eligible, key=lambda r: r["expiry"])

def candles():
    headers = {"Cache-Control": "no-store"}
    def reply(body, status=200):
        return JSONResponse(body, status_code=status, headers=headers)
    token = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
    if not token:
        return reply({"error":"Set UPSTOX_ACCESS_TOKEN for futures candles"}, 503)
    now = datetime.now(IST)
    day = now.date()
    try:
        instrument = contract(day)
        key = quote(instrument["instrument_key"], safe="")
        def fetch(path):
            response = requests.get(API + path, headers={"Authorization":"Bearer "+token}, timeout=(3, 10))
            response.raise_for_status()
            return response.json()["data"]["candles"]
        rows = fetch(f"/intraday/{key}/minutes/5")
        if not rows:
            rows = fetch(f"/{key}/minutes/5/{day-timedelta(days=1)}/{day-timedelta(days=12)}")
        bars = {}
        for row in rows:
            stamp = datetime.fromisoformat(row[0])
            if stamp.tzinfo is None or stamp > now:
                continue
            o,h,l,c,v = map(float,row[1:6])
            if not all(map(math.isfinite,(o,h,l,c,v))) or not (0<l<=min(o,c)<=max(o,c)<=h and v>=0):
                continue
            time = int(stamp.timestamp()*1000)
            bars[time] = dict(time=time,open=o,high=h,low=l,close=c,volume=v)
        return reply({"symbol":instrument["trading_symbol"],"bars":[bars[t] for t in sorted(bars)]})
    except requests.HTTPError as err:
        code = err.response.status_code
        message = "Check Upstox token and market-data access" if code in (401,403) else f"Upstox request failed (HTTP {code})"
        return reply({"error":message},502)
    except (requests.RequestException,ValueError,KeyError,TypeError,OSError,IndexError,EOFError):
        return reply({"error":"Upstox contract or candle data unavailable"},502)

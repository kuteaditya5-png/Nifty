import pandas as pd
import v1523
from v1528 import load_pg_history_v1528

VERSION="15.29"
TARGET=12261

def merged_raw_history():
    import main
    base=main._v146_load_raw_history("15m",limit=50000)
    pg=load_pg_history_v1528()
    if base is None or len(base)==0:
        return pg.sort_index()
    b=base.copy()
    b.index=pd.to_datetime(b.index,utc=True,errors="coerce")
    b=b[~b.index.isna()]
    if pg is None or pg.empty:
        return b.sort_index()
    x=pd.concat([pg,b]).sort_index()
    return x[~x.index.duplicated(keep="last")]

def setup_v1529(app):
    @app.get("/api/regime/v1529-status")
    def status():
        try:
            x=merged_raw_history()
            return {"status":"success","version":VERSION,"merged_unique_rows":len(x),
                    "merged_start":str(x.index.min()) if len(x) else None,
                    "merged_end":str(x.index.max()) if len(x) else None,
                    "target_rows":TARGET,"ready":len(x)>=TARGET,
                    "validator":"/api/regime/frozen-validation-v1529",
                    "frozen_rule_changed":False,"live_routing_changed":False}
        except Exception as e:
            return {"status":"error","version":VERSION,"message":str(e),"live_routing_changed":False}

    @app.get("/api/regime/frozen-validation-v1529")
    def validate():
        # v15.23 imported _v146_load_raw_history directly into its module namespace.
        # Swap that reference only for this request, execute its registered validator
        # through a tiny capture app, then restore it.
        merged=merged_raw_history()
        if len(merged)<TARGET:
            return {"status":"error","version":VERSION,"message":"Merged history below target.",
                    "merged_unique_rows":len(merged),"target_rows":TARGET,"live_routing_changed":False}
        original=v1523._v146_load_raw_history
        def loader(timeframe="15m",limit=50000):
            if timeframe=="15m": return merged.tail(limit)
            return original(timeframe,limit)
        class CaptureApp:
            def __init__(self): self.fn=None
            def get(self,path):
                def deco(fn):
                    if "frozen" in path and "validation" in path: self.fn=fn
                    return fn
                return deco
        cap=CaptureApp()
        try:
            v1523._v146_load_raw_history=loader
            v1523.setup_v1523(cap)
            if cap.fn is None: raise RuntimeError("Unable to capture v15.23 frozen validator.")
            result=cap.fn()
            if isinstance(result,dict):
                result["version"]="15.29"
                result["integrated_history"]={"merged_unique_rows":len(merged),
                    "start":str(merged.index.min()),"end":str(merged.index.max()),
                    "source":"production + PostgreSQL nifty_15m_history_v1528"}
                result["frozen_rule_changed"]=False
                result["live_routing_changed"]=False
            return result
        finally:
            v1523._v146_load_raw_history=original

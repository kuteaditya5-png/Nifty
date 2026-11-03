import json
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import breakout_v1814 as b
import prediction_v1812 as shadow
import server_journal_v1814 as journal

IST=ZoneInfo('Asia/Kolkata')

def frame(n=30):
    idx=pd.date_range('2026-11-02 09:15',periods=n,freq='5min',tz=IST)
    return pd.DataFrame([{'Open':23000+i,'High':23003+i,'Low':22998+i,'Close':23001+i,'Volume':0} for i in range(n)],index=idx)

def test_forming_future_duplicate_and_naive():
    df=frame();now=df.index[-1]+pd.Timedelta(minutes=2)
    assert b.completed(df,now).index[-1]==df.index[-2]
    with pytest.raises(ValueError):b.completed(pd.concat([df,df.iloc[-1:]]),now)
    with pytest.raises(ValueError):b.completed(df.tz_localize(None),now)

def test_breakout_no_lookahead_and_alignment():
    df=frame();df.loc[df.index[-1],['Open','High','Low','Close']]=[23030,23051,23029,23050]
    now=df.index[-1]+pd.Timedelta(minutes=5)
    r=b.analyze(df,now)
    assert r['latest']['confirmed'] and r['latest']['direction']=='UP'
    assert b.adjust_score(.3,r)[0]==pytest.approx(.35)
    assert b.adjust_score(-.3,r)[0]==pytest.approx(-.25)
    assert b.adjust_score(0,r)[0]==0
    prefix=b.analyze(df.iloc[:-1],now)['records']
    assert prefix==r['records'][:-1]
    future=df.iloc[-1:].copy();future.index+=pd.Timedelta(minutes=5);future['Close']=99999
    assert b.analyze(pd.concat([df,future]),now)['records']==r['records']

def test_missing_opening_and_stale():
    df=frame().drop(frame().index[1]);r=b.analyze(df,df.index[-1]+pd.Timedelta(minutes=5))
    assert r['latest']['orb_high'] is None
    r=b.analyze(df,df.index[-1]+pd.Timedelta(minutes=25))
    assert not r['eligible'] and b.adjust_score(.3,r)[0]==.3

def test_wick_rejection_no_boost():
    df=frame();df.loc[df.index[-1],['Open','High','Low','Close']]=[23025,23070,23024,23026]
    r=b.analyze(df,df.index[-1]+pd.Timedelta(minutes=5))
    assert not r['latest']['confirmed']
    assert any(x['direction']=='REJECTION' for x in r['latest']['events'])
    assert b.adjust_score(.3,r)[0]==.3

def test_session_reset_and_zero_range():
    df=frame();tomorrow=frame().iloc[:4].copy();tomorrow.index+=pd.Timedelta(days=1)
    r=b.analyze(pd.concat([df,tomorrow]),tomorrow.index[-1]+pd.Timedelta(minutes=5))
    assert r['latest']['prior6_high'] is None
    df.loc[df.index[-1],['Open','High','Low','Close']]=23030
    r=b.analyze(df,df.index[-1]+pd.Timedelta(minutes=5))
    assert r['latest']['quality_flags']==['ZERO_RANGE'] and not r['eligible']

def test_closing_spike():
    df=frame(75);df.loc[df.index[-2],['Open','High','Low','Close']]=23074
    df.loc[df.index[-1],['Open','High','Low','Close']]=[23074,23184,23074,23184]
    r=b.analyze(df,df.index[-1]+pd.Timedelta(minutes=5))
    assert 'CLOSING_SPIKE_REVIEW' in r['latest']['quality_flags']
    assert not r['latest']['confirmed'] and not r['eligible']

def test_monotonic_rsi_finite():
    assert shadow._rsi(pd.Series(range(30))).iloc[-1]==100
    assert shadow._rsi(pd.Series([1]*30)).iloc[-1]==50

def test_monitor_auth_and_dedup(monkeypatch):
    app=FastAPI();provider=MagicMock();journal.register(app,provider)
    monkeypatch.setenv('NIFTY_MONITOR_SECRET','test-private-key')
    with TestClient(app) as c:
        assert c.post('/api/signal-journal/collect').status_code==403
        assert c.post('/api/signal-journal/collect',headers={'X-Monitor-Secret':'wrong'}).status_code==403
    provider.assert_not_called()
    conn=MagicMock();cur=conn.__enter__.return_value.cursor.return_value.__enter__.return_value
    monkeypatch.setattr(journal.signal_tracker,'connect',lambda:conn)
    cur.fetchone.side_effect=[(True,),('CAPTURED',)]
    result=journal.collect(provider,datetime(2026,11,2,10,1,tzinfo=IST))
    assert not result['recorded'];provider.assert_not_called()

def test_capture_and_missing_not_replayed(monkeypatch):
    conn=MagicMock();cur=conn.__enter__.return_value.cursor.return_value.__enter__.return_value
    cur.fetchone.side_effect=[(True,),None,('stored',)]
    monkeypatch.setattr(journal.signal_tracker,'connect',lambda:conn)
    now=datetime(2026,11,2,10,1,tzinfo=IST)
    provider=MagicMock(return_value={'status':'success','candle_at':'2026-11-02T09:55:00+05:30','decision_completed_at':now.isoformat(),'fno_setup':'WAIT'})
    assert journal.collect(provider,now)['recorded']
    assert provider.call_count==1
    inserts=[c for c in cur.execute.call_args_list if "VALUES(%s,'MISSING')" in c.args[0]]
    assert len(inserts)==9
    payload=cur.execute.call_args.args[1][1].obj
    assert payload['capture_delay_seconds']==60

def test_export_separates_missing(monkeypatch):
    from openpyxl import Workbook
    at=datetime(2026,11,2,9,15,tzinfo=IST)
    monkeypatch.setattr(journal,'export_rows',lambda day:[(at,at,'MISSING',{})])
    w=Workbook();journal.append_export(w)
    assert w['Server Decisions']['D2'].value=='MISSING'
    assert w['Server Decisions']['E2'].value is None
    assert w['Collection Coverage']['C2'].value==1

@pytest.fixture
def main_stub(monkeypatch):
    import main
    df=frame(75)
    monkeypatch.setattr(main.yf,'Ticker',lambda *a,**kw: type('Ticker',(),{'history':lambda self,**kw:df.copy()})())
    for name in ['get_news_articles','calculate_vix_dynamics','get_global_analysis','get_institutional_flow','get_option_chain_analysis','get_market_breadth','get_nifty_futures_analysis','get_premarket_analysis','get_cross_asset_context']:
        monkeypatch.setattr(main,name,lambda *a,**kw:{'status':'unavailable'})
    return main

def test_prediction_and_chart_contract(main_stub):
    result=main_stub.prediction(True)
    assert result['status']=='success',result
    assert result['fno_setup']=='WAIT'
    assert not result['option_data_available']
    assert 'option_chain' in result['failed_gates']['CE']
    from fastapi.encoders import jsonable_encoder
    json.dumps(jsonable_encoder(result),allow_nan=False)
    with TestClient(main_stub.app) as client:
        assert client.get('/prediction?include_alerts=true').status_code==200
        chart=client.get('/chart-data?interval=5m').json()
        assert chart['status']=='success'
        assert chart['breakout']['records']
        assert client.get('/chart-data?interval=15m').json()['breakout'] is None

def test_bearish_confirmation_and_bounds():
    df=frame();df[['Open','High','Low','Close']]=46000-df[['Open','Low','High','Close']].to_numpy()
    df.loc[df.index[-1],['Open','High','Low','Close']]=[22970,22971,22949,22950]
    r=b.analyze(df,df.index[-1]+pd.Timedelta(minutes=5))
    assert r['latest']['confirmed'] and r['latest']['direction']=='DOWN'
    assert b.adjust_score(-.3,r)[0]==pytest.approx(-.35)
    assert b.adjust_score(-.99,r)[0]==-1

def test_replay_date_retains_warmup(monkeypatch):
    import yfinance as yf
    prior=frame(75);prior.index-=pd.Timedelta(days=3)
    today=frame(20)
    df=pd.concat([prior,today])
    monkeypatch.setattr(yf,'Ticker',lambda *a,**kw:type('Ticker',(),{'history':lambda self,**kw:df.copy()})())
    app=FastAPI();shadow.register(app)
    with TestClient(app) as c:
        result=c.get('/api/v18-12/replay?date=2026-11-02').json()
        assert result['summary']['observations']==20


def test_stale_source_records_no_fake_snapshot(monkeypatch):
    conn=MagicMock();cur=conn.__enter__.return_value.cursor.return_value.__enter__.return_value
    cur.fetchone.side_effect=[(True,),None]
    monkeypatch.setattr(journal.signal_tracker,'connect',lambda:conn)
    now=datetime(2026,11,2,10,1,tzinfo=IST)
    result=journal.collect(lambda **kw:{'status':'success','candle_at':'2026-10-30T15:25:00+05:30','decision_completed_at':now.isoformat()},now)
    assert result['status']=='skipped'
    assert not any('INSERT INTO' in c.args[0] for c in cur.execute.call_args_list)

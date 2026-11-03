import io
from datetime import datetime
from unittest.mock import MagicMock
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook, Workbook
import candle_audit_v1815 as audit
import signal_tracker

def frame():
    idx=pd.date_range('2026-11-02 09:15',periods=75,freq='5min',tz=audit.IST).append(
        pd.date_range('2026-11-03 09:15',periods=35,freq='5min',tz=audit.IST))
    return pd.DataFrame([{'Open':23000+i*2,'High':23005+i*2,'Low':22998+i*2,'Close':23003+i*2,'Volume':0} for i in range(len(idx))],index=idx)

def test_predictions_prefix_invariant_and_no_future_payload():
    df=frame(); full=audit.replay_predictions(df); prefix=audit.replay_predictions(df.iloc[:-6])
    assert all(full[k]==v for k,v in prefix.items())
    changed=df.copy();changed.iloc[-1,changed.columns.get_loc('Close')]=99999
    altered=audit.replay_predictions(changed)
    assert full[df.index[-2].isoformat()]==altered[df.index[-2].isoformat()]
    assert all('future_points' not in p and 'direction_correct' not in p for p in full.values())

def test_exact_next_and_session_boundary():
    df=frame(); predictions=audit.replay_predictions(df)
    rows=audit.joined_rows(df,predictions,now=df.index[-1]+pd.Timedelta(minutes=10))
    last_day1=df.index[74].isoformat();assert rows[last_day1]['Evaluation Status']=='SESSION END'
    assert rows[last_day1]['Next Close'] is None
    current=df.index[80]; removed=df.drop(df.index[81])
    rows=audit.joined_rows(removed,predictions,now=df.index[-1]+pd.Timedelta(minutes=10))
    assert rows[current.isoformat()]['Evaluation Status']=='MISSING NEXT CANDLE'
    assert rows[current.isoformat()]['Next Close'] is None

def test_live_late_revision_quality_and_neutral():
    df=frame(); predictions=audit.replay_predictions(df);ts=df.index[80];key=ts.isoformat()
    p=predictions[key].copy();p['direction']='NEUTRAL';p['neutral_threshold']=2
    payload={'next_candle_audit':p,'fno_setup':'WATCH CE','confidence':44}
    live={key:(ts,ts+pd.Timedelta(minutes=5),payload)}
    r=audit.joined_rows(df,predictions,live)[key]
    assert r['Prediction Result']=='CORRECT' and r['Actual Next Direction']=='NEUTRAL'
    assert r['Trade Call']=='NOT RECORDED' and r['Live Market Confidence %']==44
    live[key]=(ts,ts+pd.Timedelta(minutes=5,seconds=1),payload)
    assert audit.joined_rows(df,predictions,live)[key]['Evaluation Status']=='LATE CAPTURE'
    assert audit.joined_rows(df,predictions,live)[key]['Prediction Result'] is None
    live[key]=(ts,ts+pd.Timedelta(minutes=5),payload)
    revised=df.copy();revised.loc[ts,'Close']+=.1
    assert audit.joined_rows(revised,predictions,live)[key]['Evaluation Status']=='REVISED SOURCE DATA'
    invalid=df.copy();invalid.loc[df.index[81],['Open','High','Low','Close']]=23000
    assert audit.joined_rows(invalid,predictions,live)[key]['Evaluation Status']=='EXCLUDED DATA QUALITY'

def test_modes_warmup_missing_and_first_capture(monkeypatch):
    df=frame();p=audit.replay_predictions(df)
    assert p[df.index[10].isoformat()]['direction'] is None
    rows=audit.joined_rows(df,p,mode='live')
    assert all(r['Prediction Source']=='MISSING' for r in rows.values())
    ts=df.index[80]; key=ts.isoformat();snapshot={'status':'success','candle_at':key,'next_candle_audit':p[key]}
    conn=MagicMock();cur=conn.__enter__.return_value.cursor.return_value.__enter__.return_value
    monkeypatch.setattr(signal_tracker,'connect',lambda:conn);cur.fetchone.return_value=None
    assert audit.save_live(snapshot,ts+pd.Timedelta(minutes=5,seconds=1))=='FIRST CAPTURE ALREADY SAVED'
    sql=cur.execute.call_args_list[-1].args[0]
    assert 'DO NOTHING' in sql and 'DO UPDATE' not in sql
    assert audit.save_live(snapshot,ts+pd.Timedelta(minutes=11)).startswith('SKIPPED')

def test_candle_endpoint_excel_auth_and_join(monkeypatch):
    import yfinance
    df=frame();ticker=MagicMock();ticker.history.return_value=df
    monkeypatch.setattr(yfinance,'Ticker',lambda symbol:ticker)
    monkeypatch.setattr(audit,'load_live',lambda day:({},'UNAVAILABLE TEST'))
    monkeypatch.setenv('SIGNAL_EXPORT_KEY','test-export-key')
    app=FastAPI();signal_tracker.register(app)
    with TestClient(app) as client:
        assert client.get('/api/signal-journal/candles.xlsx?date=2026-11-03').status_code==403
        h={'X-Signal-Export-Key':'test-export-key'}
        assert client.get('/api/signal-journal/candles.xlsx?date=2026-11-03&prediction_mode=bad',headers=h).status_code==422
        response=client.get('/api/signal-journal/candles.xlsx?date=2026-11-03',headers=h)
        assert response.status_code==200,response.text
        wb=load_workbook(io.BytesIO(response.content));ws=wb['NIFTY OHLCV']
        assert ws.max_row==36 and ws.max_column==35+len(audit.HEADERS)
        headers=[c.value for c in ws[1]];rows=[dict(zip(headers,r)) for r in ws.iter_rows(min_row=2,values_only=True)]
        assert rows[0]['Next Candle Prediction'] is not None # Prior-session warm-up retained.
        assert rows[0]['Prediction Source']=='REPLAY'
        assert rows[0]['Trade Call']=='NOT RECORDED'
        assert rows[0]['Next Close']==float(df.iloc[76].Close)
        assert rows[-1]['Next Close'] is None
        assert 'Prediction Review' in wb.sheetnames
        assert ticker.history.call_args.kwargs['start'].date()<datetime(2026,11,3).date()

def test_replay_independent_of_storage_and_no_source_mutation(monkeypatch):
    df=frame(); original=df.copy(deep=True)
    monkeypatch.setattr(audit,'load_live',lambda day:pytest.fail('Replay must not require DB'))
    wb=Workbook();ws=wb.active;ws.title='NIFTY OHLCV';ws.append(['Existing column'])
    day=df[df.index.date==datetime(2026,11,3).date()]
    for _ in day.index:ws.append(['preserved'])
    audit.append_to_workbook(wb,ws,day,df,datetime(2026,11,3).date(),mode='replay')
    assert all(ws.cell(i,1).value=='preserved' for i in range(2,len(day)+2))
    pd.testing.assert_frame_equal(df,original)

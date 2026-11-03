import pandas as pd
import pytest
from breakout_setup_v1816 import build
from breakout_v1814 import IST

def setup(down=False):
    idx=pd.date_range('2026-11-03 10:00',periods=2,freq='5min',tz=IST)
    df=pd.DataFrame([[100,111,99,110],[110,112,108,111]],index=idx,columns=['Open','High','Low','Close'])
    if down:
        df[['Open','High','Low','Close']]=220-df[['Open','Low','High','Close']].to_numpy()
    records=[{'candle_at':t.isoformat(),'candle_end':(t+pd.Timedelta(minutes=5)).isoformat(),'time':int(t.timestamp()),'confirmed':i==0,'direction':('DOWN' if down else 'UP') if i==0 else 'NONE','buffer_points':1,'quality_flags':[], 'events':[{'kind':'ORB','direction':'DOWN' if down else 'UP'}]} for i,t in enumerate(idx)]
    return df,{'records':records,'eligible':True},idx[-1]+pd.Timedelta(minutes=5)

@pytest.mark.parametrize('down',[False,True])
def test_symmetric_spot_levels(down):
    df,a,now=setup(down);p=build(df,a,now)
    assert p['status']=='ACTIVE' and p['risk_points']==12
    assert p['target_1_points']==12 and p['target_2_points']==24
    assert (p['target_2']<p['target_1']<p['entry']<p['stop_loss']) if down else (p['stop_loss']<p['entry']<p['target_1']<p['target_2'])

def test_stop_target_ambiguity_and_t2():
    df,a,now=setup();df.iloc[-1]=[110,140,90,111]
    assert build(df,a,now)['status']=='AMBIGUOUS'
    df.iloc[-1]=[110,140,109,139]
    assert build(df,a,now)['status']=='TARGET 2 TOUCHED'
    df.iloc[-1]=[110,112,90,95]
    assert build(df,a,now)['status']=='STOP TOUCHED'

def test_wait_stale_closed_quality_and_gap():
    df,a,now=setup();a['records'][0]['confirmed']=False
    assert not build(df,a,now)['show_levels']
    a['records'][0]['confirmed']=True;a['eligible']=False
    assert build(df,a,now)['status']=='STALE DATA'
    assert not build(df,a,now)['show_levels']
    assert build(df,a,pd.Timestamp('2026-11-03 16:00',tz=IST))['status']=='SESSION CLOSED'
    a['eligible']=True;a['records'][-1]['quality_flags']=['ZERO_RANGE']
    assert build(df,a,now)['status']=='DATA REVIEW'
    a['records'][-1]['quality_flags']=[]
    df.index=[df.index[0],df.index[-1]+pd.Timedelta(minutes=5)]
    assert build(df,a,now)['status']=='DATA GAP'

def test_expired():
    df,a,now=setup();a['records'][-1]['candle_end']=(df.index[0]+pd.Timedelta(minutes=35)).isoformat()
    assert build(df,a,now)['status']=='EXPIRED'

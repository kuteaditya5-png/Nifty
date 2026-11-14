import unittest
import pandas as pd
import fvg_v1817 as f
class FvgTests(unittest.TestCase):
 def frame(self, rows=None):
  rows=rows or [(99,101,98,100),(100,111,99,110),(110,113,105,112)]
  return pd.DataFrame(rows,columns=['Open','High','Low','Close'],index=pd.date_range('2026-11-05 09:15',periods=len(rows),freq='5min',tz='Asia/Kolkata'))
 def runf(self,df):return f.analyze(df,df.index[-1]+pd.Timedelta(minutes=5))
 def test_sides(self):
  df=self.frame();z=self.runf(df)['latest']['zone']
  self.assertEqual((z['direction'],z['lower'],z['upper'],z['status']),('UP',101,105,'FRESH'))
  m=df.copy()
  for a,b in [('Open','Open'),('High','Low'),('Low','High'),('Close','Close')]:m[a]=300-df[b]
  self.assertEqual(self.runf(m)['latest']['zone']['direction'],'DOWN')
 def test_lifecycle(self):
  df=self.frame([(99,101,98,100),(100,111,99,110),(110,113,105,112),(106,110,103,109),(109,110,99,100),(100,104,97,98),(98,108,97,107)])
  r=self.runf(df)['records']
  self.assertEqual(r[3]['zone']['status'],'PARTIAL');self.assertEqual(r[3]['signals'][0]['direction'],'UP')
  self.assertEqual(r[4]['zone']['status'],'INVERTED');self.assertEqual(r[4]['signals'],[])
  self.assertTrue(r[5]['signals'][0]['inverse']);self.assertEqual(r[6]['zone']['status'],'INVALIDATED')
 def test_no_lookahead(self):
  df=self.frame([(99,101,98,100),(100,111,99,110),(110,113,105,112),(106,110,103,109)])
  r=self.runf(df)
  for i in range(1,len(df)+1):self.assertEqual(self.runf(df.iloc[:i])['records'],r['records'][:i])
 def test_incomplete(self):
  df=self.frame();self.assertIsNone(f.analyze(df,df.index[-1]+pd.Timedelta(minutes=4))['latest']['zone'])
 def test_gap_and_session(self):
  for delta in [pd.Timedelta(minutes=5),pd.Timedelta(days=1)]:
   df=self.frame();df.index=[df.index[0],df.index[1],df.index[2]+delta]
   self.assertIsNone(self.runf(df)['latest']['zone'])
 def test_bad_data(self):
  df=self.frame();df.iloc[1,df.columns.get_loc('High')]=float('nan')
  self.assertIsNone(self.runf(df)['latest']['zone'])
 def test_stale(self):
  self.assertFalse(f.analyze(self.frame(),'2026-11-06 10:00+05:30')['eligible'])
 def test_export(self):
  import candle_audit_v1815 as a
  df=self.frame();now=df.index[-1]+pd.Timedelta(minutes=5);key=df.index[-1].isoformat()
  self.assertEqual(a.joined_rows(df,{},mode='replay',now=now)[key]['FVG Type'],'BULLISH FVG')
  self.assertEqual(a.joined_rows(df,{},mode='live',now=now)[key]['FVG Source'],'MISSING')
  live={key:(df.index[-1],now,{'fvg':self.runf(df)})}
  self.assertEqual(a.joined_rows(df,{},live=live,mode='live',now=now)[key]['FVG Source'],'LIVE')

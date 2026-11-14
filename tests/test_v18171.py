import pytest
import fvg_v1817 as f

def evidence(*sides, eligible=True):
 return {'eligible':eligible,'latest':{'quality':'OK','signals':[{'direction':s} for s in sides]}}

@pytest.mark.parametrize('sign,side,blocked',[(1,'UP','PE'),(-1,'DOWN','CE')])
def test_support_and_shared_cap(sign,side,blocked):
 score,a=f.adjust_score(.28*sign,evidence(side))
 assert score==pytest.approx(.33*sign) and a['blocked_sides']==[blocked]
 score,a=f.adjust_score(.33*sign,evidence(side),.05*sign)
 assert score==pytest.approx(.33*sign) and a['adjustment']==0
 score,a=f.adjust_score(.30*sign,evidence(side),.02*sign)
 assert score==pytest.approx(.33*sign)

@pytest.mark.parametrize('base,side',[(.4,'DOWN'),(-.4,'UP'),(.02,'DOWN'),(-.02,'UP')])
def test_opposition_does_not_flip(base,side):
 score,a=f.adjust_score(base,evidence(side))
 assert score*base>=0 and abs(score)==pytest.approx(max(0,abs(base)-.05))
 alerts={'call':{'signal':'BUY SIGNAL'},'put':{'signal':'WATCH'}}
 f.filter_alerts(alerts,a)
 assert alerts['call' if base>0 else 'put']['signal']=='WAIT'

@pytest.mark.parametrize('ev',[evidence(),evidence('UP',eligible=False)])
def test_absent_or_stale_unchanged(ev):
 score,a=f.adjust_score(.4,ev)
 assert score==.4 and a['blocked_sides']==[]

def test_conflicting_retests_block_both():
 score,a=f.adjust_score(.4,evidence('UP','DOWN'))
 assert score==pytest.approx(.35)
 alerts={'call':{'signal':'BUY SIGNAL'},'put':{'signal':'BUY SIGNAL'}}
 f.filter_alerts(alerts,a)
 assert all(v['signal']=='WAIT' for v in alerts.values())

def test_no_standalone_trade_or_repeated_votes():
 score,a=f.adjust_score(0,evidence('UP','UP'))
 assert score==0
 score,a=f.adjust_score(.4,evidence('UP','UP'))
 assert score==pytest.approx(.45)
 alerts={'call':{'signal':'WAIT'},'put':{'signal':'WAIT'}}
 f.filter_alerts(alerts,a)
 assert alerts['call']['signal']=='WAIT'

def test_pipeline_order():
 from pathlib import Path
 source=Path('main.py').read_text()
 start=source.index('        combined_score, breakout_adjustment =')
 s=source[start:]
 assert s.index('fvg_v1817.adjust_score(')<s.index('direction_strength = abs(combined_score)')<s.index('fno_alerts = build_fno_alert_engine(')<s.index('fvg_v1817.filter_alerts(')<s.index('        snapshot = {')
 assert 'watch_gates[side]["fvg_alignment"]' in s

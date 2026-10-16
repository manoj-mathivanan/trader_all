import tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
from core.research import store,investor_paper as paper,investor_scores as scores,investor_workflow as workflow

class PaperTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.data=patch.object(store,'DATA',Path(self.temp.name));self.data.start()
  p=paper.state();p['activated_at']='2026-10-01T00:00:00+00:00';store.write(paper.NAME,p)
  self.targets=patch.object(workflow,'score_targets',return_value=[dict(isin='X',kind='candidate',company={'symbol':'X'})]);self.targets.start()
  self.external=patch.object(workflow,'paper_holdings',return_value=[]);self.external.start()
  self.clock=patch.object(paper.intel.company,'utcnow',return_value=datetime(2026,10,5,12,tzinfo=timezone.utc));self.clock.start()
 def tearDown(self):
  self.clock.stop();self.external.stop();self.targets.stop();self.data.stop();self.temp.cleanup()
 def signal(self,at='2026-10-01T10:00:00+00:00',stop=95,target=115):
  store.write('investor/assessments/score-latest-X-candidate',dict(id='s1',as_of=at,decision='buy_candidate',score=80,model=scores.MODEL,entry_plan=dict(stop=stop,target=target)))
 def bars(self,**kw):
  rows=[dict(date='2026-10-01',open=99,high=102,low=98,close=100),dict(date='2026-10-02',open=100,high=104,low=96,close=102)]
  rows[-1].update(kw)
  store.write('investor/stock_details/X',dict(technical=dict(status='available',price_date=rows[-1]['date'],audited_bars=rows)))
 def test_next_session_fill_costs_and_idempotence(self):
  self.signal();self.bars();paper.run(None);p=paper.state();pos=p['positions']['X']
  self.assertEqual(pos['entry_date'],'2026-10-02');self.assertAlmostEqual(pos['entry_price'],100.15)
  self.assertLessEqual(pos['cost'],10000);self.assertLessEqual(pos['quantity']*(100.15-95),500)
  paper.run(None);self.assertEqual(paper.state()['cash'],p['cash']);self.assertEqual(len(paper.state()['decisions']),1)
 def test_stop_first_when_both_touch(self):
  self.signal();self.bars(high=120,low=90);paper.run(None);p=paper.state()
  self.assertFalse(p['positions']);self.assertEqual(p['trades'][0]['reason'],'stop');self.assertLess(p['trades'][0]['net_pnl'],0)
 def test_opening_gap_cancels_bad_risk(self):
  self.signal();self.bars(open=120,high=125,low=119,close=121);paper.run(None)
  self.assertEqual(paper.state()['decisions'][0]['status'],'cancelled');self.assertEqual(paper.state()['cash'],100000)
 def test_old_signal_and_external_holding_never_enter(self):
  self.signal(at='2026-09-30T10:00:00+00:00');self.bars();paper.run(None);self.assertFalse(paper.state()['positions'])
  store.write(paper.NAME,dict(paper.state(),processed=[]));self.signal();self.external.stop();self.external=patch.object(workflow,'paper_holdings',return_value=[{'isin':'X'}]);self.external.start()
  paper.run(None);self.assertFalse(paper.state()['positions'])
 def test_revised_prices_pause_position(self):
  self.signal();self.bars();paper.run(None);self.bars(open=50,close=51,high=52,low=48);paper.run(None)
  self.assertIn('paused',paper.state()['positions']['X']);self.assertFalse(paper.state()['trades'])
 def test_missing_or_incomplete_bars_do_not_fill(self):
  self.signal();store.write('investor/stock_details/X',dict(technical=dict(status='unavailable')));paper.run(None)
  self.assertFalse(paper.state()['positions']);self.assertTrue(paper.state()['pending'])
 def test_plan_uses_atr_and_positive_stop(self):
  self.assertEqual(paper.plan({},dict(close=100,atr14=2))['stop_price'],96)
  self.assertIsNone(paper.plan({},dict(close=100))['stop_price'])

 def test_new_same_session_avoid_revokes_pending_entry(self):
  self.signal();paper.run(None);self.assertTrue(paper.state()['pending'])
  v=store.read('investor/assessments/score-latest-X-candidate');v.update(id='s2',decision='avoid',as_of='2026-10-01T11:00:00+00:00');store.write('investor/assessments/score-latest-X-candidate',v)
  self.bars();paper.run(None);self.assertFalse(paper.state()['positions']);self.assertFalse(paper.state()['pending'])

 def test_benchmark_does_not_include_pre_activation_returns(self):
  store.write('bars/NIFTY50',dict(bars=[dict(date='2026-09-30',close=100)]));paper.run(None)
  self.assertIsNone(paper.state()['benchmark']['return_pct']);self.assertNotIn('benchmark_base',paper.state())
  store.write('bars/NIFTY50',dict(bars=[dict(date='2026-10-01',close=100),dict(date='2026-10-03',close=105)]));paper.run(None)
  self.assertAlmostEqual(paper.state()['benchmark']['return_pct'],5)

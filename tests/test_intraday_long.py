import unittest
from unittest.mock import patch
from datetime import datetime, timedelta
from core.research import intraday_long, backtest
from core.research.config import BacktestConfig
from tests.test_intraday_short import minute_bars


class IntradayLongTests(unittest.TestCase):
    def setUp(self):
        self.daily = {'A':[dict(date=d,open=100,high=101,low=99,close=100,volume=10000)
                           for d in ('2025-02-01','2025-02-02','2025-02-03')]}
        self.cfg = BacktestConfig(pattern='blue_sky',start='2025-02-02',end='2025-02-03',acknowledge_limitations=True,
                                  execution_horizon='intraday',entry_mode='next_open',capital=10000,
                                  risk_pct=1,stop_pct=8,winner_exit='take_15',slippage_bps=0,buy_cost_bps=0,sell_cost_bps=0)
        self.plan = {'2025-02-02':[dict(symbol='A',signal_date='2025-02-01',signal_index=0,daily_index=1)]}
        self.minutes = {'A':{'2025-02-02':minute_bars('2025-02-02')}}

    def run_engine(self):
        return intraday_long.simulate(self.daily,self.cfg,self.minutes,plan=self.plan)

    def test_cutoff_open_no_future_prices_and_buy_first(self):
        next(b for b in self.minutes['A']['2025-02-02'] if b['time']=='15:00').update(open=105,high=200,low=1,close=100)
        result = self.run_engine()
        t = result['trades'][0]
        self.assertEqual((t['direction'],t['entry_time'],t['exit_time'],t['exit']),('long','09:15','15:00',105))
        self.assertEqual(t['entry_date'],t['exit_date'])
        self.assertEqual(t['pnl'],5*t['quantity'])
        self.assertEqual([o['side'] for o in result['state']['orders']],['buy','sell'])
        self.assertEqual(result['metrics']['overnight_positions'],0)

    def test_stop_first_ambiguity_and_adverse_gap(self):
        self.minutes['A']['2025-02-02'][1].update(high=116,low=91)
        result = self.run_engine()
        self.assertEqual(result['trades'][0]['exit'],92)
        self.assertEqual(result['metrics']['ambiguous_stop_target_bars'],1)
        self.minutes['A']['2025-02-02'][1].update(open=80,high=81,low=79,close=80)
        self.assertEqual(self.run_engine()['trades'][0]['exit'],80)

    def test_target_and_next_bar_stop(self):
        self.minutes['A']['2025-02-02'][1].update(high=116,close=115)
        self.assertAlmostEqual(self.run_engine()['trades'][0]['exit'],115)
        self.minutes['A']['2025-02-02'][0].update(high=110,close=109)
        self.minutes['A']['2025-02-02'][1].update(open=99,high=100,low=98,close=99)
        t = self.run_engine()['trades'][0]
        self.assertEqual(t['stop_trace'][0]['stop'],92)
        self.assertAlmostEqual(t['stop_trace'][1]['stop'],100.28)
        self.assertEqual(t['exit'],99)

    def test_costs_reconcile_and_capital_cannot_reuse_same_open(self):
        self.cfg.slippage_bps,self.cfg.buy_cost_bps,self.cfg.sell_cost_bps = 10,35,50
        result = self.run_engine()
        self.assertAlmostEqual(result['metrics']['final_equity']-self.cfg.capital,sum(t['pnl'] for t in result['trades']),places=2)
        self.assertGreater(result['metrics']['modeled_fees'],0)
        self.assertGreater(result['metrics']['modeled_slippage'],0)
        self.cfg.risk_pct=5
        self.daily['B']=self.daily['A']
        self.daily['C']=self.daily['A']
        self.minutes['B']=self.minutes['A']
        self.minutes['C']=self.minutes['A']
        self.plan['2025-02-02'] += [{**self.plan['2025-02-02'][0],'symbol':s} for s in ('B','C')]
        result=self.run_engine()
        self.assertLessEqual(sum(t['entry']*t['quantity']*(1+self.cfg.buy_cost_bps/10000) for t in result['trades']),self.cfg.capital)

    def test_missing_minutes_and_daily_engine_reject(self):
        self.minutes['A']['2025-02-02']=[b for b in self.minutes['A']['2025-02-02'] if b['time']!='15:00']
        with self.assertRaisesRegex(ValueError,'Incomplete regular-session'):
            self.run_engine()
        with self.assertRaisesRegex(ValueError,'five-minute inputs'):
            backtest.simulate(self.daily,self.cfg)

    def test_verified_special_session_is_excluded_with_evidence(self):
        self.cfg.start='2025-10-20'
        self.cfg.end='2025-10-22'
        self.daily={'A':[dict(date='2025-10-21',open=100,high=101,low=99,close=100,volume=10000)]}
        self.plan={'2025-10-21':[dict(symbol='A',signal_date='2025-10-20',signal_index=0,daily_index=0)]}
        result=self.run_engine()
        self.assertEqual(result['trades'],[])
        self.assertIn('CMTR70319.pdf',result['excluded_sessions'][0]['evidence']['source'])

    def test_plan_uses_prior_signal_not_entry_close(self):
        calls=[]
        def predicate(rows,i,cfg):
            calls.append(rows[i]['date'])
            return rows[i]['close']>100
        self.daily['A'][0]['close']=101
        self.daily['A'][1]['close']=1
        with patch('strategies.swing_patterns.patterns.signals.matches',side_effect=predicate):
            plan=intraday_long.entry_plan(self.daily,self.cfg)
        self.assertEqual(list(plan),['2025-02-02'])
        self.assertEqual(plan['2025-02-02'][0]['signal_date'],'2025-02-01')
        self.assertEqual(calls,['2025-02-01','2025-02-02'])


if __name__=='__main__':
    unittest.main()

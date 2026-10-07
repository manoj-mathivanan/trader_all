import unittest
from datetime import datetime,timedelta
from pydantic import ValidationError
from core.research import intraday_short,intraday_data,backtest
from core.research.config import BearishBacktestConfig


def minute_bars(day):
    start = datetime.fromisoformat(day+'T09:15:00+05:30')
    return [dict(date=day,time=(start+timedelta(minutes=5*i)).strftime('%H:%M'),
                 timestamp=int((start+timedelta(minutes=5*i)).timestamp()*1000),
                 open=100,high=101,low=99,close=100,volume=10000) for i in range(75)]


class IntradayShortTests(unittest.TestCase):
    def setUp(self):
        self.daily = {'A':[dict(date=d,open=100,high=101,low=99,close=100,volume=10000)
                           for d in ('2025-02-01','2025-02-02','2025-02-03')]}
        self.cfg = BearishBacktestConfig(start='2025-02-02',end='2025-02-03',acknowledge_limitations=True,
                                         execution_horizon='intraday',entry_mode='next_open',capital=10000,
                                         risk_pct=1,stop_pct=8,winner_exit='take_15',slippage_bps=0,
                                         buy_cost_bps=0,sell_cost_bps=0)
        self.plan = {'2025-02-02':[dict(symbol='A',signal_date='2025-02-01',signal_index=0,daily_index=1)]}
        self.minutes = {'A':{'2025-02-02':minute_bars('2025-02-02')}}

    def run_engine(self):
        return intraday_short.simulate(self.daily,self.cfg,self.minutes,plan=self.plan)

    def test_hard_1500_buyback_uses_open_and_no_future_prices(self):
        cutoff = next(b for b in self.minutes['A']['2025-02-02'] if b['time']=='15:00')
        cutoff.update(open=95,high=200,low=1,close=100)
        result = self.run_engine()
        t = result['trades'][0]
        self.assertEqual((t['entry_time'],t['exit_time'],t['exit']),('09:15','15:00',95))
        self.assertEqual(t['entry_date'],t['exit_date'])
        self.assertEqual(t['reason'],'Mandatory intraday square-off')
        self.assertEqual(t['pnl'],5*t['quantity'])
        self.assertEqual(result['state']['positions'],{})
        self.assertEqual(result['metrics']['overnight_positions'],0)
        self.assertEqual(result['metrics']['modeled_borrow_costs'],0)

    def test_stop_first_when_same_bar_hits_stop_and_target(self):
        self.minutes['A']['2025-02-02'][1].update(high=109,low=84)
        result = self.run_engine()
        t = result['trades'][0]
        self.assertEqual(t['exit'],108)
        self.assertLess(t['pnl'],0)
        self.assertEqual(result['metrics']['ambiguous_stop_target_bars'],1)

    def test_target_and_adverse_stop_gap(self):
        self.minutes['A']['2025-02-02'][1].update(low=84,close=85)
        t = self.run_engine()['trades'][0]
        self.assertEqual(t['exit'],85)
        self.assertEqual(t['exit_time'],'09:20')
        self.minutes['A']['2025-02-02'][1].update(open=120,high=121,low=119,close=120)
        t = self.run_engine()['trades'][0]
        self.assertEqual(t['exit'],120)
        self.assertEqual(t['reason'],'Intraday gap through stop')

    def test_missing_cutoff_is_an_error_not_overnight_or_daily_substitution(self):
        self.minutes['A']['2025-02-02'] = [b for b in self.minutes['A']['2025-02-02'] if b['time']!='15:00']
        with self.assertRaisesRegex(ValueError,'Incomplete regular-session'):
            self.run_engine()
        with self.assertRaisesRegex(ValueError,'five-minute inputs'):
            backtest.simulate(self.daily,self.cfg)

    def test_close_updates_activate_next_bar(self):
        self.minutes['A']['2025-02-02'][0].update(low=90,close=91)
        self.minutes['A']['2025-02-02'][1].update(open=102,high=103,low=101,close=102)
        t = self.run_engine()['trades'][0]
        self.assertEqual(t['stop_trace'][0]['stop'],108)
        self.assertAlmostEqual(t['stop_trace'][1]['stop'],98.28)
        self.assertEqual(t['exit'],102)

    def test_fees_and_slippage_reconcile(self):
        self.cfg.slippage_bps,self.cfg.buy_cost_bps,self.cfg.sell_cost_bps = 10,35,50
        result = self.run_engine()
        self.assertGreater(result['metrics']['modeled_fees'],0)
        self.assertGreater(result['metrics']['modeled_slippage'],0)
        self.assertAlmostEqual(result['metrics']['final_equity']-self.cfg.capital,
                               sum(t['pnl'] for t in result['trades']),places=2)

    def test_invalid_intraday_entry_or_cutoff(self):
        for change in ({'entry_mode':'close'},{'square_off_time':'15:30'},{'square_off_time':'15:03'},{'borrow_cost_bps_year':10}):
            with self.assertRaises(ValidationError):
                BearishBacktestConfig(**{**self.cfg.model_dump(),**change})

    def test_minute_normalization_and_duplicate_rejection(self):
        row = ['2025-02-02T09:15:00+05:30',100,101,99,100,100]
        normalized = intraday_data.normalize([row],'2025-02-02')
        self.assertEqual(normalized[0]['time'],'09:15')
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            intraday_data.normalize([row,row],'2025-02-02')
        with self.assertRaisesRegex(ValueError,'timezone'):
            intraday_data.normalize([['2025-02-02T09:15:00',100,101,99,100,100]],'2025-02-02')


if __name__=='__main__':
    unittest.main()

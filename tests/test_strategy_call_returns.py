import unittest
from datetime import date,timedelta
from unittest.mock import patch
from core.research import backtest
from core.research.config import BacktestConfig
from scripts.research_stock_call_accuracy import outcome
from scripts.research_strategy_call_returns import period_stats


class PeriodIsolationTests(unittest.TestCase):
    def call(self,signal,entry,exit_date,ret):
        return dict(symbol='TEST',signal_date=signal,entry_date=entry,exit_date=exit_date,
                    return_pct=ret,holding_sessions=10,status='correct' if ret>0 else 'incorrect')

    def test_future_exit_cannot_influence_selection(self):
        calls=[self.call('2022-11-01','2022-11-02','2022-11-16',4),
               self.call('2022-12-20','2022-12-21','2023-02-01',80)]
        result=period_stats(calls,'2019-01-01','2022-12-31')
        self.assertEqual(result['closed'],1)
        self.assertEqual(result['open'],1)
        self.assertEqual(result['mean_return_pct'],4)

    def test_signal_before_validation_is_not_validation_entry(self):
        calls=[self.call('2022-12-30','2023-01-02','2023-02-01',80),
               self.call('2023-02-01','2023-02-02','2023-03-01',-6)]
        result=period_stats(calls,'2023-01-01','2024-12-31')
        self.assertEqual(result['closed'],1)
        self.assertEqual(result['mean_return_pct'],-6)

    def test_entry_after_cutoff_is_not_an_open_selection_call(self):
        calls=[self.call('2022-12-30','2023-01-02','2023-02-01',80)]
        result=period_stats(calls,'2019-01-01','2022-12-31')
        self.assertEqual(result['signals'],0)
        self.assertIsNone(result['mean_return_pct'])

    def test_trailing_exits_match_existing_engine(self):
        rows=[]
        for i in range(250):
            close=100 if i<=160 else 100+(i-160)*2 if i<230 else 80
            opening=rows[-1]['close'] if rows else close
            rows.append(dict(date=(date(2020,1,1)+timedelta(days=i)).isoformat(),
                             open=opening,high=max(opening,close)+1,low=min(opening,close)-1,
                             close=close,volume=1000000))
        for pattern in ('breakout','blue_sky','vcp','multiyear'):
            for exit_rule in ('trail_50d','trail_30w'):
                with self.subTest(pattern=pattern,exit=exit_rule):
                    cfg=BacktestConfig(pattern=pattern,entry_mode='next_open',winner_exit=exit_rule,
                        max_hold_days=1000,start=rows[0]['date'],end=rows[-1]['date'],
                        slippage_bps=0,buy_cost_bps=0,sell_cost_bps=0,acknowledge_limitations=True)
                    result=outcome(rows,160,cfg)
                    with patch.object(backtest,'signal',side_effect=lambda rows,i,cfg:i==160):
                        engine=backtest.simulate({'TEST':rows},cfg,liquidate=False)
                    trade=engine['trades'][0]
                    self.assertEqual((result['entry_date'],result['exit_date'],result['entry'],result['exit']),
                                     (trade['entry_date'],trade['exit_date'],trade['entry'],trade['exit']))


if __name__=='__main__':
    unittest.main()

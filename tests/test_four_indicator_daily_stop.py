import copy
from datetime import date, timedelta
from types import SimpleNamespace
import unittest

from scripts.research_four_indicator_daily_stop import simulate, StopPlan
from scripts.research_four_indicator_exits import simulate as reference, ExitPlan, exit_features


class DailyStopTests(unittest.TestCase):
    def fixture(self):
        start = date(2025,1,1)
        bars = [dict(date=str(start+timedelta(days=i)),open=100.,high=101.,low=99.,close=100.,volume=1000)
                for i in range(108)]
        cfg = SimpleNamespace(start=bars[100]['date'],end=bars[-1]['date'],capital=10000.,
                              max_positions=1,slippage_bps=0,buy_cost_bps=0,sell_cost_bps=0)
        signals = [dict(exit=False,checks=[dict(passed=i == 100) for _ in range(4)]) for i in range(108)]
        return {'A':bars}, {'A':signals}, cfg

    def test_no_stop_matches_existing_daily_replay(self):
        data, signals, cfg = self.fixture()
        levels = exit_features(data)
        self.assertEqual(simulate(data,signals,levels,cfg,StopPlan()),
                         reference(data,signals,levels,cfg,ExitPlan()))

    def test_completed_close_trigger_fills_next_open_and_ignores_future_close(self):
        data, signals, cfg = self.fixture()
        data['A'][101].update(close=97,low=96)
        data['A'][102].update(open=90,close=92,low=89)
        result = simulate(data,signals,exit_features(data),cfg,StopPlan(stop_pct=2))
        trade = result['trades'][0]
        self.assertEqual(trade['exit_date'],data['A'][102]['date'])
        self.assertEqual(trade['exit'],90)
        self.assertIn('loss at daily close',trade['reason'])
        changed = copy.deepcopy(data);changed['A'][102].update(close=1000,high=1001)
        future = simulate(changed,signals,exit_features(changed),cfg,StopPlan(stop_pct=2))
        self.assertEqual(result['orders'],future['orders'])

    def test_low_touch_without_close_breach_does_not_trigger(self):
        data, signals, cfg = self.fixture()
        data['A'][101]['low']=90
        result = simulate(data,signals,exit_features(data),cfg,StopPlan(stop_pct=2))
        self.assertIn('End of backtest',result['trades'][0]['reason'])


if __name__ == '__main__': unittest.main()

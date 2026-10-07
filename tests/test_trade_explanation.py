import unittest
from copy import deepcopy
from datetime import date, timedelta
from core.research.trade_chart import explain_trade


class TradeExplanationTests(unittest.TestCase):
    def fixture(self):
        rows=[]
        for i in range(245):
            close=100 if i<220 else 110 if i==220 else 112 if i==221 else 125
            rows.append(dict(date=(date(2024,1,1)+timedelta(days=i)).isoformat(),
                             timestamp=1704067200000+i*86400000,open=close,high=close+1,
                             low=close-1,close=close,volume=2000 if i==220 else 1000))
        trade=dict(symbol='TEST',entry_date=rows[221]['date'],exit_date=rows[230]['date'],
                   entry=112,exit=125,quantity=10,pnl=130,reason='End of available test data')
        config=dict(pattern='blue_sky',entry_mode='next_open',sma_days=20,
                    volume_multiple=1.5,min_turnover=0,stop_pct=8,slippage_bps=0,
                    buy_cost_bps=0,sell_cost_bps=0,require_long_trend=True)
        return rows,trade,{'config':config}

    def test_full_warmup_averages_and_signal_exclude_future(self):
        rows,trade,result=self.fixture();original=deepcopy(rows)
        x=explain_trade(result,{'TEST':rows},trade,rows,221,230)
        self.assertEqual(rows,original)
        self.assertEqual(x['bars'][200]['chart_values']['sma_200'],100)
        self.assertEqual(x['bars'][220]['chart_values']['trigger'],101)
        self.assertEqual(x['signal']['date'],rows[220]['date'])
        self.assertTrue(all(c['passed'] for c in x['checks']))
        rows[-1]['close']=100000
        y=explain_trade(result,{'TEST':rows},trade,rows,221,230)
        self.assertEqual(x['checks'],y['checks'])
        self.assertEqual(x['bars'][220]['chart_values'],y['bars'][220]['chart_values'])

    def test_stop_update_activates_next_session(self):
        rows,trade,result=self.fixture()
        x=explain_trade(result,{'TEST':rows},trade,rows,221,230)
        self.assertAlmostEqual(x['bars'][222]['chart_values']['protective_stop'],112*.92)
        self.assertAlmostEqual(x['bars'][223]['chart_values']['protective_stop'],112)
        values=[b['chart_values']['protective_stop'] for b in x['bars'][221:231]]
        self.assertEqual(values,sorted(values))
        self.assertNotIn('protective_stop',x['bars'][231]['chart_values'])

    def test_close_signal_and_target_rule(self):
        rows,trade,result=self.fixture()
        result['config'].update(entry_mode='close',winner_exit='take_25')
        x=explain_trade(result,{'TEST':rows},trade,rows,220,230)
        self.assertEqual(x['signal']['date'],rows[220]['date'])
        self.assertEqual(x['bars'][220]['chart_values']['target'],140)

    def test_15_percent_target_and_fixed_target_stop_trace(self):
        rows,trade,result=self.fixture()
        result['config'].update(winner_exit='take_15')
        x=explain_trade(result,{'TEST':rows},trade,rows,221,230)
        self.assertAlmostEqual(x['bars'][221]['chart_values']['target'],112*1.15)
        self.assertEqual(next(s['label'] for s in x['series'] if s['id']=='target'), '+15% profit target')
        self.assertAlmostEqual(x['bars'][223]['chart_values']['protective_stop'],125*.92)

    def test_8_percent_target_label_and_price(self):
        rows,trade,result=self.fixture()
        result['config'].update(winner_exit='take_8',stop_pct=4)
        x=explain_trade(result,{'TEST':rows},trade,rows,221,230)
        self.assertAlmostEqual(x['bars'][221]['chart_values']['target'],112*1.08)
        self.assertAlmostEqual(x['bars'][221]['chart_values']['initial_stop'],112*.96)
        self.assertEqual(next(s['label'] for s in x['series'] if s['id']=='target'), '+8% profit target')

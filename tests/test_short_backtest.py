import unittest
import tempfile
from pathlib import Path
from datetime import date, timedelta
from unittest.mock import patch
from core.research import backtest, bearish, corporate_actions, store
from core.research.config import BearishBacktestConfig, Settings
from core.research.short_trade_chart import explain_trade


def rows(prices):
    return [dict(date=(date(2024, 1, 1)+timedelta(days=i)).isoformat(), open=p, high=p+1, low=p-1,
                 close=p, volume=1000000) for i, p in enumerate(prices)]


class ShortBacktestTests(unittest.TestCase):
    def cfg(self, bars, **values):
        return BearishBacktestConfig(start=bars[127]['date'], end=bars[-1]['date'], capital=10000,
                                    risk_pct=1, stop_pct=10, entry_mode='next_open', winner_exit='take_15',
                                    acknowledge_limitations=True, require_weak_market=False,
                                    require_falling_long_trend=False, slippage_bps=0, buy_cost_bps=0,
                                    sell_cost_bps=0, **values)

    def simulate(self, datasets, cfg):
        with patch.object(bearish, 'evaluate', return_value=dict(breakdown_level=99)):
            return backtest.simulate(datasets, cfg, entry_warmup=126)

    def test_short_profit_equity_and_sell_then_buy(self):
        bars = rows([100]*129)
        bars[127].update(open=100, high=101, low=89, close=90)
        bars[128].update(open=90, high=91, low=83, close=84)
        result = self.simulate({'A': bars}, self.cfg(bars))
        t = result['trades'][0]
        self.assertEqual((t['direction'], t['entry'], t['exit'], t['quantity']), ('short', 100, 84, 10))
        self.assertEqual(t['pnl'], 160)
        self.assertEqual(result['curve'][0]['equity'], 10100)
        self.assertEqual([o['side'] for o in result['state']['orders']], ['sell', 'buy'])
        self.assertEqual(result['metrics']['final_equity'], 10160)

    def test_short_stop_and_adverse_gap(self):
        for opening, high, loss in ((100, 111, 100), (120, 121, 200)):
            bars = rows([100]*130)
            bars[128].update(open=opening, high=high, low=99, close=100)
            result = self.simulate({'A': bars}, self.cfg(bars))
            self.assertAlmostEqual(result['trades'][0]['pnl'], -loss)
            self.assertEqual(result['trades'][0]['reason'], 'Gap through stop' if opening==120 else 'Stop loss / trailing stop')

    def test_proceeds_do_not_fund_additional_shorts(self):
        bars = rows([100]*129)
        cfg = self.cfg(bars, max_rs_rating=100, max_positions=50)
        cfg.capital, cfg.risk_pct = 1000, 5
        result = self.simulate({s: bars for s in ('A', 'B', 'C')}, cfg)
        self.assertEqual(len(result['trades']), 2)
        self.assertEqual(sum(t['quantity']*t['entry'] for t in result['trades']), 1000)

    def test_calendar_borrow_cost_and_broker_cost_accounting(self):
        bars = rows([100]*130)
        bars[-1]['date'] = (date.fromisoformat(bars[-2]['date'])+timedelta(days=3)).isoformat()
        cfg = self.cfg(bars, borrow_cost_bps_year=3650)
        result = self.simulate({'A': bars}, cfg)
        self.assertAlmostEqual(result['metrics']['modeled_borrow_costs'], 4)
        self.assertAlmostEqual(result['trades'][0]['pnl'], -4)
        self.assertAlmostEqual(result['metrics']['final_equity'], 9996)
        cfg.buy_cost_bps, cfg.sell_cost_bps, cfg.slippage_bps = 35, 50, 10
        costed = self.simulate({'A': bars}, cfg)
        self.assertGreater(costed['metrics']['modeled_fees'], 0)
        self.assertGreater(costed['metrics']['modeled_slippage'], 0)
        self.assertAlmostEqual(costed['metrics']['final_equity']-cfg.capital,
                               sum(t['pnl'] for t in costed['trades']), places=2)

    def test_rank_uses_completed_return_and_weakest_first(self):
        a, z = rows([100]*130), rows([100]*130)
        a[126].update(close=50, open=50, low=49, high=51)
        z[126].update(close=90, open=90, low=89, high=91)
        a[127].update(close=500, high=501)
        cfg = self.cfg(a, candidate_rank='rs_126', max_positions=1)
        result = self.simulate({'A': a, 'Z': z}, cfg)
        self.assertEqual(result['trades'][0]['symbol'], 'A')
        self.assertEqual(result['trades'][0]['signal_date'], a[126]['date'])

    def test_split_rebases_short_liability_without_fictitious_profit(self):
        bars = rows([100]*130)
        for b in bars[128:]:
            b.update(open=50, high=51, low=49, close=50)
        bars = corporate_actions.attach(bars, [dict(id='split', kind='split', ex_date=bars[128]['date'],
                                                   share_factor=2, price_basis='raw', volume_basis='raw',
                                                   verified=True, source='fixture', basis_source='fixture')])
        result = self.simulate({'A': bars}, self.cfg(bars))
        t = result['trades'][0]
        self.assertEqual((t['quantity'], t['exit_quantity'], t['pnl']), (10, 20, 0))
        self.assertEqual(result['metrics']['final_equity'], 10000)

    def test_bearish_warmup_and_no_paper_state(self):
        bars = rows([100]*130)
        cfg = self.cfg(bars)
        self.assertEqual(backtest.required_warmup(cfg), 252)
        with self.assertRaisesRegex(ValueError, 'paper portfolios'):
            backtest.simulate({'A': bars}, cfg, state={})

    def test_real_signal_and_frozen_short_chart(self):
        bars = rows([200-i*.1 for i in range(281)]+[159,150,140])
        bars[281]['volume'] = 2000000
        for i,b in enumerate(bars):
            b['timestamp'] = 1704067200000+i*86400000
        cfg = self.cfg(bars)
        cfg.start, cfg.end = date.fromisoformat(bars[282]['date']), date.fromisoformat(bars[283]['date'])
        result = backtest.simulate({'A':bars},cfg)
        self.assertEqual(len(result['trades']),1)
        t = result['trades'][0]
        result['config'] = cfg.model_dump(mode='json')
        chart = explain_trade(result,{'A':bars},t,bars,282,283)
        self.assertTrue(all(c['passed'] for c in chart['checks']))
        self.assertGreater(chart['bars'][282]['chart_values']['initial_stop'],t['entry'])
        self.assertLess(chart['bars'][282]['chart_values']['target'],t['entry'])
        self.assertEqual(chart['bars'][282]['chart_values']['protective_stop'],t['stop_trace'][0]['stop'])
        self.assertEqual(chart['signal']['date'],bars[281]['date'])

    def test_weak_market_gate_is_not_the_bullish_gate(self):
        bars = rows([100+i for i in range(130)])
        cfg = self.cfg(bars)
        cfg.require_weak_market = True
        result = self.simulate({'A':bars},cfg)
        self.assertEqual(result['trades'],[])  # No 200-session breadth coverage.
        cfg.require_weak_market = False
        self.assertGreater(len(self.simulate({'A':bars},cfg)['trades']),0)

    def test_frozen_comparison_preserves_inputs_and_still_audits_gaps(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(store,'DATA',Path(folder)):
            bars = rows([100]*130)
            reference_id = '123456abcdef'
            cfg = self.cfg(bars, comparison_run_id=reference_id, low_lookback_days=50)
            reference = dict(config=dict(start=str(cfg.start),end=str(cfg.end),name='Baseline'),
                             universe='nifty50',universe_snapshot=dict(instruments=[]),
                             manifest=[dict(symbol='A')],excluded=['OLD'])
            store.write('runs/'+reference_id,reference)
            store.write('run_data/'+reference_id,{'A':bars})
            # Today's provider cache must not substitute for the comparison snapshot.
            store.write('bars/A',dict(bars=rows([1]*130)))
            _, inputs, _, excluded = backtest.prepare(Settings(universe='nifty50'),cfg)
            self.assertEqual(inputs,{'A':bars})
            self.assertEqual(excluded,['OLD'])
            bars[10]['open'] = 50
            store.write('run_data/'+reference_id,{'A':bars})
            with self.assertRaisesRegex(ValueError,'Price discontinuity'):
                backtest.run(Settings(universe='nifty50'),cfg,lambda _:None,'new-reference')
            self.assertIsNone(store.read('runs/new-reference'))


if __name__ == '__main__':
    unittest.main()

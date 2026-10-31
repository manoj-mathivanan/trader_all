import copy
import unittest
from datetime import date
from types import SimpleNamespace

from pydantic import ValidationError

from core.research import four_indicator_swing as fs
from core.strategies.four_indicator_allocation import AllocationContext
from tests.test_four_indicator_swing import rows


class AllocationTests(unittest.TestCase):
    def setUp(self):
        self.bars = rows()
        self.config = fs.SwingConfig(start=self.bars[100]['date'], end=self.bars[-1]['date'],
                                     capital=100000, max_positions=2, slippage_bps=0)
        self.signals = [dict(exit=False, close=b['close'], checks=[dict(passed=i == 100, value=1) for _ in range(4)])
                        for i, b in enumerate(self.bars)]
        self.data = {'A': copy.deepcopy(self.bars), 'B': copy.deepcopy(self.bars)}
        self.items = [dict(symbol=s, sector='IT') for s in self.data]

    def simulate(self, config=None, data=None, **kwargs):
        return fs.simulate(data or self.data, {s: self.signals for s in self.data}, config or self.config,
                           fs.RULES[3], instruments=self.items, **kwargs)

    def test_default_cash_and_fills_match_legacy_config(self):
        legacy = SimpleNamespace(**{k: getattr(self.config, k) for k in ('start','end','capital','max_positions','slippage_bps')})
        self.assertEqual(self.simulate(), self.simulate(legacy))
        first = self.simulate()['trades'][0]
        self.assertLessEqual(first['entry_cost'], self.config.capital/2)

    def test_volume_priority_uses_signal_and_excludes_its_volume_from_average(self):
        for b in self.data['B']: b['volume'] = 10000
        self.data['A'][100]['volume'] = 5000
        cfg = self.config.model_copy(update=dict(max_positions=1, candidate_ranking='relative_volume'))
        result = self.simulate(cfg)
        self.assertEqual(result['trades'][0]['symbol'], 'A')
        self.assertEqual(result['trades'][0]['allocation']['relative_volume'], 5)
        self.assertEqual(self.simulate(cfg.model_copy(update={'candidate_ranking':'turnover'}))['trades'][0]['symbol'], 'B')
        changed = copy.deepcopy(self.data)
        changed['B'][101]['volume'] = 10**10
        changed['B'][-1]['close'] *= 10
        entry = self.simulate(cfg, changed)['trades'][0]
        self.assertEqual((entry['symbol'], entry['quantity'], entry['allocation']),
                         (result['trades'][0]['symbol'], result['trades'][0]['quantity'], result['trades'][0]['allocation']))

    def test_atr_reduces_volatile_stock_and_stock_cap_includes_fees(self):
        for b in self.data['B']:
            b['high'] += 30
            b['low'] -= 30
        result = self.simulate(self.config.model_copy(update=dict(target_atr_pct=2, max_position_pct=40)))
        trades = {t['symbol']: t for t in result['trades']}
        self.assertLess(trades['B']['quantity'], trades['A']['quantity'])
        for t in trades.values():
            self.assertLessEqual(t['entry_cost'], 40000)
            self.assertGreaterEqual(t['allocation']['volatility_multiplier'], .5)
            self.assertLessEqual(t['allocation']['volatility_multiplier'], 1.25)

    def test_sector_cap_combines_existing_positions_and_unknown_bucket(self):
        result = self.simulate(self.config.model_copy(update=dict(max_sector_pct=30)), liquidate=False)
        ledger = result['ledger']
        self.assertLessEqual(sum(p['entry']*p['quantity'] for p in ledger['positions'].values()), 30000)
        self.assertTrue(any(p['allocation']['sector_exposure_before'] > 0 for p in ledger['positions'].values()))
        self.items = []
        unknown = self.simulate(self.config.model_copy(update=dict(max_sector_pct=30)), liquidate=False)
        self.assertLessEqual(sum(p['entry']*p['quantity'] for p in unknown['ledger']['positions'].values()), 30000)
        self.assertEqual(next(iter(unknown['ledger']['positions'].values()))['allocation']['sector'], 'Unknown')

    def test_weak_and_missing_breadth_scale_conservatively(self):
        cfg = self.config.model_copy(update=dict(market_weak_scale=.5, sector_weak_scale=.5))
        self.items = []
        context = AllocationContext(self.data, cfg, self.items)
        value = context.allocation('A',100,self.bars[100]['date'],100000,2)
        self.assertEqual(value['market']['status'], 'strong')
        self.assertEqual(value['sector_breadth']['status'], 'unknown')
        self.assertEqual(value['multiplier'], .5)
        # One missing date must reduce coverage; stale peer prices do not count.
        missing = {s: [b for b in bars if s == 'A' or b['date'] != self.bars[100]['date']] for s,bars in self.data.items()}
        context = AllocationContext(missing,cfg,self.items)
        self.assertEqual(context.breadth(self.bars[100]['date'])['status'], 'unknown')
        value = context.allocation('A',100,self.bars[100]['date'],100000,2)
        self.assertEqual(value['multiplier'], .25)

    def test_incremental_paper_matches_one_replay_with_all_controls(self):
        cfg = self.config.model_copy(update=dict(candidate_ranking='relative_volume',target_atr_pct=2,
                                                market_weak_scale=.5,sector_weak_scale=.5,max_sector_pct=30))
        self.signals[103]['exit'] = True
        self.signals[105]['checks'] = [dict(passed=True,value=1) for _ in range(4)]
        full = self.simulate(cfg,liquidate=False)
        first = self.simulate(cfg.model_copy(update={'end':date.fromisoformat(self.bars[104]['date'])}),liquidate=False)
        second = self.simulate(cfg.model_copy(update={'start':date.fromisoformat(self.bars[105]['date'])}),
                               state=first['ledger'],liquidate=False,entry_start=cfg.start)
        self.assertEqual(second, full)

    def test_breadth_and_atr_ignore_future_candles_and_weak_trends_reduce_size(self):
        cfg = self.config.model_copy(update=dict(target_atr_pct=2,market_weak_scale=.5,sector_weak_scale=.5,sector_min_peers=2))
        data = {s:[dict(b,open=300-i,close=300-i,high=302-i,low=299-i) for i,b in enumerate(bars)]
                for s,bars in self.data.items()}
        full = AllocationContext(data,cfg,self.items)
        truncated = AllocationContext({s:bars[:101] for s,bars in data.items()},cfg,self.items)
        value = full.allocation('A',100,self.bars[100]['date'],100000,2)
        self.assertEqual(value,truncated.allocation('A',100,self.bars[100]['date'],100000,2))
        self.assertEqual(value['market']['status'],'weak')
        self.assertEqual(value['sector_breadth']['status'],'weak')
        self.assertEqual(value['market_multiplier']*value['sector_multiplier'],.25)

    def test_invalid_controls_rejected(self):
        for update in (dict(target_atr_pct=-1),dict(market_weak_scale=0),dict(max_sector_pct=101),dict(candidate_ranking='probability')):
            with self.assertRaises(ValidationError):
                fs.SwingConfig(**{**self.config.model_dump(), **update})


if __name__ == '__main__':
    unittest.main()

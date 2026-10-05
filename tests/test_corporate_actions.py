import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
from core.research import corporate_actions as ca, backtest, data_quality
from core.research.config import BacktestConfig


def bar(day, price):
    return {'date': day, 'open': price, 'high': price + 1, 'low': price - 1, 'close': price, 'volume': 1000}


def action(**changes):
    return {'id': 'test-split', 'kind': 'split', 'ex_date': '2025-01-03', 'share_factor': 2,
            'price_basis': 'raw', 'volume_basis': 'raw', 'verified': True,
            'source': 'unit-test issuer evidence', 'basis_source': 'unit-test exchange comparison', **changes}


class CorporateActionTests(unittest.TestCase):
    def test_split_adjusts_ohlcv_without_mutation_or_future_action_leakage(self):
        raw = [bar('2025-01-01', 100), bar('2025-01-02', 100), bar('2025-01-03', 50)]
        rows = ca.attach(raw, [action()]); before = deepcopy(rows)
        self.assertIs(ca.adjusted_bars(rows, '2025-01-02'), rows)
        adjusted = ca.adjusted_bars(rows, '2025-01-03')
        self.assertEqual(adjusted[0]['close'], 50)
        self.assertEqual(adjusted[0]['volume'], 2000)
        self.assertEqual(adjusted[-1]['volume'], 1000)
        self.assertEqual(rows, before)
        self.assertEqual(data_quality.audit({'TEST': rows})['findings'], [])

    def test_already_adjusted_series_is_not_adjusted_twice(self):
        rows = ca.attach([bar('2025-01-01', 50)], [action(price_basis='already_adjusted', volume_basis='already_adjusted')])
        self.assertIs(ca.adjusted_bars(rows, '2026-01-01'), rows)

    def test_unverified_mixed_basis_duplicate_and_fractional_contracts_fail(self):
        for records in ([action(verified=False)], [action(price_basis='unknown')],
                        [action(volume_basis='already_adjusted')], [action(), action()]):
            with self.assertRaises(ValueError):
                ca.attach([bar('2025-01-01', 100)], records)
        position = dict(quantity=3, entry=100, stop=92, best_close=110, entry_cost=300, initial_risk=24)
        with self.assertRaisesRegex(ValueError, 'fractional'):
            ca.rebase_position(position, 100, action(share_factor=1.5))

    def test_raw_split_position_preserves_equity_costs_risk_and_restart(self):
        rows = ca.attach([bar('2025-01-01', 100), bar('2025-01-02', 100),
                          bar('2025-01-03', 50), bar('2025-01-04', 51)], [action()])
        cfg = SimpleNamespace(**BacktestConfig(start='2025-01-02', end='2025-01-05', capital=100000,
                               acknowledge_limitations=True, slippage_bps=0,buy_cost_bps=0,sell_cost_bps=0).model_dump())
        with patch.object(backtest, 'signal', side_effect=lambda bars, i, cfg: i == 0):
            full = backtest.simulate({'TEST': rows}, cfg, liquidate=False)
            cfg.end = '2025-01-02'
            first = backtest.simulate({'TEST': rows}, cfg, liquidate=False)
            original = deepcopy(first)
            cfg.end = '2025-01-05'
            resumed = backtest.simulate({'TEST': rows}, cfg, state=first['state'], liquidate=False)
        self.assertEqual(full, resumed)
        self.assertEqual(first, original)
        p = resumed['state']['positions']['TEST']; old = first['state']['positions']['TEST']
        self.assertEqual(p['quantity'], 2 * old['quantity'])
        self.assertEqual(p['entry_cost'], old['entry_cost'])
        self.assertEqual(p['initial_risk'], old['initial_risk'])
        self.assertEqual(resumed['curve'][1]['equity'], first['curve'][0]['equity'])
        self.assertEqual(len(resumed['corporate_actions']), 1)
        self.assertEqual(resumed['trades'], [])

    def test_raw_split_gap_stop_uses_rebased_stop_and_original_buy_fill(self):
        rows = ca.attach([bar('2025-01-01', 100), bar('2025-01-02', 100), bar('2025-01-03', 40)], [action()])
        cfg = BacktestConfig(start='2025-01-02', end='2025-01-04', capital=100000,acknowledge_limitations=True,
                             slippage_bps=0,buy_cost_bps=0,sell_cost_bps=0)
        with patch.object(backtest, 'signal', side_effect=lambda bars, i, cfg: i == 0):
            r=backtest.simulate({'TEST': rows},cfg)
        trade=r['trades'][0]
        self.assertEqual(trade['entry'],100)
        self.assertEqual(trade['exit_quantity'],trade['quantity']*2)
        self.assertAlmostEqual(trade['pnl'],trade['quantity']*(-20))


if __name__ == '__main__':
    unittest.main()

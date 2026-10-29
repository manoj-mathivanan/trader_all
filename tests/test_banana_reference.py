import unittest
from datetime import date, timedelta
from unittest.mock import patch
from pydantic import ValidationError
from core.research import backtest, banana_reference, strategy_presets
from core.research.config import BacktestConfig


class ReferenceTests(unittest.TestCase):
    def rows(self, tail):
        rows = [dict(date=str(date(2019, 1, 1)+timedelta(days=i)), open=100,
                     high=101, low=99, close=100, volume=1000000) for i in range(253)]
        for b in tail:
            rows.append(dict(date=str(date(2019, 1, 1)+timedelta(days=len(rows))), volume=1000000, **b))
        return rows

    def cfg(self, rows, **values):
        p = next(p for p in strategy_presets.available() if p['name']=='Banana reference - VCP')
        return BacktestConfig(**{**p['backtest_defaults'], **values}, start=rows[253]['date'],
                              end=rows[-1]['date'], acknowledge_limitations=True)

    def signal(self, rows, i, cfg, *args):
        return i == 252, 100

    def test_close_exit_next_open_and_no_automatic_breakeven(self):
        rows = self.rows([dict(open=99,high=111,low=98,close=110),
                          dict(open=110,high=111,low=97,close=99),
                          dict(open=96,high=99,low=95,close=98)])
        rows[0]['listing_metadata'] = dict(listing_date=rows[0]['date'],verified=True,source='test',ipo_verified=True)
        with patch.object(banana_reference,'setup_proxy',side_effect=self.signal):
            r = backtest.simulate({'A':rows},self.cfg(rows,pattern='ipo',buy_cost_bps=0,sell_cost_bps=0))
        self.assertEqual(r['trades'][0]['exit'],96)
        self.assertEqual(r['trades'][0]['reason'],'Close below SMA50; next open')

    def test_end_marks_holdings_and_future_bars_do_not_change_result(self):
        rows = self.rows([dict(open=99,high=110,low=98,close=109),
                          dict(open=109,high=111,low=108,close=110)])
        future = rows+[dict(rows[-1],date='2026-01-01',open=9999,high=10000,low=9998,close=9999)]
        with patch.object(banana_reference,'setup_proxy',side_effect=self.signal):
            a = banana_reference._simulate({'A':rows},self.cfg(rows),setup='screen_proxy',entry='pivot',cost_bps=0)
            b = banana_reference._simulate({'A':future},self.cfg(rows),setup='screen_proxy',entry='pivot',cost_bps=0)
        self.assertEqual(a,b)
        self.assertFalse(a['trades'])
        self.assertAlmostEqual(1000000+a['open_pnl'],a['metrics']['final_equity'])

    def test_locked_circuit_defers_stop(self):
        rows = self.rows([dict(open=99,high=110,low=98,close=109),
                          dict(open=90,high=90,low=90,close=90),
                          dict(open=85,high=88,low=83,close=86)])
        with patch.object(banana_reference,'setup_proxy',side_effect=self.signal):
            r = banana_reference._simulate({'A':rows},self.cfg(rows),setup='screen_proxy',entry='pivot',cost_bps=0)
        self.assertEqual(r['trades'][0]['exit'],85)

    def test_entry_day_ordering_is_explicit(self):
        rows = self.rows([dict(open=99,high=111,low=90,close=110),
                          dict(open=110,high=112,low=109,close=111)])
        with patch.object(banana_reference,'setup_proxy',side_effect=self.signal):
            conservative=banana_reference._simulate({'A':rows},self.cfg(rows),setup='screen_proxy',entry='pivot',cost_bps=0)
            reference=banana_reference._simulate({'A':rows},self.cfg(rows),setup='screen_proxy',entry='pivot',cost_bps=0,same_day='reference')
        self.assertEqual(conservative['trades'][0]['exit'],92)
        self.assertFalse(reference['trades'])

    def test_sales_cannot_fund_same_day_entries(self):
        rows=self.rows([dict(open=99,high=102,low=98,close=101),
                        dict(open=90,high=102,low=89,close=101),
                        dict(open=100,high=102,low=99,close=101)])
        other=[dict(b) for b in rows]
        other[253].update(open=100,high=100,low=99,close=100)
        def signals(bs,i,c,*args):
            return (bs is rows and i==252) or (bs is other and i==253),100
        with patch.object(banana_reference,'setup_proxy',side_effect=signals):
            r=banana_reference._simulate({'A':rows,'B':other},self.cfg(rows,risk_pct=5,max_positions=2),
                                         setup='screen_proxy',entry='pivot',cap_pct=100,cost_bps=0)
        first=next(o for o in r['state']['orders'] if o['symbol']=='A' and o['side']=='buy')
        second=next(o for o in r['state']['orders'] if o['symbol']=='B' and o['side']=='buy')
        self.assertLessEqual(second['quantity']*second['price']+second['fees'],self.cfg(rows).capital-first['quantity']*first['price']-first['fees'])

    def test_position_and_turnover_caps_limit_quantity(self):
        rows=self.rows([dict(open=99,high=110,low=98,close=109),
                        dict(open=109,high=111,low=108,close=110)])
        with patch.object(banana_reference,'setup_proxy',side_effect=self.signal):
            position=banana_reference._simulate({'A':rows},self.cfg(rows,risk_pct=5),
                setup='screen_proxy',entry='pivot',cost_bps=0,cap_pct=30)
            turnover=banana_reference._simulate({'A':rows},self.cfg(rows,risk_pct=5),
                setup='screen_proxy',entry='pivot',cost_bps=0,cap_pct=100,turnover_pct=.1)
        self.assertEqual(position['open_positions']['A']['quantity'],3000)
        self.assertEqual(turnover['open_positions']['A']['quantity'],1000)

    def test_all_presets_persist_model_and_source_rules(self):
        presets=[p for p in strategy_presets.available() if p.get('backtest_defaults')]
        self.assertEqual(len(presets),4)
        for p in presets:
            cfg=BacktestConfig(**p['backtest_defaults'],start='2020-01-01',end='2026-09-30',acknowledge_limitations=True)
            self.assertEqual(cfg.simulation_model,'banana_proxy_v1')
            self.assertIsNone(p['trading_defaults'])
            self.assertEqual(p['source_filters']['market_cap_min_cr'],300)

    def test_unsupported_exit_and_asymmetric_costs_rejected(self):
        rows=self.rows([dict(open=100,high=101,low=99,close=100)]*2)
        for values in [dict(winner_exit='take_15'),dict(candidate_rank='fundamental_score')]:
            with self.assertRaises(ValidationError):
                self.cfg(rows,**values)

    def test_ipo_missing_evidence_is_unavailable_not_zero_return(self):
        rows=self.rows([dict(open=100,high=101,low=99,close=100)]*2)
        with self.assertRaisesRegex(ValueError,'no verified IPO'):
            backtest.simulate({'A':rows},self.cfg(rows,pattern='ipo'))


if __name__=='__main__':
    unittest.main()

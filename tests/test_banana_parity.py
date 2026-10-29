"""Execution tests for the isolated reference-method research harness."""
import unittest
from datetime import date, timedelta
from unittest.mock import patch
from core.research.config import BacktestConfig
from scripts.research_banana_parity import simulate


class BananaParityTests(unittest.TestCase):
    def rows(self, tail):
        start=date(2025,1,1)
        rows=[dict(date=str(start+timedelta(days=i)),open=100,high=101,low=99,close=100,volume=1000000) for i in range(201)]
        for values in tail:
            rows.append(dict(date=str(start+timedelta(days=len(rows))),volume=1000000,**values))
        return rows

    def cfg(self, rows, **changes):
        return BacktestConfig(start=rows[201]['date'],end=rows[-1]['date'],pattern='vcp',
            minimum_warmup_sessions=50,capital=10000,fee_model='custom_bps',acknowledge_limitations=True,
            **changes)

    def test_close_below_average_exits_next_open(self):
        rows=self.rows([dict(open=100,high=112,low=99,close=110),
                        dict(open=110,high=111,low=98,close=99),
                        dict(open=97,high=99,low=95,close=98)])
        with patch('scripts.research_banana_parity.matches',side_effect=lambda bs,i,c:i==200):
            result=simulate({'A':rows},self.cfg(rows),cost_bps=0)
        self.assertEqual(result['trades'][0]['exit_date'],rows[-1]['date'])
        self.assertEqual(result['trades'][0]['exit'],97)
        self.assertEqual(result['trades'][0]['reason'],'Close below SMA50; next open')

    def test_reference_does_not_move_stop_to_breakeven(self):
        rows=self.rows([dict(open=100,high=112,low=99,close=110),
                        dict(open=110,high=111,low=97,close=105),
                        dict(open=105,high=108,low=104,close=107)])
        with patch('scripts.research_banana_parity.matches',side_effect=lambda bs,i,c:i==200):
            reference=simulate({'A':rows},self.cfg(rows),cost_bps=0)
            local=simulate({'A':rows},self.cfg(rows),exits='local',cost_bps=0)
        self.assertEqual(reference['trades'][0]['exit'],107)
        self.assertEqual(local['trades'][0]['exit_date'],rows[202]['date'])

    def test_sale_proceeds_cannot_fund_same_day_entry(self):
        rows=self.rows([dict(open=100,high=102,low=99,close=101),
                        dict(open=90,high=102,low=89,close=101),
                        dict(open=100,high=102,low=99,close=101)])
        def signal(bs,i,c):
            return (bs is rows and i==200) or (bs is other and i==201)
        other=[dict(b) for b in rows]
        with patch('scripts.research_banana_parity.matches',side_effect=signal):
            result=simulate({'A':rows,'B':other},self.cfg(rows,risk_pct=5,max_positions=2),cost_bps=0,cap_pct=100)
        # A uses 62.5% of cash; after its gap exit only the prior remaining
        # cash can buy B. Same-day A proceeds stay unsettled.
        btrade=next(t for t in result['trades'] if t['symbol']=='B')
        atrade=next(t for t in result['trades'] if t['symbol']=='A')
        from core.execution.upstox import equity_charges
        def entry_cost(t):return t['quantity']*t['entry']+equity_charges(t['entry'],t['quantity'],'buy',t['entry_date'])['total']
        self.assertLessEqual(entry_cost(btrade),10000-entry_cost(atrade))

    def test_locked_day_defers_stop_to_next_tradable_open(self):
        rows=self.rows([dict(open=100,high=102,low=99,close=101),
                        dict(open=90,high=90,low=90,close=90),
                        dict(open=85,high=88,low=83,close=86)])
        with patch('scripts.research_banana_parity.matches',side_effect=lambda bs,i,c:i==200):
            result=simulate({'A':rows},self.cfg(rows),cost_bps=0)
        self.assertEqual(result['trades'][0]['exit'],85)
        self.assertEqual(result['trades'][0]['exit_date'],rows[-1]['date'])

    def test_locked_final_day_is_marked_without_fabricated_sale(self):
        rows=self.rows([dict(open=100,high=102,low=99,close=101),
                        dict(open=90,high=90,low=90,close=90)])
        with patch('scripts.research_banana_parity.matches',side_effect=lambda bs,i,c:i==200):
            result=simulate({'A':rows},self.cfg(rows),cost_bps=0)
        self.assertFalse(result['trades'])
        self.assertIn('A',result['open_positions'])
        self.assertAlmostEqual(10000+result['open_pnl'],result['metrics']['final_equity'])

    def test_intraday_pivot_ordering_is_an_explicit_sensitivity(self):
        rows=self.rows([dict(open=100,high=112,low=90,close=110),
                        dict(open=110,high=112,low=109,close=111)])
        with patch('scripts.research_banana_parity.vcp_setup',side_effect=lambda bs,i,c:i==200):
            conservative=simulate({'A':rows},self.cfg(rows),setup='setup_high',entry='pivot',cost_bps=0)
            reference=simulate({'A':rows},self.cfg(rows),setup='setup_high',entry='pivot',cost_bps=0,same_day='reference')
        self.assertEqual(conservative['trades'][0]['exit_date'],rows[201]['date'])
        self.assertEqual(conservative['trades'][0]['reason'],'Stop / intraday trail')
        self.assertEqual(reference['trades'][0]['exit_date'],rows[202]['date'])

    def test_gap_above_pivot_is_not_exempt_from_entry_day_stop(self):
        rows=self.rows([dict(open=102,high=112,low=90,close=110),
                        dict(open=110,high=112,low=109,close=111)])
        with patch('scripts.research_banana_parity.vcp_setup',side_effect=lambda bs,i,c:i==200):
            result=simulate({'A':rows},self.cfg(rows),setup='setup_high',entry='pivot',cost_bps=0,same_day='reference')
        self.assertEqual(result['trades'][0]['exit_date'],rows[201]['date'])

    def test_future_candles_do_not_change_past_fills(self):
        rows=self.rows([dict(open=100,high=112,low=99,close=110),
                        dict(open=110,high=111,low=98,close=99),
                        dict(open=97,high=99,low=95,close=98)])
        future=rows+[dict(rows[-1],date='2026-01-01',open=10000,high=10001,low=9999,close=10000)]
        with patch('scripts.research_banana_parity.matches',side_effect=lambda bs,i,c:i==200):
            original=simulate({'A':rows},self.cfg(rows),cost_bps=0)
            extended=simulate({'A':future},self.cfg(rows),cost_bps=0)
        self.assertEqual(original,extended)


if __name__=='__main__':
    unittest.main()

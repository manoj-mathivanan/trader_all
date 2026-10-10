"""Fee accounting, causal exits and durable swing-control fixtures."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pydantic import ValidationError
from core.research.config import BacktestConfig, BearishBacktestConfig
from core.research.backtest import simulate
from core.execution.zerodha import equity_charges, breakeven_price
from core.risk.position_sizer import percent_risk_size
from core.portfolio.paper import PaperConfig


def cfg(**changes):
    return BacktestConfig(**{'start':'2025-01-01', 'end':'2025-02-01',
        'capital':100000, 'pattern':'blue_sky', 'entry_mode':'next_open',
        'acknowledge_limitations':True, 'fee_model':'zerodha_equity',
        'slippage_bps':0, **changes})


def bar(day, opening=100, close=101, low=99):
    return dict(date=day, open=opening, high=max(opening, close)+1,
                low=low, close=close, volume=1000000)


class ChargesTests(unittest.TestCase):
    def test_delivery_tariff_and_rebalance_do_not_double_count_ipft(self):
        for day in ['2025-01-01', '2026-03-02']:
            buy = equity_charges(1000,100,'buy',day)
            sell = equity_charges(1000,100,'sell',day)
            self.assertEqual(buy['brokerage'],0)
            self.assertAlmostEqual(buy['exchange']+buy['ipft'],3.07)
            self.assertAlmostEqual(buy['stt'],100)
            self.assertAlmostEqual(buy['stamp'],15)
            self.assertAlmostEqual(buy['total'],118.7406)
            self.assertAlmostEqual(sell['total'],119.0806)
            self.assertEqual(sell['dp'],13)
        self.assertRaises(ValueError,equity_charges,100,10,'buy','2024-09-30')

    def test_intraday_cap_and_no_delivery_dp_or_buy_stt(self):
        buy=equity_charges(1000,100,'buy','2025-01-01',intraday=True)
        sell=equity_charges(1000,100,'sell','2025-01-01',intraday=True)
        self.assertEqual(buy['brokerage'],20)
        self.assertEqual(buy['stt'],0)
        self.assertEqual(sell['stt'],25)
        self.assertEqual(sell['dp'],0)
        self.assertAlmostEqual(buy['stamp'],3)

    def test_integer_size_covers_charges_and_stop_slippage(self):
        c=cfg(slippage_bps=10)
        qty=percent_risk_size(100000,19000,100,92,c,day='2025-01-01')
        def loss(q):
            return q*(100-91.908)+equity_charges(100,q,'buy','2025-01-01')['total']+equity_charges(91.908,q,'sell','2025-01-01')['total']
        self.assertLessEqual(loss(qty),1500)
        self.assertGreater(loss(qty+1),1500)
        self.assertLessEqual(qty*100+equity_charges(100,qty,'buy','2025-01-01')['total'],19000)
        be=breakeven_price(10000+equity_charges(100,100,'buy','2025-01-01')['total'],100,'2025-01-02',10)
        fill=be*.999
        self.assertAlmostEqual(fill*100-equity_charges(fill,100,'sell','2025-01-02')['total'],10000+equity_charges(100,100,'buy','2025-01-01')['total'],places=7)


class RefinementTests(unittest.TestCase):
    def run_rows(self,rows,config,signal=lambda rows,i,c:i==0,**kwargs):
        with patch('core.research.backtest.signal',side_effect=signal):
            return simulate({'TEST':rows},config,**kwargs)

    def test_same_day_stop_reclassifies_both_legs_and_cash_reconciles(self):
        r=self.run_rows([bar('2025-01-01'),bar('2025-01-02',low=80)],cfg())
        t=r['trades'][0]
        q=t['quantity']
        fees=equity_charges(t['entry'],q,'buy',t['entry_date'],intraday=True)['total']+equity_charges(t['exit'],q,'sell',t['exit_date'],intraday=True)['total']
        self.assertAlmostEqual(t['fees'],fees)
        self.assertEqual(t['charges']['dp'],0)
        self.assertAlmostEqual(t['gross_pnl']-t['fees'],t['pnl'])
        self.assertAlmostEqual(r['state']['cash'],100000+t['pnl'])
        self.assertAlmostEqual(sum(o['fees'] for o in r['state']['orders']),r['metrics']['modeled_fees'])

    def test_open_gap_uses_previous_close_not_future_prices(self):
        r=self.run_rows([bar('2025-01-01',close=100),bar('2025-01-02',opening=104,close=200)],cfg(max_open_gap_pct=3))
        self.assertFalse(r['trades'])
        self.assertEqual(r['entry_filter_rejections'],{'Opening gap too large':1})

    def test_stalled_exit_at_next_open_and_restart_equals_full(self):
        rows=[bar('2025-01-01'),bar('2025-01-02'),bar('2025-01-03'),bar('2025-01-04',opening=98,close=99,low=97)]
        c=cfg(stalled_exit_sessions=2)
        full=self.run_rows(rows,c)
        t=full['trades'][0]
        self.assertEqual(t['exit_date'],'2025-01-04')
        self.assertEqual(t['reason'],'Stalled trade (next open)')
        self.assertEqual(t['exit'],98)
        first=self.run_rows(rows,c.model_copy(update={'end':'2025-01-03'}),liquidate=False)
        resumed=self.run_rows(rows,c,state=first['state'])
        self.assertEqual(resumed,full)

    def test_breakout_failure_is_not_retroactive(self):
        rows=[bar('2025-01-01',opening=99,close=99),bar('2025-01-02',opening=101,close=102),bar('2025-01-03',opening=103,close=99),bar('2025-01-04',opening=97,close=98,low=96)]
        r=self.run_rows(rows,cfg(failed_breakout_sessions=2),signal=lambda rows,i,c:i==1)
        self.assertEqual(r['trades'][0]['reason'],'Early breakout failure (next open)')
        self.assertEqual(r['trades'][0]['exit_date'],'2025-01-04')

    def test_cost_adjusted_breakeven_activates_next_session(self):
        rows=[bar('2025-01-01'),bar('2025-01-02',close=110,low=99),bar('2025-01-03',opening=109,close=109,low=99)]
        r=self.run_rows(rows,cfg(winner_exit='trail_pct',trail_pct=20))
        t=r['trades'][0]
        self.assertEqual(t['exit_date'],'2025-01-03')
        self.assertAlmostEqual(t['pnl'],0,places=7)
        self.assertEqual(r['metrics']['win_rate'],0)
        self.assertEqual(t['stop_trace'][0]['stop'],92)
        self.assertGreater(t['stop_trace'][1]['stop'],100)

    def test_cooldown_survives_restart_and_counts_stock_sessions(self):
        rows=[bar('2025-01-01'),bar('2025-01-02',low=80),bar('2025-01-03'),bar('2025-01-06'),bar('2025-01-07')]
        c=cfg(reentry_cooldown_sessions=2)
        r=self.run_rows(rows,c,signal=lambda *args:True)
        self.assertEqual([t['entry_date'] for t in r['trades']],['2025-01-02','2025-01-07'])
        self.assertEqual(r['entry_filter_rejections'],{'Reentry cooldown':2})
        first=self.run_rows(rows,c.model_copy(update={'end':'2025-01-03'}),signal=lambda *args:True,liquidate=False)
        second=self.run_rows(rows,c,state=first['state'],signal=lambda *args:True)
        self.assertEqual(second,r)

    def test_market_scaling_supports_paper_namespace(self):
        c=SimpleNamespace(**cfg(skip_weak_markets=False,market_risk_scale=.5).model_dump())
        r=self.run_rows([bar('2025-01-01'),bar('2025-01-02')],c)
        expected=percent_risk_size(100000,100000,100,92,SimpleNamespace(**{**vars(c),'risk_pct':.75}),day='2025-01-02')
        self.assertEqual(r['trades'][0]['quantity'],expected)

    def test_unsupported_fee_modes_rejected_and_paper_accepts_tariff(self):
        for changes in [{'entry_mode':'pivot'},{'execution_horizon':'intraday'},{'start':'2024-01-01'}]:
            values={**cfg().model_dump(),**changes}
            self.assertRaises(ValidationError,BacktestConfig,**values)
        self.assertRaises(ValidationError,BearishBacktestConfig,start='2025-01-01',end='2025-02-01',acknowledge_limitations=True,fee_model='zerodha_equity',entry_mode='next_open')
        PaperConfig(capital=100000,acknowledge_limitations=True,fee_model='zerodha_equity',buy_cost_bps=0,sell_cost_bps=0)
        self.assertRaises(ValidationError,PaperConfig,capital=100000,acknowledge_limitations=True,buy_cost_bps=0)


if __name__=='__main__':
    unittest.main()

import math
import unittest
from types import SimpleNamespace
from core.execution.upstox import charges, equity_charges, size_order, breakeven_price
from core.execution.paper import PaperBrokerAdapter
from core.research.config import BacktestConfig
from core.research.options_backtest import ReplayConfig, transaction_fee
from core.research.intraday_costs import upstox_cash_fees

class UpstoxPlusTests(unittest.TestCase):
    def test_plus_caps_and_all_delivery_components(self):
        buy = equity_charges(1000, 100, 'buy', '2026-10-29')
        sell = equity_charges(1000, 100, 'sell', '2026-10-29')
        self.assertEqual(buy['brokerage'], 30)
        self.assertEqual(equity_charges(1, 1, 'buy', '2026-10-29')['brokerage'], .025)
        self.assertEqual(buy['stt'], 100)
        self.assertAlmostEqual(buy['stamp'], 15)
        self.assertEqual(sell['stamp'], 0)
        self.assertEqual(sell['dp'], 20)
        self.assertAlmostEqual(buy['exchange'], 3.07)
        self.assertAlmostEqual(buy['sebi'], .1)
        self.assertAlmostEqual(buy['gst'], .18*(30+3.07+.0001))
        self.assertAlmostEqual(sell['total']-equity_charges(1000,100,'sell','2026-10-29',dp=False)['total'], 23.6)

    def test_intraday_cap_and_date_boundaries(self):
        small = equity_charges(100, 10, 'buy', '2026-10-29', intraday=True)
        self.assertEqual(small['brokerage'], 1)
        self.assertEqual(small['stt'], 0)
        sell = equity_charges(1000,100,'sell','2026-10-29',intraday=True)
        self.assertEqual(sell['brokerage'],30)
        self.assertEqual(sell['dp'],0)
        self.assertEqual(sell['stt'],25)
        self.assertAlmostEqual(equity_charges(1000,100,'buy','2026-02-28')['exchange'],2.97)
        self.assertAlmostEqual(charges(100,100,'sell','2026-03-31',segment='options')['stt'],10)
        self.assertAlmostEqual(charges(100,100,'sell','2026-04-01',segment='options')['stt'],15)

    def test_saved_fee_selection_cannot_bypass_new_fills(self):
        for model in ('custom_bps','zerodha_equity','upstox_plus'):
            cfg=SimpleNamespace(slippage_bps=10,buy_cost_bps=0,sell_cost_bps=0,fee_model=model)
            fill=PaperBrokerAdapter(cfg).fill(100,100,'buy',day='2026-10-29')
            self.assertAlmostEqual(fill['fees'],equity_charges(100.1,100,'buy','2026-10-29')['total'])
            self.assertEqual(fill['fee_model'],'upstox_plus')
            self.assertGreater(fill['fees'],30)
            with self.assertRaises(ValueError):PaperBrokerAdapter(cfg).fill(100,10,'buy')
            saved=BacktestConfig(start='2020-01-01',end='2021-01-01',acknowledge_limitations=True,fee_model=model)
            self.assertEqual(saved.fee_model,'upstox_plus')

    def test_exact_sizing_is_maximal_and_breakeven_reconciles(self):
        for sign in (1,-1):
            qty=size_order(100000,10000,100,92 if sign==1 else 108,1,'2026-10-29',sign=sign,intraday=True)
            side='buy' if sign==1 else 'sell'
            def cost(q):return equity_charges(100,q,side,'2026-10-29',intraday=True)['total']
            self.assertLessEqual(qty*100+cost(qty),10000)
            self.assertGreater((qty+1)*100+cost(qty+1),10000)
            entry_cost=100*qty+sign*cost(qty)
            raw=breakeven_price(entry_cost,qty,'2026-10-29',10,intraday=True,sign=sign)
            fill=raw*(1-sign*.001)
            exit_fee=equity_charges(fill,qty,'sell' if sign==1 else 'buy','2026-10-29',intraday=True)['total']
            self.assertAlmostEqual(fill*qty-sign*exit_fee,entry_cost,places=7)

    def test_research_helpers_share_plus_and_options_ignore_old_zero_costs(self):
        self.assertEqual(upstox_cash_fees(1000,100,'sell','2026-10-29'),equity_charges(1000,100,'sell','2026-10-29',intraday=True)['total'])
        cfg=ReplayConfig(fee_model='custom_bps',brokerage_per_order=0)
        self.assertEqual(transaction_fee(250,65,'buy','2026-10-29',cfg),charges(250,65,'buy','2026-10-29',segment='options')['total'])
        for value in (0,-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):equity_charges(value,1,'buy','2026-10-29')

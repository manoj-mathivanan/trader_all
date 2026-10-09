import unittest
from core.research.intraday_costs import upstox_cash_fees
from tests import test_momentum


class FeeScheduleTests(unittest.TestCase):
    def test_buy_sell_levies_and_brokerage_cap(self):
        buy = upstox_cash_fees(1000,100,'buy','2026-03-01')
        sell = upstox_cash_fees(1000,100,'sell','2026-03-01')
        self.assertAlmostEqual(sell-buy,22)
        self.assertAlmostEqual(buy+sell,82.681436)
        # Twice the notional does not double the capped brokerage.
        self.assertLess(upstox_cash_fees(1000,200,'buy','2026-03-01'),2*buy)

    def test_dated_transition_and_stress(self):
        old = upstox_cash_fees(1000,100,'buy','2026-02-28')
        new = upstox_cash_fees(1000,100,'buy','2026-03-01')
        self.assertAlmostEqual(new-old,.000118)
        self.assertAlmostEqual(upstox_cash_fees(1000,100,'buy','2026-03-01',1.5),new*1.5)


class NonlinearSizingTests(unittest.TestCase):
    def test_exact_fees_constrain_risk_and_capital_for_both_sides(self):
        fixture = test_momentum.MomentumTests()
        fixture.setUp()
        def capped(price, qty, side, day):
            return min(20,price*qty*.001)+(price*qty*.00025 if side=='sell' else 0)
        for mode in ('follow','reverse'):
            cfg = fixture.cfg.model_copy(update={'execution_mode':mode,'slippage_bps':5})
            from core.research.momentum import simulate
            result = simulate(fixture.daily,cfg,fixture.minutes,fixture.plan,fee_model=capped)
            trade = result['trades'][0]
            sign = 1 if trade['direction']=='long' else -1
            side = 'buy' if sign==1 else 'sell'
            other = 'sell' if sign==1 else 'buy'
            qty, fill, stop = trade['quantity'],trade['entry'],trade['initial_stop']
            stop_fill = stop*(1-sign*.0005)
            def risk(q):
                return sign*(fill-stop_fill)*q+capped(fill,q,side,'')+capped(stop_fill,q,other,'')
            self.assertLessEqual(risk(qty),100)
            self.assertLessEqual(fill*qty+capped(fill,qty,side,''),5000)
            self.assertTrue(risk(qty+1)>100 or fill*(qty+1)+capped(fill,qty+1,side,'')>5000)
            fees = capped(fill,qty,side,'')+capped(trade['exit'],qty,other,'')
            self.assertAlmostEqual(trade['fees'],fees)
            self.assertAlmostEqual(result['metrics']['final_equity'],10000+trade['pnl'])

    def test_custom_fees_cannot_silently_use_percentage_breakeven(self):
        fixture = test_momentum.MomentumTests()
        fixture.setUp()
        fixture.cfg.breakeven_after_r = 1
        from core.research.momentum import simulate
        with self.assertRaisesRegex(ValueError,'breakeven'):
            simulate(fixture.daily,fixture.cfg,fixture.minutes,fixture.plan,fee_model=upstox_cash_fees)

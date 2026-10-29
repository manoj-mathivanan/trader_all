from dataclasses import replace
import unittest

from core.research.candle_rejection import Rules
from core.research.candle_continuation import limit_fill, orders, simulate
from scripts.research_candle_continuation import verify
from tests.test_candle_rejection import candles


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.bars=candles()
        for bar in self.bars:
            bar.update(open=101.2,high=101.3,low=101.1,close=101.2)
        self.bars[2].update(open=100,high=101.1,low=99.9,close=101)
        self.context=dict(symbol='A',atr=2,previous_low=98,previous_high=105)
        self.rules=replace(Rules(),max_trades_per_stock=1)

    def run_engine(self,variant,bars=None,sign=1,rules=None):
        result=simulate({'A':{'2025-01-02':bars or self.bars}},
                        {'2025-01-02':[self.context]},variant,sign,5,rules or self.rules)
        verify(result)
        return result

    def test_impulse_requires_close_and_pullback_waits_for_resumption(self):
        self.assertIn(3,orders(self.bars,self.context,'impulse_control',1))
        self.bars[3].update(open=101,high=101,low=100.7,close=100.8)
        self.bars[4].update(open=100.8,high=101.4,low=100.7,close=101.3)
        setup=orders(self.bars,self.context,'weak_pullback',1)
        self.assertNotIn(3,setup)
        self.assertNotIn(4,setup)
        self.assertIn(5,setup)
        self.assertEqual(setup[5]['signal_index'],4)
        self.bars[3]['low']=100.4
        self.assertNotIn(5,orders(self.bars,self.context,'weak_pullback',1))

    def test_two_weak_candles_allowed_but_third_expires(self):
        self.bars[3].update(open=101,high=101,low=100.8,close=100.9)
        self.bars[4].update(open=100.9,high=100.95,low=100.7,close=100.8)
        self.bars[5].update(open=100.8,high=101.4,low=100.7,close=101.3)
        self.assertEqual(orders(self.bars,self.context,'weak_pullback',1)[6]['pullback_bars'],2)
        self.bars[5].update(open=100.8,high=100.9,low=100.6,close=100.7)
        self.bars[6].update(open=100.7,high=101.4,low=100.6,close=101.3)
        self.assertNotIn(7,orders(self.bars,self.context,'weak_pullback',1))

    def test_gap_decision_uses_open_not_eventual_high_low_close(self):
        original=orders(self.bars,self.context,'gap_retest',1)[3]
        self.bars[3].update(high=500,low=1,close=400)
        changed=orders(self.bars,self.context,'gap_retest',1)[3]
        self.assertEqual(original,changed)
        self.assertEqual(original['limit'],101)
        self.assertEqual(original['active_index'],4)

    def test_limit_delay_penetration_expiry_and_open_crossing(self):
        order=orders(self.bars,self.context,'gap_retest',1)[3]
        bar=dict(self.bars[3],open=101.2,low=100.99)
        self.assertIsNone(limit_fill(order,bar,3,1,.0005,self.rules))
        self.assertIsNone(limit_fill(order,bar,4,1,.0005,self.rules))
        self.assertEqual(limit_fill(order,dict(bar,low=100.9),4,1,.0005,self.rules),(101,False))
        self.assertEqual(limit_fill(order,dict(bar,open=100.9),4,1,.0005,self.rules),(101,True))
        self.assertIsNone(limit_fill(order,dict(bar,low=100),7,1,.0005,self.rules))

    def test_intrabar_limit_fill_does_not_claim_earlier_target(self):
        self.bars[4].update(open=101.2,high=105,low=100.9,close=101.2)
        self.bars[6].update(high=105,close=104)
        result=self.run_engine('gap_retest')
        trade=result['trades'][0]
        self.assertEqual(trade['entry_index'],4)
        self.assertEqual(trade['exit_time'],'09:45')
        self.assertEqual(trade['reason'],'target')
        self.assertGreater(result['diagnostics']['entry_bar_targets_not_credited'],0)
        self.assertEqual(trade['entry'],trade['limit'])

    def test_fill_bar_stop_is_active_and_gaps_not_retroactively_cancelled(self):
        self.bars[4].update(open=101.2,high=105,low=99,close=101.2)
        result=self.run_engine('gap_retest')
        trade=result['trades'][0]
        self.assertEqual(trade['reason'],'stop')
        self.assertTrue(trade['ambiguous'])
        self.bars[4].update(open=98,high=99,low=97,close=98)
        result=self.run_engine('gap_retest')
        trade=result['trades'][0]
        self.assertEqual(trade['reason'],'gap_stop')
        self.assertEqual(trade['entry'],101)
        self.assertAlmostEqual(trade['exit'],98*(1-.0005))
        self.assertEqual(result['order_ledger'][0]['status'],'filled')

    def test_expired_order_has_no_trade(self):
        result=self.run_engine('gap_retest')
        self.assertEqual(result['trades'],[])
        self.assertTrue(result['order_ledger'])
        self.assertTrue(all(o['status']=='expired' for o in result['order_ledger']))

    def test_pending_orders_reserve_slot_and_cash(self):
        other=[dict(b) for b in self.bars]
        result=simulate({'A':{'2025-01-02':self.bars},'B':{'2025-01-02':other}},
                        {'2025-01-02':[self.context,dict(self.context,symbol='B')]},
                        'gap_retest',1,5,replace(self.rules,max_positions=1))
        verify(result)
        self.assertEqual(result['diagnostics']['limit_orders_submitted'],1)
        self.assertGreater(result['diagnostics']['position_or_trade_cap'],0)

    def test_short_rules_are_directional_mirror(self):
        self.bars[4].update(open=101.2,high=101.3,low=100.9,close=101.2)
        reflected=[dict(b,open=200-b['open'],close=200-b['close'],high=200-b['low'],low=200-b['high']) for b in self.bars]
        long=orders(self.bars,self.context,'gap_retest',1)[3]
        short=orders(reflected,self.context,'gap_retest',-1)[3]
        self.assertAlmostEqual(short['limit'],200-long['limit'])
        result=self.run_engine('gap_retest',reflected,-1)
        self.assertTrue(result['trades'])
        self.assertTrue(all(t['stop']>t['entry'] and t['target']<t['entry'] for t in result['trades']))

    def test_future_candles_do_not_change_existing_market_entry(self):
        first=self.run_engine('impulse_control')['trades'][0]
        self.bars[40].update(open=150,high=160,low=140,close=155)
        second=self.run_engine('impulse_control')['trades'][0]
        self.assertEqual(first['entry_timestamp'],second['entry_timestamp'])
        self.assertEqual(first['entry'],second['entry'])
        self.assertEqual(first['quantity'],second['quantity'])


if __name__=='__main__':
    unittest.main()

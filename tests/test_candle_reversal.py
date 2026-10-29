from copy import deepcopy
from dataclasses import replace
import unittest

from core.research import candle_rejection as original,candle_reversal as reversal
from scripts.research_candle_passive import verify_control
from scripts.research_candle_reversal import verify
from tests.test_candle_rejection import candles


class ReversalTests(unittest.TestCase):
    def setUp(self):
        self.bars=candles()
        self.bars[2].update(open=100.8,high=101.2,low=100.4,close=101)
        self.bars[3].update(open=101,high=102,low=99,close=100)
        self.context=dict(symbol='A',atr=.2,previous_low=100.4,previous_high=105)
        self.inputs=dict(sessions={'A':{'2025-01-02':self.bars}},plan={'2025-01-02':[self.context]})
        self.rules=replace(original.Rules(),max_trades_per_stock=1)
        self.source=original.simulate(self.inputs['sessions'],self.inputs['plan'],'level',1,5,self.rules)

    def test_follow_control_reproduces_original(self):
        control=reversal.simulate(self.inputs,self.source,'follow',5,self.rules)
        verify_control(self.source,control)

    def test_reverse_swaps_barriers_preserves_time_and_resizes(self):
        result=reversal.simulate(self.inputs,self.source,'reverse',5,self.rules)
        verify(result,self.source)
        old,new=self.source['trades'][0],result['trades'][0]
        self.assertEqual(new['entry_timestamp'],old['entry_timestamp'])
        self.assertEqual(new['stop'],old['target'])
        self.assertEqual(new['target'],old['stop'])
        self.assertEqual(new['direction'],'short')
        self.assertLess(new['quantity'],old['quantity'])
        self.assertGreater(new['fees'],0)
        self.assertLess(old['pnl'],0)
        self.assertGreater(new['pnl'],0)

    def test_original_outcomes_and_exits_do_not_choose_reverse_trades(self):
        modified=deepcopy(self.source)
        for trade in modified['trades']:
            trade['pnl']=10**12
            trade['exit_timestamp']=trade['entry_timestamp']+999999999
            trade['exit_time']='23:59'
            trade['exit']=9999999
            trade['quantity']=1
        self.assertEqual(reversal.entry_events(self.source),reversal.entry_events(modified))
        a=reversal.simulate(self.inputs,self.source,'reverse',5,self.rules)
        b=reversal.simulate(self.inputs,modified,'reverse',5,self.rules)
        self.assertEqual(a,b)

    def test_ambiguous_bar_is_stop_first_for_reversed_position(self):
        self.bars[3]['high']=105
        result=reversal.simulate(self.inputs,self.source,'reverse',5,self.rules)
        self.assertTrue(result['trades'][0]['ambiguous'])
        self.assertEqual(result['trades'][0]['reason'],'stop')
        self.assertLess(result['trades'][0]['pnl'],0)

    def test_no_costs_diagnostic_and_source_event_accounting(self):
        result=reversal.simulate(self.inputs,self.source,'reverse',0,self.rules,fee_multiplier=0)
        verify(result,self.source)
        self.assertEqual(result['metrics']['fees'],0)
        self.assertEqual(result['metrics']['slippage'],0)
        self.assertEqual(len(result['entry_decisions']),len(self.source['trades']))


if __name__=='__main__':
    unittest.main()

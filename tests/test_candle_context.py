import unittest

from core.research.candle_level_context import state,active_levels,trend,opportunities,context_gate
from core.research import candle_continuation
from tests.test_candle_rejection import candles


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.bars=candles()
        self.context=dict(symbol='A',atr=2,previous_low=95,previous_high=110)
        self.bars[2].update(open=100.8,high=101.2,low=100,close=101)

    def test_opening_level_cannot_validate_its_own_final_candle(self):
        self.assertIn(3,opportunities(self.bars,self.context,'geometry_control',1))
        self.assertNotIn(3,opportunities(self.bars,self.context,'known_level',1))
        self.bars[3].update(open=100.8,high=101.2,low=100,close=101)
        signals=opportunities(self.bars,self.context,'known_level',1)
        self.assertIn(4,signals)
        self.assertEqual(signals[4]['context_level_known_index'],3)

    def test_pivot_requires_both_right_bars_and_expires_after_break(self):
        highs=[10,11,15,12,10,18]
        lows=[8,9,10,9,8,16]
        for g,(high,low) in enumerate(zip(highs,lows)):
            for b in self.bars[g*3:g*3+3]:
                b.update(open=low+.5,high=high,low=low,close=low+1)
        snap=state(self.bars,self.context)
        self.assertFalse(any(l['name']=='pivot_high_2' for l in active_levels(snap,14,2)))
        self.assertTrue(any(l['name']=='pivot_high_2' for l in active_levels(snap,15,2)))
        self.assertTrue(any(l['name']=='pivot_high_2' for l in active_levels(snap,17,2)))
        self.assertFalse(any(l['name']=='pivot_high_2' for l in active_levels(snap,18,2)))

    def test_future_candles_cannot_change_available_levels(self):
        original=active_levels(state(self.bars,self.context),6,2)
        self.bars[20].update(open=200,high=300,low=1,close=250)
        self.assertEqual(active_levels(state(self.bars,self.context),6,2),original)

    def test_trend_uses_only_completed_groups(self):
        snap=dict(groups=[dict(high=101,low=99,known_index=3),dict(high=102,low=100,known_index=6)],levels=[])
        self.assertFalse(trend(snap,5,1))
        self.assertTrue(trend(snap,6,1))
        self.assertFalse(trend(snap,6,-1))

    def test_opposing_room_blocks_entry_without_moving_stop(self):
        self.bars[6].update(open=100.8,high=101.2,low=100,close=101)
        snap=dict(groups=[dict(high=101,low=99,close=100.1,known_index=3),
                          dict(high=102,low=100,close=101,known_index=6)],
                  levels=[dict(name='support',role='support',price=100,known_index=0),
                          dict(name='opposition',role='resistance',price=102,known_index=0)])
        setup=dict(signal_index=6,extreme=100,atr=2)
        self.assertIsNone(context_gate(self.bars,self.context,snap,setup,7,1,True))
        snap['levels']=snap['levels'][:1]
        selected=context_gate(self.bars,self.context,snap,setup,7,1,True)
        self.assertTrue(selected['context_trend'])
        self.assertIsNone(selected['opposing_room_r'])
        self.assertEqual(setup['extreme'],100)

    def test_weak_control_is_unchanged(self):
        self.bars[3].update(open=101,high=101,low=100.7,close=100.8)
        self.bars[2].update(open=100,high=101.1,low=99.9,close=101)
        self.bars[4].update(open=100.8,high=101.4,low=100.7,close=101.3)
        self.assertEqual(opportunities(self.bars,self.context,'weak_control',1),
                         candle_continuation.orders(self.bars,self.context,'weak_pullback',1))


if __name__=='__main__':
    unittest.main()

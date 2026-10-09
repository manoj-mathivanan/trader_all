import unittest
from copy import deepcopy
from core.research import momentum
from tests import test_momentum as fixtures


class PullbackTests(unittest.TestCase):
    def fixture(self):
        f=fixtures.MomentumTests();f.setUp()
        bars=f.minutes['A']['2025-02-03']
        for b in bars:
            b.update(open=104.5,high=105,low=104.3,close=104.8)
        for b,prices in zip(bars,[(100,104.2,99.9,104),(104,104,103.5,103.6),
                                  (103.6,103.7,103,103.2),(103.2,104.6,103.2,104.5)]):
            b.update(zip(('open','high','low','close'),prices))
        bars[5].update(open=104.5,high=105,low=102,close=104)
        f.cfg.entry_pattern='flag';f.cfg.stop_reference='pullback'
        return f,bars

    def test_causal_two_candle_pullback_and_direction_symmetry(self):
        f,bars=self.fixture()
        pattern=momentum.flag_quality(bars,3,5,1,4)
        self.assertEqual(pattern['pullback_extreme'],103)
        self.assertEqual(pattern['retracement_fraction'],.25)
        changed=deepcopy(bars);changed[4]['close']=1000
        self.assertEqual(pattern,momentum.flag_quality(changed,3,5,1,4))
        self.assertIsNone(momentum.flag_quality(bars,2,10,1,4))
        mirror=deepcopy(bars)
        for b in mirror:
            o,h,l,c=[b[k] for k in ('open','high','low','close')]
            b.update(open=200-o,high=200-l,low=200-h,close=200-c)
        short=momentum.flag_quality(mirror,3,5,-1,4)
        self.assertEqual(short['pullback_extreme'],97)
        self.assertEqual(short['retracement_fraction'],.25)
        bars[2]['low']=101
        self.assertIsNone(momentum.flag_quality(bars,3,5,1,4))

    def test_next_open_fill_and_actual_pullback_stop(self):
        f,bars=self.fixture()
        t=f.simulate()['trades'][0]
        self.assertEqual((t['entry_time'],t['entry'],t['initial_stop']),('09:35',104.5,103))
        self.assertEqual((t['exit_time'],t['exit'],t['reason']),('09:40',103,'Pullback stop loss'))
        self.assertEqual(t['signal_pattern']['pullback_candles'],2)
        bars[4].update(open=102,low=101,close=102)
        self.assertEqual(f.simulate()['trades'],[])  # Gap below the planned stop: no positive risk distance.

    def test_reverse_flag_mirrors_pullback_distance_and_preserves_signal(self):
        f, bars = self.fixture()
        baseline = f.simulate()['trades'][0]
        f.cfg.execution_mode = 'reverse'
        trade = f.simulate()['trades'][0]
        self.assertEqual(trade['entry_time'], baseline['entry_time'])
        self.assertEqual((trade['signal_direction'], trade['direction']), ('long', 'short'))
        self.assertEqual(trade['initial_stop'], 106)
        bars[4].update(high=107)
        self.assertEqual(f.simulate()['trades'][0]['exit'], 106)

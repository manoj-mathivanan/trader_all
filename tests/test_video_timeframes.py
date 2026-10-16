import unittest
from copy import deepcopy
from core.research.video_methods import fvg_setups,replay_limit
from core.research.video_timeframes import entry_setups
from tests.test_video_methods import bars


def fixture(minutes):
    wave=[0,.2,.4,.2,0,-.2,-.4,-.2]
    previous=[bars([100+(day*25+j//15)*.005+wave[(day*25+j//15)%8]
                    for j in range(375)]) for day in range(3)]
    for day,session in enumerate(previous):
        for b in session:
            b['date']=f'2026-06-{25+day}';b['timestamp']-=(3-day)*86400000
    prices=[102]*(375//minutes)
    prices[30:43]=[102,102.2,102.4,102.2,102,101.8,102,102.1,101.9,101.7,101.5,101.7,102.3]
    current=bars([p for p in prices for _ in range(minutes)])
    for j,b in enumerate(current):
        p=b['close']
        b.update(open=p-.01 if j%minutes==0 else p,high=p+.02,low=p-.02)
    return current,previous


class VideoTimeframesTest(unittest.TestCase):
    def test_generalised_one_minute_matches_original_control(self):
        current,previous=fixture(1)
        for direction in (1,-1):
            # Include an actual positive long fixture and its bearish mirror.
            source=current if direction==1 else [dict(b,open=204-b['open'],close=204-b['close'],high=204-b['low'],low=204-b['high']) for b in current]
            history=previous if direction==1 else [[dict(b,open=204-b['open'],close=204-b['close'],high=204-b['low'],low=204-b['high']) for b in s] for s in previous]
            original=fvg_setups(source,history,direction)
            general=entry_setups(source,history,direction)
            self.assertTrue(original)
            self.assertEqual(original,[{k:s[k] for k in original[0]} for s in general])

    def test_five_minute_formation_is_complete_before_fill(self):
        current,previous=fixture(5)
        setups=entry_setups(current,previous,entry_minutes=5)
        self.assertTrue(setups)
        setup=setups[0];j=setup['signal_index']
        self.assertEqual(j%5,4)
        self.assertEqual(setup['available_at'],current[j]['timestamp']+60000)
        self.assertNotIn(setup,entry_setups(current[:j],previous,entry_minutes=5))
        current[j+1]['low']=setup['entry']-.05
        trade=replay_limit(setup,current)
        self.assertEqual(trade['entry_index'],j+1)
        # Participation uses the preceding1m signal volume for both timeframes.
        self.assertEqual(setup['volume'],current[j]['volume'])

    def test_atr_floor_widens_stop_without_using_later_prices(self):
        current,previous=fixture(1)
        current[29]['high']=106
        structural=entry_setups(current,previous)
        widened=entry_setups(current,previous,atr_minimum=True)
        self.assertTrue(structural and widened)
        setup=widened[0]
        self.assertTrue(setup['atr_floor_used'])
        self.assertLess(setup['stop'],setup['structural_stop'])
        self.assertAlmostEqual(setup['entry']-setup['stop'],setup['prior_atr'])
        j=setup['signal_index']
        self.assertIn(setup,entry_setups(current[:j+1],previous,atr_minimum=True))
        future=deepcopy(current)
        for b in future[j+1:]:b.update(open=1000,high=2000,low=900,close=1000)
        self.assertIn(setup,entry_setups(future,previous,atr_minimum=True))

    def test_five_minute_signals_are_prefix_causal(self):
        current,previous=fixture(5)
        for atr in (False,True):
            setups=entry_setups(current,previous,entry_minutes=5,atr_minimum=atr)
            self.assertTrue(setups)
            for size in (160,210,215,300):
                self.assertEqual(entry_setups(current[:size],previous,entry_minutes=5,atr_minimum=atr),
                                 [s for s in setups if s['signal_index']<size])

    def test_invalid_timeframe_is_rejected(self):
        current,previous=fixture(1)
        with self.assertRaises(ValueError):entry_setups(current,previous,entry_minutes=3)

    def test_wider_ceiling_is_explicit_and_default_is_preserved(self):
        current,previous=fixture(1)
        current[29]['high']=110
        narrow=entry_setups(current,previous,atr_minimum=True)
        wide=entry_setups(current,previous,atr_minimum=True,max_stop_fraction=.02)
        self.assertTrue(wide)
        self.assertTrue(any((s['entry']-s['stop'])/s['entry']>.005 for s in wide))
        self.assertTrue(all((s['entry']-s['stop'])/s['entry']<=.005 for s in narrow))
        self.assertEqual(entry_setups(current,previous),entry_setups(current,previous,max_stop_fraction=.005))
        for invalid in (0,float('nan'),1):
            with self.assertRaises(ValueError):entry_setups(current,previous,max_stop_fraction=invalid)


if __name__=='__main__':unittest.main()

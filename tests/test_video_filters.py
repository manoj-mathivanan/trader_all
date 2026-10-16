import unittest
from copy import deepcopy

from core.research.video_filters import prior_market_regimes,setup_features,filter_flags,context_features
from core.research.video_methods import replay_limit,settlement
from tests.test_video_methods import bars


class VideoFiltersTest(unittest.TestCase):
    def test_benchmark_regime_never_uses_current_or_future_close(self):
        from datetime import date,timedelta
        rows=[dict(date=str(date(2025,1,1)+timedelta(days=j)),close=100+j) for j in range(70)]
        regimes=prior_market_regimes(rows)
        self.assertEqual(regimes[rows[50]['date']]['direction'],1)
        modified=deepcopy(rows)
        for b in modified[50:]:b['close']=1
        self.assertEqual(prior_market_regimes(modified)[rows[50]['date']],regimes[rows[50]['date']])
        for size in (51,55,60):
            self.assertEqual(prior_market_regimes(rows[:size]),
                             {d:r for d,r in regimes.items() if d<=rows[size-1]['date']})

    def test_relative_volume_denominator_excludes_signal_and_future(self):
        rows=bars([100]*40)
        rows[25]['volume']=15000
        setup=dict(signal_index=25,direction=1)
        features=setup_features(setup,rows)
        self.assertEqual(features['relative_volume'],1.5)
        self.assertEqual(features,setup_features(setup,rows[:26]))
        rows[26]['volume']=1e9
        self.assertEqual(features,setup_features(setup,rows))

    def test_atr_precedes_impulse_and_market_requires_previous_session(self):
        rows=bars([100]*40)
        setup=dict(signal_index=25)
        prior=setup_features(setup,rows)
        rows[24].update(open=100,close=102,high=103,low=99)
        updated=setup_features(setup,rows)
        self.assertEqual(updated['prior_atr'],prior['prior_atr'])
        self.assertGreater(updated['displacement_atr'],1)
        regime=dict(direction=1,as_of='2026-06-30')
        flags=filter_flags(setup,updated,regime,'2026-06-30')
        self.assertTrue(flags['market'])
        self.assertFalse(filter_flags(setup,updated,regime,'2026-06-29')['market'])
        self.assertFalse(filter_flags(dict(setup,direction=-1),updated,regime,'2026-06-30')['market'])

    def test_zero_volume_is_rejected_without_division_by_zero(self):
        rows=bars([100]*40)
        for b in rows:b['volume']=0
        features=setup_features(dict(signal_index=25),rows)
        self.assertIsNone(features['relative_volume'])
        self.assertFalse(filter_flags(dict(signal_index=25),features,None,'2026-06-30')['relative_volume'])

    def test_resting_buy_limit_does_not_avoid_gap_loss(self):
        rows=bars([100,98,98])
        setup=dict(signal_index=0,entry=100,stop=99,expires=2,volume=10000)
        trade=replay_limit(setup,rows)
        self.assertTrue(trade['gap_entry'])
        self.assertEqual((trade['entry'],trade['exit_raw']),(100,98))
        self.assertLess(settlement(trade,10)['net_pnl'],-20)
        self.assertIsNone(replay_limit(setup,rows,gap_policy='legacy_cancel'))

    def test_resting_short_limit_also_honours_gap_loss(self):
        rows=bars([100,102,102])
        setup=dict(signal_index=0,entry=100,stop=101,expires=2,volume=10000,direction=-1)
        trade=replay_limit(setup,rows)
        self.assertTrue(trade['gap_entry'])
        self.assertEqual((trade['entry'],trade['exit_raw']),(100,102))
        self.assertLess(settlement(trade,10)['net_pnl'],-20)
        self.assertIsNone(replay_limit(setup,rows,gap_policy='legacy_cancel'))

    def test_higher_gap_is_unavailable_until_third_frame_completes(self):
        values=[100,101,103,102,104,100,101.5,102]
        rows=bars([p for p in values for _ in range(15)])
        features=context_features(rows)
        self.assertFalse(features[43]['higher_fvg_zone'])
        self.assertFalse(features[44]['higher_fvg_zone']) # A new zone cannot validate its own entry formation.
        self.assertTrue(features[47]['higher_fvg_zone'])
        self.assertEqual(features[44]['available_at'],rows[44]['timestamp']+60000)
        self.assertFalse(features[90]['higher_fvg_zone']) # Prior close removed the zone.
        for size in (44,45,60,91):
            self.assertEqual(context_features(rows[:size]),features[:size])

    def test_invalidation_does_not_reset_on_a_simple_bounce(self):
        values=[100,102,104,102,100,101,103,102,101,100,99,100,101,102]
        rows=bars([p for p in values for _ in range(15)])
        features=context_features(rows)
        self.assertTrue(features[134]['context_invalidation'])
        self.assertFalse(features[164]['context_invalidation'])
        self.assertFalse(features[194]['context_invalidation'])

    def test_short_context_is_causal_and_symmetric(self):
        rows=bars([p for p in [100,101,103,102,104,100,101.5,102] for _ in range(15)])
        reflected=[dict(b,open=250-b['open'],close=250-b['close'],high=250-b['low'],low=250-b['high']) for b in rows]
        features=context_features(reflected,direction=-1)
        self.assertEqual(features,context_features(rows))
        for size in (44,45,60,91):
            self.assertEqual(context_features(reflected[:size],direction=-1),features[:size])


if __name__=='__main__':unittest.main()

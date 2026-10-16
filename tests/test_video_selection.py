import unittest
from copy import deepcopy
from core.research.video_selection import prior_liquidity_ranks,flags,time_bucket


class SelectionTest(unittest.TestCase):
    def test_ranking_excludes_current_and_future_prices_and_volume(self):
        rows=[dict(date=f'2026-01-{j+1:02}',close=100,volume=1000+j) for j in range(25)]
        panel={'AAA':rows,'BBB':[dict(b,volume=2000) for b in rows]}
        original=prior_liquidity_ranks(panel)
        changed=deepcopy(panel)
        for b in changed['AAA'][20:]:b.update(close=1e9,volume=1e9)
        self.assertEqual(original['2026-01-21'],prior_liquidity_ranks(changed)['2026-01-21'])
        self.assertEqual(original['2026-01-21']['BBB']['rank'],1)
        self.assertEqual(original['2026-01-21']['AAA']['as_of'],'2026-01-20')
        self.assertEqual(prior_liquidity_ranks({s:r[:21] for s,r in panel.items()}),{'2026-01-21':original['2026-01-21']})

    def test_tie_order_is_deterministic_and_duplicate_dates_rejected(self):
        rows=[dict(date=f'2026-01-{j+1:02}',close=100,volume=1000) for j in range(21)]
        self.assertEqual(prior_liquidity_ranks({'BBB':rows,'AAA':rows})['2026-01-21']['AAA']['rank'],1)
        with self.assertRaises(ValueError):prior_liquidity_ranks({'AAA':rows+rows[-1:]})

    def test_boundaries_and_direction_matching(self):
        t=dict(signal_time='10:29',direction=-1,market_direction=-1,liquidity_rank=10)
        self.assertTrue(flags(t)['early']);self.assertTrue(flags(t)['market_top10'])
        t['signal_time']='10:30';self.assertFalse(flags(t)['early'])
        self.assertEqual(time_bucket(t),'10:30-12:00')
        t['signal_time']='12:00';self.assertEqual(time_bucket(t),'12:00-14:30')
        t['market_direction']=0;self.assertFalse(flags(t)['market_aligned'])
        t['liquidity_rank']=11;self.assertFalse(flags(t)['top10_turnover'])


if __name__=='__main__':unittest.main()

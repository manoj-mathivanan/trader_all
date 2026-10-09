import unittest
from unittest.mock import patch

from core.research import backtest, fundamental_history as history, official_filings, intraday_long
from core.research.config import BacktestConfig, BearishBacktestConfig
from tests.test_official_filings import ITEM, URL, PRIOR, AT, document


class FundamentalRankingTests(unittest.TestCase):
    def config(self, **kw):
        return BacktestConfig(start='2026-07-09', end='2026-07-12', pattern='vcp', entry_mode='next_open',
                              candidate_rank='fundamental_score', max_positions=5, risk_pct=.5,
                              acknowledge_limitations=True, **kw)

    def test_highest_five_replace_alphabetical_when_slots_bind(self):
        bars = [dict(date=d, open=100, high=101, low=99, close=100, volume=1e6)
                for d in ('2026-07-09','2026-07-10','2026-07-11')]
        data = {s: bars for s in 'ABCDEFG'}
        scores = lambda s,d: dict(score=ord(s)-ord('A'), coverage_pct=85, flags=[])
        with patch.object(backtest, 'signal', side_effect=lambda b,i,c:i==0):
            ranked = backtest.simulate(data, self.config(), fundamental_scores=scores)
            alpha = backtest.simulate(data, self.config().model_copy(update={'candidate_rank':'alphabetical'}))
        buys = lambda r: [o['symbol'] for o in r['state']['orders'] if o['side']=='buy']
        self.assertEqual(buys(ranked), list('GFEDC'))
        self.assertEqual(buys(alpha), list('ABCDE'))
        self.assertEqual(ranked['state']['orders'][0]['fundamentals']['score'],6)

    def test_publication_time_and_comparison_filing_cutoff(self):
        current = official_filings.parse(document(profit='1200'), URL, ITEM, AT)
        prior = official_filings.parse(document(year=2025, revenue='100000', profit='1000'), PRIOR, ITEM, AT)
        # Even a prior-year comparison cannot be used before its publication.
        prior['filed_at'] = '2026-07-10T10:00:00+05:30'
        current['sha256'] = prior['sha256'] = 'a'*64
        payload = dict(series={'TCS':history.reconstruct([current,prior], ITEM)})
        payload['sha256'] = history.digest(payload)
        scores = history.Scores(payload)
        self.assertIsNone(scores('TCS','2026-07-09')['score']) # current after the open
        self.assertEqual(scores('TCS','2026-07-10')['coverage_pct'],5) # comparison not yet published
        self.assertEqual(scores('TCS','2026-07-11')['coverage_pct'],40)
        close = history.Scores(payload, 'close')
        self.assertEqual(close('TCS','2026-07-10')['coverage_pct'],40)
        payload['series']['TCS'][0]['snapshot']['profit_growth_pct'] = 999
        with self.assertRaisesRegex(ValueError,'checksum'):
            history.Scores(payload)

    def test_missing_stale_and_ties_are_deterministic(self):
        values = {'A':None, 'B':dict(score=90,coverage_pct=90,flags=['stale']),
                  'C':dict(score=60,coverage_pct=80,flags=[]), 'D':dict(score=60,coverage_pct=85,flags=[]),
                  'E':dict(score=60,coverage_pct=85,flags=[])}
        self.assertEqual(sorted(values,key=lambda s:history.rank_key(values[s],s)),list('DECAB'))
        with self.assertRaisesRegex(ValueError, 'dated'):
            backtest.simulate({},self.config())
        with self.assertRaises(ValueError):
            BearishBacktestConfig(start='2026-07-09',end='2026-07-12',candidate_rank='fundamental_score',acknowledge_limitations=True)

    def test_intraday_plan_uses_open_time_scores(self):
        bars = [dict(date=d,open=100,high=101,low=99,close=100,volume=1e6)
                for d in ('2026-07-09','2026-07-10')]
        cfg = self.config(execution_horizon='intraday')
        calls=[]
        def score(s,d):
            calls.append((s,d))
            return dict(score=90 if s=='Z' else 10,coverage_pct=85,flags=[])
        with patch('strategies.swing_patterns.patterns.signals.matches',return_value=True):
            plan=intraday_long.entry_plan({'A':bars,'Z':bars},cfg,fundamental_scores=score)
        self.assertEqual([x['symbol'] for x in plan['2026-07-10']],['Z','A'])
        self.assertEqual(set(d for s,d in calls),{'2026-07-10'})


if __name__ == '__main__':
    unittest.main()

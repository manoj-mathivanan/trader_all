import unittest
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch

from core.research import backtest, fundamental_history as history, official_filings, intraday_long, store
from core.research.config import BacktestConfig, BearishBacktestConfig
from tests.test_official_filings import ITEM, URL, PRIOR, AT, document


class FundamentalRankingTests(unittest.TestCase):
    def test_capture_reads_history_and_deduplicates_documents(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(store, 'DATA', Path(directory)):
            documents = []
            for url, html in ((URL, document(profit='1200')),
                              (PRIOR, document(year=2025, revenue='100000', profit='1000'))):
                raw = html.encode()
                digest = hashlib.sha256(raw).hexdigest()
                artifact = 'company/filings/'+digest+'.html'
                path = store.DATA/artifact
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
                documents.append(dict(url=url, sha256=digest, artifact=artifact))
            key = 'company/fundamentals/'+ITEM['isin']
            store.write(key, dict(validation={'status':'passed'}, documents=documents[:1]))
            store.write(key+'/history/older', dict(validation={'status':'passed'}, documents=documents))
            # Unvalidated historical records cannot add evidence.
            store.write(key+'/history/failed', dict(validation={'status':'failed'}, documents=[{'url':'invalid'}]))
            payload = history.capture({'instruments':[ITEM]})
            self.assertEqual(payload['excluded'], [])
            versions = payload['series']['TCS']
            self.assertEqual(len(versions), 2)
            self.assertEqual(len(versions[-1]['documents']), 2)
            self.assertEqual(versions[-1]['snapshot']['profit_growth_pct'], 20)
            self.assertLess(versions[0]['available_at'], versions[-1]['available_at'])
            # Valid historical evidence survives a failed current pull.
            store.write(key, dict(validation={'status':'failed'}, documents=[]))
            self.assertEqual(history.capture({'instruments':[ITEM]})['series'], payload['series'])
            # Presentation changes at one URL do not remove identical financial facts.
            variant = document(profit='1200').encode()+b'\n'
            digest = hashlib.sha256(variant).hexdigest()
            artifact = 'company/filings/'+digest+'.html'
            (store.DATA/artifact).write_bytes(variant)
            store.write(key+'/history/variant', dict(validation={'status':'passed'},
                        documents=[dict(url=URL, sha256=digest, artifact=artifact)]))
            self.assertEqual(history.capture({'instruments':[ITEM]})['series'], payload['series'])
            changed = document(profit='1400').encode()
            digest = hashlib.sha256(changed).hexdigest()
            artifact = 'company/filings/'+digest+'.html'
            (store.DATA/artifact).write_bytes(changed)
            store.write(key+'/history/variant', dict(validation={'status':'passed'},
                        documents=[dict(url=URL, sha256=digest, artifact=artifact)]))
            self.assertIn('Conflicting archived filing facts',
                          history.capture({'instruments':[ITEM]})['excluded'][0]['reason'])
            store.write(key+'/history/variant', dict(validation={'status':'failed'}))
            # Historical bytes receive the same checksum checks as current bytes.
            (store.DATA/documents[1]['artifact']).write_bytes(b'corrupt')
            rejected = history.capture({'instruments':[ITEM]})
            self.assertEqual(rejected['series'], {})
            self.assertIn('checksum mismatch', rejected['excluded'][0]['reason'])

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

    def test_new_standalone_period_is_not_hidden_by_old_consolidated_period(self):
        old = official_filings.parse(document(year=2025), PRIOR, ITEM, AT)
        new = official_filings.parse(document(basis='Standalone'), URL, ITEM, AT)
        old['sha256'] = new['sha256'] = 'a'*64
        versions = history.reconstruct([old, new], ITEM)
        self.assertEqual(versions[-1]['snapshot']['period_end'], '2026-06-30')
        self.assertEqual(versions[-1]['snapshot']['basis'], 'standalone')
        self.assertNotIn('revenue_growth_pct', versions[-1]['snapshot'])

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

import copy
import unittest

import httpx

from core.research import four_indicator_swing as fs
from core.research.analyst_consensus import ConsensusGate, IndianAPIClient, consensus
from tests import test_four_indicator_rs_paper as rs_fixtures


def payload(buy=3, hold=1):
    n=buy+hold
    return dict(companyName='Example',analystView=[
        dict(ratingValue=2,ratingName='Buy',numberOfAnalystsLatest=str(buy)),
        dict(ratingValue=3,ratingName='Hold',numberOfAnalystsLatest=str(hold)),
        dict(ratingValue=6,ratingName='Total',numberOfAnalystsLatest=str(n))],
        recosBar=dict(isDataPresent=True,noOfRecommendations=n,meanValue=(2*buy+3*hold)/n))


def observation(value=None):
    return dict(observed_at='2026-10-31T04:00:00+00:00',identity_verified=True,payload=value or payload())


class AnalystTests(unittest.TestCase):
    def test_exact_threshold_and_small_coverage(self):
        gate=ConsensusGate({'A':observation()},allow_hindsight=True)
        self.assertTrue(gate('A','2025-01-01','2025-01-02')[0])
        self.assertEqual(consensus(payload())['buy_share_pct'],75)
        self.assertFalse(ConsensusGate({'A':observation(payload(74,26))},allow_hindsight=True)('A','2025-01-01','2025-01-02')[0])
        self.assertTrue(ConsensusGate({'A':observation(payload(1,0))},allow_hindsight=True)('A','2025-01-01','2025-01-02')[0])

    def test_causal_future_stale_missing_and_identity(self):
        gate=ConsensusGate({'A':observation()})
        self.assertEqual(gate('A','2026-10-11','2026-10-12')[1]['reason'],'analyst_snapshot_not_yet_available')
        self.assertTrue(gate('A','2026-10-31','2026-11-02')[0])
        self.assertEqual(gate('A','2026-11-10','2026-11-11')[1]['reason'],'analyst_snapshot_stale')
        self.assertFalse(gate('MISSING','2026-10-31','2026-11-02')[0])
        obs=observation();obs['identity_verified']=False
        self.assertEqual(ConsensusGate({'A':obs},allow_hindsight=True)('A','2025-01-01','2025-01-02')[1]['reason'],'analyst_identity_unverified')

    def test_no_coverage_is_not_a_buy(self):
        empty=dict(companyName='Uncovered',analystView={},recosBar=dict(isDataPresent=False,meanValue=0,noOfRecommendations=0))
        self.assertEqual(consensus(empty)['status'],'no_coverage')
        self.assertFalse(ConsensusGate({'A':observation(empty)},allow_hindsight=True)('A','2025-01-01','2025-01-02')[0])
        with self.assertRaises(ValueError):consensus({})

    def test_malformed_votes_and_inconsistent_totals_fail_closed(self):
        for mutate in [lambda p:p['recosBar'].update(noOfRecommendations=10),
                       lambda p:p['recosBar'].update(meanValue=1),
                       lambda p:p['analystView'][0].update(numberOfAnalystsLatest='-1'),
                       lambda p:p['analystView'][0].update(ratingName='Outperform'),
                       lambda p:p['analystView'].append(copy.deepcopy(p['analystView'][0]))]:
            p=payload();mutate(p)
            self.assertFalse(ConsensusGate({'A':observation(p)},allow_hindsight=True)('A','2025-01-01','2025-01-02')[0])

    def test_requests_wait_after_response_and_no_automatic_retry(self):
        now=[100.0];starts=[];sleeps=[]
        def sleep(n):sleeps.append(n);now[0]+=n
        def handler(request):
            starts.append(now[0]);now[0]+=.2
            self.assertEqual(request.headers['X-API-Key'],'test-key')
            return httpx.Response(200,json=payload())
        client=IndianAPIClient('test-key',clock=lambda:now[0],sleep=sleep,transport=httpx.MockTransport(handler))
        try:
            client.stock('A');client.stock('B');client.stock('C')
            self.assertTrue(all(b-a>=1.2 for a,b in zip(starts,starts[1:])))
        finally:client.close()
        with self.assertRaises(ValueError):IndianAPIClient('test-key',interval=.99)
        calls=[]
        client=IndianAPIClient('test-key',sleep=lambda _:None,transport=httpx.MockTransport(lambda r:(calls.append(r) or httpx.Response(429))))
        try:
            with self.assertRaisesRegex(ValueError,'429'):client.stock('A')
            self.assertEqual(len(calls),1)
        finally:client.close()

    def test_filter_is_post_signal_and_does_not_change_exits_or_default_metrics(self):
        fixture=rs_fixtures.RSPaperTests();fixture.setUp()
        args=(fixture.data,fixture.signals,fixture.cfg,fs.RULES[3])
        original=fs.simulate(*args,liquidate=False)
        calls=[]
        def accept(symbol,signal_day,entry_day):
            calls.append((symbol,signal_day,entry_day));return True,{'reason':'test_pass'}
        accepted=fs.simulate(*args,liquidate=False,entry_filter=accept)
        self.assertEqual(original['metrics'],accepted['metrics'])
        self.assertEqual(original['curve'],accepted['curve'])
        self.assertTrue(calls)
        self.assertTrue(all(signal_day<entry_day for _,signal_day,entry_day in calls))
        self.assertEqual([o['date'] for o in original['ledger']['orders'] if o['side']=='SELL'],
                         [o['date'] for o in accepted['ledger']['orders'] if o['side']=='SELL'])
        blocked=fs.simulate(*args,liquidate=False,entry_filter=lambda *args:(False,{'reason':'test_reject'}))
        self.assertEqual(blocked['metrics']['final_equity'],fixture.cfg.capital)
        self.assertEqual(blocked['ledger']['orders'],[])


if __name__=='__main__':unittest.main()

import json
import os
import unittest
from unittest.mock import patch
from datetime import timedelta
import httpx
from core.research import company_review as review, store
from tests import test_company_review as base


class AutomaticResearchTests(unittest.TestCase):
    def setUp(self):
        base.CompanyReviewTests.setUp(self)
        self.addCleanup(patch.stopall)
        patch.object(review.official_filings, 'discover', return_value=dict(status='test', sources=[])).start()
    tearDown = base.CompanyReviewTests.tearDown

    def web_transport(self, value, *, search=True):
        discovered = ['https://example.com/results', 'https://news.example.org/article']
        def respond(request):
            payload = json.loads(request.content)
            self.assertFalse(payload['store'])
            if payload.get('tools'):
                self.assertEqual(payload['tools'][0]['type'], 'web_search')
                self.assertEqual(payload['tool_choice'], {'type': 'web_search'})
                self.assertLessEqual(payload['max_tool_calls'], 8)
                output = [dict(type='web_search_call', status='completed', action=dict(sources=[dict(url=u) for u in discovered]))] if search else []
                output.append(dict(type='message', content=[dict(type='output_text', text='Live research confirmed the exact company and found its latest quarterly results. Unknown figures remain unknown.')]))
            else:
                self.assertEqual(payload['text']['format']['name'], 'company_web_research')
                self.assertNotIn('tools', payload)
                output = [dict(type='message', content=[dict(type='output_text', text=json.dumps(value))])]
            return httpx.Response(200, json=dict(status='completed', id='test_response', output=output, usage={'total_tokens': 123}))
        return httpx.MockTransport(respond)

    def web_output(self, **changes):
        fund = base.financial()
        metrics = [dict(key=k, url=fund['source']['url'], measurement_period='Latest quarterly or annual statement, as applicable')
                   for k in review.MetricSource.model_fields['key'].annotation.__args__ if fund.get(k) is not None]
        value = dict(identity_confirmed=True, fundamentals=fund, financial_publication_date_is_exact=True, metric_sources=metrics,
                     findings=[dict(event='Quarterly results', kind='support', explanation='Revenue grew in the cited results.',
                       citations=[dict(url='https://example.com/results', title='Company results', published_date=(review.utcnow().date()-timedelta(days=1)).isoformat(), source_kind='company'),
                                  dict(url='https://news.example.org/article', title='Results reporting', published_date=(review.utcnow().date()-timedelta(days=1)).isoformat(), source_kind='reporting')])],
                     unknowns=['Upcoming earnings date not confirmed.'])
        value.update(changes)
        return value

    def auto_call(self, value, **options):
        with patch.dict(os.environ, {'TRADER_ENV': 'local', 'OPENAI_API_KEY': 'test-key', 'TRADER_NEWS_MODEL': 'test-model'}):
            return review.automatic_review(self.cfg, review.AutoResearchRequest(isin=base.ISIN), transport=self.web_transport(value, **options))

    def test_automatic_research_finds_sources_without_user_articles(self):
        saved = self.auto_call(self.web_output())
        self.assertEqual(saved['research_mode'], 'automatic_web')
        self.assertEqual(saved['news']['verdict'], 'supportive')
        self.assertIsNone(saved['fundamentals']['score'])
        self.assertEqual(saved['articles'], [])
        self.assertEqual(len(saved['retrieval']['sources']), 2)
        self.assertEqual(review.overview(self.cfg)['rows'][0]['latest_review']['id'], saved['id'])
        self.assertIsNone(review.overview(self.cfg)['rows'][0]['score'])

    def test_actual_search_and_exact_identity_required(self):
        for value, args in [(self.web_output(), {'search': False}), (self.web_output(identity_confirmed=False), {})]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.auto_call(value, **args)
            self.assertIsNone(store.read('company/reviews_index'))

    def test_invented_source_rejected_without_partial_write(self):
        value = self.web_output()
        value['findings'][0]['citations'][0]['url'] = 'https://invented.example.org/fake'
        with self.assertRaisesRegex(ValueError, 'unsearched source'):
            self.auto_call(value)
        self.assertIsNone(store.read('company/evidence'))

    def test_metrics_without_source_become_unknown(self):
        value = self.web_output()
        value['metric_sources'] = [m for m in value['metric_sources'] if m['key'] != 'revenue_growth_pct']
        saved = self.auto_call(value)
        self.assertIsNone(saved['fundamentals']['snapshot'])
        self.assertEqual(saved['fundamentals']['coverage_pct'], 0)

    def test_undated_news_cannot_support_buy(self):
        value = self.web_output()
        for citation in value['findings'][0]['citations']:
            citation['published_date'] = None
        saved = self.auto_call(value)
        self.assertEqual(saved['news']['verdict'], 'insufficient_evidence')
        self.assertEqual(saved['news']['findings'], [])

    def test_missing_financials_never_get_invented_score(self):
        saved = self.auto_call(self.web_output(fundamentals=None, metric_sources=[]))
        self.assertIsNone(saved['fundamentals']['score'])
        self.assertFalse(store.read('company/evidence', {}).get('fundamentals'))

    def test_unknown_publication_date_and_empty_metrics_do_not_create_snapshot(self):
        for changes in [dict(financial_publication_date_is_exact=False), dict(metric_sources=[])]:
            with self.subTest(changes=changes):
                saved = self.auto_call(self.web_output(**changes))
                self.assertIsNone(saved['fundamentals']['score'])
                self.assertIsNone(saved['fundamentals']['snapshot'])
                self.assertFalse(store.read('company/evidence', {}).get('fundamentals'))

    def test_legacy_empty_automatic_snapshot_is_not_scored(self):
        snapshot = base.financial()
        for key in review.MetricSource.model_fields['key'].annotation.__args__:
            snapshot[key] = None
        snapshot.update(recorded_at=store.now(), provenance='llm_web_search')
        self.assertIsNone(review.latest_snapshot({'fundamentals': [snapshot]}, base.ISIN, review.utcnow()))

    def test_official_snapshot_overrides_llm_figures(self):
        snapshot = base.financial(revenue_growth_pct=7)
        snapshot.update(provenance='official_nse_filing', metric_sources=[], calculations=[], extraction_notice='Official parser')
        with patch.object(review.official_filings, 'retrieve', return_value=dict(status='available', snapshot=snapshot, documents=[], failures=[])):
            saved = self.auto_call(self.web_output())
        self.assertEqual(saved['fundamentals']['snapshot']['revenue_growth_pct'], 7)
        self.assertEqual(saved['fundamentals']['snapshot']['provenance'], 'official_nse_filing')
        self.assertEqual(saved['fundamentals']['score'], 85)

    def test_route_requires_server_connection_and_queues_job(self):
        with patch.dict(os.environ, {'TRADER_ENV': 'local', 'OPENAI_API_KEY': '', 'TRADER_NEWS_MODEL': ''}):
            self.assertEqual(self.client.post('/api/company/research', json={'isin': base.ISIN}, headers=self.headers).status_code, 400)
        with patch.dict(os.environ, {'TRADER_ENV': 'local', 'OPENAI_API_KEY': 'test-key', 'TRADER_NEWS_MODEL': 'test-model'}), \
                patch('dashboard.api.company_review.jobs.submit', return_value={'id': 'test', 'status': 'queued'}) as submit:
            response = self.client.post('/api/company/research', json={'isin': base.ISIN}, headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['status'], 'queued')
            self.assertEqual(submit.call_args.args[0], 'Company web research')


if __name__ == '__main__':
    unittest.main()

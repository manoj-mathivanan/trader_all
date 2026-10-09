import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from pydantic import ValidationError

from core.research import company_review as review, store
from core.research.config import Settings, TradingConfig
from dashboard.api.main import app

ISIN = 'INE000A01001'
ITEM = dict(isin=ISIN, symbol='TEST', name='Test Company', sector='Industrials')


def financial(**changes):
    at = review.utcnow()
    value = dict(isin=ISIN, company_type='non_financial', period_end=(at.date()-timedelta(days=80)).isoformat(),
                 basis='consolidated', source=dict(title='Quarterly results', url='https://example.com/results',
                                                 published_at=(at-timedelta(days=40)).isoformat()),
                 revenue_growth_pct=20, profit_growth_pct=15, roe_pct=15, roce_pct=20, debt_equity=.5,
                 interest_coverage=4, cash_profit_ratio=1, promoter_pledge_pct=0,
                 auditor_concern=False, governance_concern=False)
    value.update(changes)
    return value


def article(**changes):
    value = dict(isin=ISIN, title='Results announcement', url='https://example.com/news',
                 published_at=(review.utcnow()-timedelta(days=1)).isoformat(), source_kind='reporting',
                 text='The company announced revenue growth of twenty percent. The filing also discusses its operating performance and cash flows.')
    value.update(changes)
    return value


class CompanyReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = patch.object(store, 'DATA', Path(self.temp.name))
        self.data.start()
        self.cfg = Settings()
        store.write('universes/niftytotalmarket', dict(instruments=[ITEM]))
        self.client = TestClient(app)
        self.headers = {'X-Trader-Request': 'local-ui'}

    def tearDown(self):
        self.data.stop()
        self.temp.cleanup()

    def import_data(self, **value):
        return review.import_evidence(self.cfg, review.ImportInput(**value))

    def test_missing_metrics_cannot_be_high_quality(self):
        missing = review.score(None)
        self.assertIsNone(missing['score'])
        value = financial()
        for k in list(value):
            if k not in ('isin', 'company_type', 'basis', 'period_end', 'source'):
                del value[k]
        result = review.score(value)
        self.assertEqual((result['score'], result['coverage_pct'], result['status']), (0, 0, 'incomplete'))

    def test_full_quality_and_red_flags(self):
        self.assertEqual(review.score(financial())['score'], 100)
        result = review.score(financial(auditor_concern=True, promoter_pledge_pct=25))
        self.assertEqual(result['status'], 'needs_review')
        self.assertEqual(len(result['flags']), 2)

    def test_financial_sectors_do_not_use_manufacturer_debt_rules(self):
        result = review.score(financial(company_type='bank', debt_equity=50, net_npa_pct=1, capital_adequacy_pct=18))
        self.assertEqual(result['score'], 100)
        self.assertNotIn('debt_equity', [c['key'] for c in result['checks']])
        self.assertEqual(review.score(financial(company_type='nbfc'))['coverage_pct'], 70)

    def test_stale_period_flag_even_if_publication_is_recent(self):
        value = financial(period_end=(review.utcnow().date()-timedelta(days=181)).isoformat())
        self.assertEqual(review.score(value)['status'], 'needs_review')

    def test_rejects_nonfinite_metrics_unknown_fields_and_unsafe_links(self):
        for changes in (dict(roe_pct=float('nan')), dict(roe_pct=float('inf')), dict(fake_metric=1),
                        dict(source=dict(title='Results', url='javascript:alert(1)', published_at=review.utcnow().isoformat()))):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                review.FundamentalInput(**financial(**changes))

    def test_future_and_naive_publication_rejected(self):
        for at in ((review.utcnow()+timedelta(days=1)).isoformat(), '2025-01-01T12:00:00'):
            with self.assertRaises(ValidationError):
                review.Article(**article(published_at=at))
        with self.assertRaises(ValidationError):
            review.FundamentalInput(**financial(period_end=review.utcnow().date().isoformat()))

    def test_import_idempotent_and_unknown_isin_batch_atomic(self):
        value = financial()
        self.assertEqual(self.import_data(fundamentals=[value])['fundamentals'], 1)
        self.assertEqual(self.import_data(fundamentals=[value])['duplicates'], 1)
        with self.assertRaises(ValueError):
            self.import_data(fundamentals=[financial(isin='INE000A01002')], articles=[article()])
        self.assertEqual(len(store.read('company/evidence')['articles']), 0)

    def test_old_quarter_import_does_not_replace_newer_quarter(self):
        self.import_data(fundamentals=[financial()])
        self.import_data(fundamentals=[financial(period_end=(review.utcnow().date()-timedelta(days=170)).isoformat())])
        latest = review.company_evidence(self.cfg, ISIN)['fundamentals']['snapshot']
        self.assertEqual(latest['period_end'], financial()['period_end'])

    def test_article_dedup_ignores_tracking_links_and_whitespace(self):
        self.import_data(articles=[article(), article(url='https://example.com/news?utm_source=other', text=article()['text']+' Additional information.'),
                                   article(url='https://another.example.com/item', text=article()['text'].replace(' ', '  '))])
        self.assertEqual(len(review.company_evidence(self.cfg, ISIN)['articles']), 1)

    def test_old_articles_and_future_recordings_excluded(self):
        self.import_data(articles=[article(published_at=(review.utcnow()-timedelta(days=31)).isoformat())])
        self.assertEqual(review.company_evidence(self.cfg, ISIN)['articles'], [])
        evidence = store.read('company/evidence')
        evidence['articles'][0]['published_at'] = review.utcnow().isoformat()
        evidence['articles'][0]['recorded_at'] = (review.utcnow()+timedelta(days=1)).isoformat()
        self.assertEqual(review.recent_articles(evidence, ISIN, review.utcnow()), [])

    def test_saved_review_immutable_and_not_a_trade(self):
        self.import_data(fundamentals=[financial()], articles=[article()])
        saved = review.create_review(self.cfg, review.ReviewRequest(isin=ISIN, disposition='would_skip'))
        self.import_data(fundamentals=[financial(revenue_growth_pct=-20)])
        stored = store.read('company/reviews/'+saved['id'])
        self.assertEqual(stored['fundamentals']['score'], 100)
        self.assertEqual(stored['disposition'], 'would_skip')
        self.assertEqual(stored['news']['verdict'], 'not_reviewed')
        self.assertFalse((store.DATA/'portfolios').exists())
        self.assertFalse((store.DATA/'runs').exists())

    def test_api_round_trip_and_path_validation(self):
        response = self.client.post('/api/company/evidence', json={'fundamentals': [financial()]}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        result = self.client.get('/api/company').json()
        self.assertEqual(result['rows'][0]['score'], 100)
        saved = self.client.post('/api/company/reviews', json={'isin': ISIN}, headers=self.headers).json()
        self.assertEqual(self.client.get('/api/company/reviews/'+saved['id']).json()['id'], saved['id'])
        self.assertEqual(self.client.get('/api/company/reviews/not-a-review').status_code, 404)
        self.assertEqual(self.client.post('/api/company/reviews', json={'isin': ISIN}).status_code, 403)

    def test_unknown_company_and_empty_import_rejected(self):
        with self.assertRaises(ValidationError):
            review.ImportInput()
        with self.assertRaises(ValueError):
            review.create_review(self.cfg, review.ReviewRequest(isin='INE000A01002'))

    def test_public_unauthenticated_deployment_cannot_trigger_paid_llm(self):
        with patch.dict(os.environ, {'TRADER_ENV': 'production', 'DASHBOARD_ADMIN_USER': '', 'DASHBOARD_ADMIN_PASSWORD': '',
                                     'OPENAI_API_KEY': 'private-test-key', 'TRADER_NEWS_MODEL': 'configured-model'}):
            self.assertFalse(review.llm_status()['enabled'])

    def call_model(self, findings, articles, status='completed', http_status=200):
        def respond(request):
            self.assertEqual(request.url.host, 'api.openai.com')
            payload = json.loads(request.content)
            self.assertFalse(payload['store'])
            self.assertTrue(payload['text']['format']['strict'])
            output = dict(findings=findings, unknowns=['No earnings calendar supplied.'])
            return httpx.Response(http_status, json=dict(status=status, id='response_test',
                                  output=[dict(content=[dict(type='output_text', text=json.dumps(output))])]))
        with patch.dict(os.environ, {'TRADER_ENV': 'local', 'OPENAI_API_KEY': 'private-test-key', 'TRADER_NEWS_MODEL': 'configured-model'}):
            return review.analyze_news(ITEM, articles, transport=httpx.MockTransport(respond))

    def model_articles(self):
        self.import_data(articles=[article(), article(url='https://second.example.org/report', text=article()['text']+' The full filing is available on the exchange.')])
        return review.company_evidence(self.cfg, ISIN)['articles']

    def finding(self, articles, kind='support'):
        return dict(event='Quarterly results', kind=kind, explanation='Revenue grew according to the supplied reports.',
                    citations=[dict(article_id=a['id'], excerpt='The company announced revenue growth of twenty percent.') for a in articles])

    def test_llm_support_requires_multiple_cited_nonopinion_domains(self):
        articles = self.model_articles()
        self.assertEqual(self.call_model([self.finding(articles)], articles)['verdict'], 'supportive')
        self.assertEqual(self.call_model([self.finding(articles[:1])], articles)['verdict'], 'insufficient_evidence')
        for a in articles:
            a['source_kind'] = 'opinion'
        self.assertEqual(self.call_model([self.finding(articles)], articles)['verdict'], 'insufficient_evidence')

    def test_llm_risks_and_conflicting_evidence_not_confirmatory(self):
        articles = self.model_articles()
        self.assertEqual(self.call_model([self.finding(articles, 'risk')], articles)['verdict'], 'adverse')
        self.assertEqual(self.call_model([self.finding(articles), self.finding(articles, 'contradiction')], articles)['verdict'], 'mixed')
        self.assertEqual(self.call_model([], articles)['verdict'], 'insufficient_evidence')

    def test_llm_fabricated_quote_or_article_id_rejected(self):
        articles = self.model_articles()
        for bad in [dict(article_id=articles[0]['id'], excerpt='An invented positive statement.'),
                    dict(article_id='invented', excerpt='The company announced revenue growth of twenty percent.')]:
            finding = self.finding(articles)
            finding['citations'] = [bad]
            with self.assertRaisesRegex(ValueError, 'unsupported citation'):
                self.call_model([finding], articles)

    def test_provider_failure_and_incomplete_result_do_not_save_review(self):
        articles = self.model_articles()
        with self.assertRaisesRegex(ValueError, 'provider request failed'):
            self.call_model([], articles, http_status=401)
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            self.call_model([], articles, status='incomplete')
        self.assertIsNone(store.read('company/reviews_index'))

    def test_scan_completed_session_and_stale_exclusion(self):
        self.import_data(fundamentals=[financial()])
        other = dict(ITEM, isin='INE000A01002', symbol='OTHER')
        store.write('universes/niftytotalmarket', dict(instruments=[ITEM, other]))
        today = review.utcnow().astimezone(review.IST).date()
        bars = [dict(date=(today-timedelta(days=130-i)).isoformat(), open=100, high=101, low=99, close=100, volume=1000000) for i in range(131)]
        # Latest completed bar is the breakout; today's unfinished bar must be ignored.
        bars[-2].update(close=105, high=106, volume=2000000)
        store.write('bars/'+ISIN, dict(bars=bars))
        store.write('bars/'+other['isin'], dict(bars=bars[:-2]))
        with patch.object(market_history := review.market_history, 'prepare', side_effect=lambda item, record, **kw: (record['bars'], {})):
            result = review.technical_scan(self.cfg, TradingConfig(pattern='blue_sky', min_turnover=0))
        self.assertEqual(result['as_of'], (today-timedelta(days=1)).isoformat())
        self.assertEqual([m['symbol'] for m in result['matches']], ['TEST'])
        self.assertIn('Stale daily history', [x['reason'] for x in result['excluded']])

    def test_scan_market_gate_and_missing_rs_fail_closed(self):
        today = review.utcnow().astimezone(review.IST).date()
        bars = [dict(date=(today-timedelta(days=61-i)).isoformat(), open=100, high=101, low=99, close=100, volume=1000000) for i in range(61)]
        bars[-1].update(close=105, high=106, volume=2000000)
        store.write('bars/'+ISIN, dict(bars=bars))
        with patch.object(review.market_history, 'prepare', side_effect=lambda item, record, **kw: (record['bars'], {})):
            for cfg in [TradingConfig(pattern='blue_sky', min_turnover=0, min_rs_rating=80),
                        TradingConfig(pattern='blue_sky', min_turnover=0, skip_weak_markets=True)]:
                self.assertEqual(review.technical_scan(self.cfg, cfg)['matches'], [])


if __name__ == '__main__':
    unittest.main()

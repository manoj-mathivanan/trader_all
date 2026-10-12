import json
import os
import tempfile
import unittest
from datetime import timedelta
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import patch
from xml.sax.saxutils import escape

import httpx
from fastapi.testclient import TestClient
from core.research import investor_intelligence as intel, store
from core.research.config import Settings
from dashboard.api.main import app

ISIN = 'INE000A01001'
ITEM = dict(isin=ISIN, name='Example Industries Limited', symbol='EXAMPLE')


def rss(title='Example Industries wins an order', url='https://example.com/news', date=None):
    date = date or format_datetime(intel.company.utcnow()-timedelta(days=1))
    return f'<rss><channel><item><title>{escape(title)}</title><link>{escape(url)}</link><description>Order economics are not disclosed.</description><pubDate>{date}</pubDate></item></channel></rss>'.encode()


class InvestorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = patch.object(store, 'DATA', Path(self.temp.name))
        self.data.start()
        self.env = patch.dict(os.environ, {'TRADER_ENV':'local', 'OPENAI_API_KEY':'fixture', 'TRADER_NEWS_MODEL':'fixture'})
        self.env.start()
        self.cfg = Settings()
        store.write('universes/'+self.cfg.universe, dict(instruments=[ITEM]))

    def tearDown(self):
        self.env.stop()
        self.data.stop()
        self.temp.cleanup()

    def test_bad_dates_unsafe_links_and_entities_rejected(self):
        for body in (rss(date='invalid'), rss(url='http://example.com/a'), rss(date=format_datetime(intel.company.utcnow()+timedelta(days=1)))):
            rows, skipped = intel.parse_feed(body, intel.FEEDS[0], intel.company.utcnow())
            self.assertEqual(rows, [])
            self.assertEqual(skipped, 1)
        with self.assertRaises(ValueError):
            intel.parse_feed(b'<!DOCTYPE rss><rss/>', intel.FEEDS[0], intel.company.utcnow())

    def test_nse_exchange_local_timestamp(self):
        at = intel.company.utcnow()
        date = (at-timedelta(hours=1)).astimezone(intel.company.IST).strftime('%d-%b-%Y %H:%M:%S')
        rows, skipped = intel.parse_feed(rss(date=date), intel.FEEDS[0], at)
        self.assertEqual(skipped, 0)
        self.assertTrue(rows[0]['published_at'].endswith('+05:30'))
        rows, skipped = intel.parse_feed(rss(date=date), intel.FEEDS[1], at)
        self.assertEqual(rows, [])

    def test_partial_refresh_retains_evidence_and_first_seen(self):
        calls = []
        def handler(request):
            calls.append(request.url.host)
            return httpx.Response(503 if request.url.host=='nsearchives.nseindia.com' else 200, content=rss())
        transport = httpx.MockTransport(handler)
        result = intel.refresh_feeds(transport=transport)
        self.assertTrue(result['partial'])
        self.assertEqual(len(calls), 4)
        initial = store.read('investor/news')['articles'][0]['first_seen_at']
        intel.refresh_feeds(transport=transport)
        self.assertEqual(store.read('investor/news')['articles'][0]['first_seen_at'], initial)
        with self.assertRaises(ValueError):
            intel.refresh_feeds(force=True, transport=httpx.MockTransport(lambda r: httpx.Response(503)))
        self.assertEqual(len(intel.evidence(self.cfg, ISIN)['articles']), 1)

    def test_duplicate_grouping_and_ambiguous_symbols(self):
        articles, _ = intel.parse_feed(rss(), intel.FEEDS[0], intel.company.utcnow())
        self.assertTrue(intel.matches(ITEM, articles[0]))
        self.assertFalse(intel.matches(dict(name='Idea Limited', symbol='IDEA'), dict(text='A new idea for investors')))
        second = dict(articles[0], id='other', publisher='Other', url='https://other.com/news')
        self.assertEqual(len(intel.group_articles(articles+[second])), 1)
        self.assertEqual(len(intel.group_articles(articles+[second])[0]['copies']), 2)
        different = dict(articles[0], id='different', text=articles[0]['title']+' — A different disclosure.')
        self.assertEqual(len(intel.group_articles(articles+[different])), 2)

    def test_production_does_not_fetch_et(self):
        calls = []
        def handler(request):
            calls.append(request.url.host)
            return httpx.Response(200, content=rss())
        with patch.dict(os.environ, {'TRADER_ENV':'production'}):
            result = intel.refresh_feeds(transport=httpx.MockTransport(handler))
        self.assertNotIn('economictimes.indiatimes.com', calls)
        self.assertNotIn('www.livemint.com', calls)
        self.assertEqual(result['coverage'][-1]['status'], 'disabled')

    def test_cited_interpretation_and_rejection_preserves_previous(self):
        intel.refresh_feeds(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=rss())))
        a = intel.evidence(self.cfg, ISIN)['articles'][0]
        event = dict(event='Order', direction='positive', materiality='unknown', evidence_quality='strong',
                     horizon='unknown', explanation='Potential revenue support; order economics are unknown.',
                     unknowns=['Order size'], citations=[dict(article_id=a['id'], excerpt='Order economics are not disclosed.')])
        def transport(value):
            return httpx.MockTransport(lambda r: httpx.Response(200, json=dict(status='completed', id='fixture',
                output=[dict(content=[dict(type='output_text', text=json.dumps(value))])], usage={})))
        result = intel.interpret(self.cfg, ISIN, transport=transport(dict(events=[event], unknowns=[])))
        saved = store.read('investor/latest/'+ISIN)
        self.assertEqual(saved['outlook'], 'positive')
        self.assertEqual(saved['events'][0]['evidence_quality'], 'limited')
        event['citations'][0]['excerpt'] = 'Invented statement which was not supplied.'
        with self.assertRaises(ValueError):
            intel.interpret(self.cfg, ISIN, force=True, transport=transport(dict(events=[event], unknowns=[])))
        self.assertEqual(store.read('investor/latest/'+ISIN)['id'], result['review_id'])

    def test_api_identity_and_llm_gate(self):
        client = TestClient(app)
        self.assertEqual(client.get('/api/investor').status_code, 200)
        self.assertEqual(client.get('/api/investor/company/not-an-isin').status_code, 400)
        with patch.dict(os.environ, {'OPENAI_API_KEY':''}):
            response = client.post('/api/investor/interpret', json={'isin':ISIN}, headers={'X-Trader-Request':'local-ui'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(store.read('jobs', []), [])

    def test_news_cache_skips_network_and_archives_versions(self):
        transport = httpx.MockTransport(lambda r: httpx.Response(200, content=rss()))
        intel.refresh_feeds(transport=transport)
        with patch.object(httpx.Client, 'stream', side_effect=AssertionError('Network should not be called')):
            self.assertTrue(intel.refresh_feeds()['cached'])
        intel.refresh_feeds(force=True, transport=httpx.MockTransport(lambda r: httpx.Response(200, content=rss(title='Example Industries updates its order'))))
        self.assertEqual(len(list((store.DATA/'investor/articles').glob('*.json'))), 8)
        self.assertEqual(len(list((store.DATA/'investor/feed_responses').glob('*.json'))), 8)

    def test_interpretation_cache_invalidation_and_raw_response_archive(self):
        intel.refresh_feeds(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=rss())))
        response = dict(status='completed', id='fixture', output=[dict(content=[dict(type='output_text', text=json.dumps(dict(events=[],unknowns=['Limited evidence'])))])])
        transport=httpx.MockTransport(lambda r: httpx.Response(200,json=response))
        result=intel.interpret(self.cfg, ISIN, transport=transport)
        with patch.object(httpx.Client, 'post', side_effect=AssertionError('LLM should not be called')):
            self.assertTrue(intel.interpret(self.cfg, ISIN)['cached'])
        attempts=list((store.DATA/'investor/llm_responses').glob('*.json'))
        self.assertEqual(len(attempts),1)
        attempt=json.loads(attempts[0].read_text())
        self.assertEqual(attempt['response'],response)
        self.assertEqual(attempt['status'],'validated')
        intel.refresh_feeds(force=True,transport=httpx.MockTransport(lambda r: httpx.Response(200,content=rss(title='Example Industries reports a loss'))))
        self.assertFalse(intel.interpret(self.cfg,ISIN,transport=transport)['cached'])
        self.assertEqual(len(list((store.DATA/'investor/llm_responses').glob('*.json'))),2)

    def test_database_bundle_preserves_history_and_responses(self):
        from scripts.sync_investor_data import bundle
        intel.refresh_feeds(transport=httpx.MockTransport(lambda r: httpx.Response(200,content=rss())))
        store.write('investor/llm_responses/test',dict(id='test',status='rejected',response={'output':[]}))
        value=bundle(store.DATA)
        self.assertTrue(value['articles'])
        self.assertTrue(any(d['kind']=='llm_responses' and d['record']['status']=='rejected' for d in value['documents']))
        self.assertTrue(any(d['kind']=='feed_responses' for d in value['documents']))


if __name__ == '__main__':
    unittest.main()

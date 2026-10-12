import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
import httpx
from core.research import investor_upstox as news, investor_intelligence as intel, store


class UpstoxNewsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = patch.object(store, 'DATA', Path(self.temp.name))
        self.data.start()
        self.token = patch.object(store, 'token', return_value='test-secret')
        self.token.start()
        self.item = dict(isin='INE000A01001', symbol='EXAMPLE', name='Example Industries')

    def tearDown(self):
        self.token.stop()
        self.data.stop()
        self.temp.cleanup()

    def article(self, suffix='1', **fields):
        return dict(heading='Market development', summary='Provider summary only.',
                    article_link='https://upstox.com/news/article-' + suffix,
                    published_time=int((intel.company.utcnow() - timedelta(hours=1)).timestamp() * 1000), **fields)

    def response(self, data, page=1, total=1):
        return httpx.Response(200, json=dict(status='success', data=data,
                                           metadata=dict(page=dict(page_number=page, total_pages=total))))

    def test_key_matching_pagination_cache_and_archive(self):
        calls = []
        key = 'NSE_EQ|' + self.item['isin']
        def handler(r):
            calls.append(r)
            page = int(r.url.params['page_number'])
            return self.response({key: [self.article(str(page))], 'NSE_EQ|unrequested': [self.article('unrelated')]}, page, 2)
        result = news.refresh([self.item], transport=httpx.MockTransport(handler))
        self.assertFalse(result['partial'])
        self.assertEqual(result['count'], 2)
        self.assertEqual(len(calls), 2)
        articles = store.read('investor/news')['articles']
        self.assertTrue(all(intel.matches(self.item, a) for a in articles))
        self.assertTrue(all(a['evidence_scope'] == 'api_summary' for a in articles))
        self.assertFalse(intel.matches(dict(self.item, isin='INE000A01002'), articles[0]))
        news.refresh([self.item], transport=httpx.MockTransport(lambda r: self.fail('Cache missed')))
        from scripts.sync_investor_data import bundle
        saved = bundle(store.DATA)
        self.assertEqual(len(saved['articles']), 2)
        self.assertIn('feed_responses', {d['kind'] for d in saved['documents']})
        self.assertNotIn('test-secret', json.dumps(saved))

    def test_batches_max_30_and_shared_article_associations(self):
        items = [dict(self.item, isin=f'INE{i:09d}') for i in range(31)]
        calls = []
        def handler(r):
            keys = r.url.params['instrument_keys'].split(',')
            calls.append(len(keys))
            return self.response({key: [self.article()] for key in keys})
        result = news.refresh(items, transport=httpx.MockTransport(handler))
        self.assertEqual(calls, [30, 1])
        self.assertEqual(result['count'], 1)
        article = store.read('investor/news')['articles'][0]
        self.assertEqual(len(article['provider_instrument_keys']), 31)
        self.assertTrue(all(intel.matches(item, article) for item in items))

    def test_auth_failure_one_request_and_no_false_empty(self):
        calls = []
        def handler(r):
            calls.append(r)
            return httpx.Response(401)
        items = [dict(self.item, isin=f'INE{i:09d}') for i in range(31)]
        result = news.refresh(items, transport=httpx.MockTransport(handler))
        self.assertEqual(len(calls), 1)
        self.assertTrue(result['partial'])
        self.assertTrue(all(r['status'] == 'unavailable' for r in result['coverage']))

    def test_partial_pagination_retains_articles_and_flags_coverage(self):
        key = 'NSE_EQ|' + self.item['isin']
        def handler(r):
            return self.response({key: [self.article()]}, total=2) if r.url.params['page_number'] == '1' else httpx.Response(503)
        result = news.refresh([self.item], transport=httpx.MockTransport(handler))
        self.assertTrue(result['partial'])
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['coverage'][0]['status'], 'unavailable')
        news.refresh([self.item], force=True, transport=httpx.MockTransport(lambda r: httpx.Response(503)))
        self.assertEqual(len(store.read('investor/news')['articles']), 1)

    def test_invalid_dates_links_and_missing_pagination(self):
        key = 'NSE_EQ|' + self.item['isin']
        invalid = self.article()
        invalid['published_time'] = int((intel.company.utcnow() - timedelta(days=8)).timestamp() * 1000)
        unsafe = self.article('2')
        unsafe['article_link'] = 'http://127.0.0.1/private'
        result = news.refresh([self.item], transport=httpx.MockTransport(lambda r: self.response({key: [invalid, unsafe]})))
        self.assertEqual(result['count'], 0)
        self.assertEqual(result['coverage'][0]['skipped'], 2)
        self.assertTrue(result['partial'])
        result = news.refresh([self.item], force=True, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=dict(status='success', data={}))))
        self.assertTrue(result['partial'])

    def test_no_token_requires_no_network(self):
        with patch.object(store, 'token', side_effect=ValueError('Missing')):
            result = news.refresh([self.item], transport=httpx.MockTransport(lambda r: self.fail('No token')))
        self.assertTrue(result['partial'])
        self.assertEqual(result['coverage'][0]['status'], 'unavailable')

    def test_empty_is_unknown_and_full_text_separate(self):
        result = news.refresh([self.item], transport=httpx.MockTransport(lambda r: self.response({})))
        self.assertFalse(result['partial'])
        self.assertEqual(result['coverage'][0]['status'], 'empty')
        self.assertIn('unknown', result['coverage'][0]['reason'])
        from core.research import investor_articles
        self.assertTrue(investor_articles.allowed('https://upstox.com/news/article-1'))
        self.assertFalse(investor_articles.allowed('https://upstox.com.evil.com/news/article-1'))

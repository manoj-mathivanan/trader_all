import base64
import json
import tempfile
import unittest
from datetime import timedelta
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import patch
import httpx
from core.research import investor_discovery as discovery, investor_intelligence as intel, store


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.data=patch.object(store,'DATA',Path(self.temp.name));self.data.start()
        self.item=dict(isin='INE000A01001',symbol='BHEL',name='BHEL Ltd')
        self.at=intel.company.utcnow()

    def tearDown(self):
        self.data.stop();self.temp.cleanup()

    def rss(self,url='https://www.moneycontrol.com/news/example'):
        return f'<rss><channel><item><title>Bharat Heavy Electricals wins contract</title><link>{url}</link><pubDate>{format_datetime(self.at-timedelta(days=20))}</pubDate></item></channel></rss>'

    def test_searches_both_engines_alias_matching_and_cache(self):
        calls=[]
        def handler(r):
            calls.append(r.url.host);return httpx.Response(200,text=self.rss())
        result=discovery.refresh([self.item],transport=httpx.MockTransport(handler))
        self.assertEqual(calls,['news.google.com','www.bing.com'])
        self.assertEqual(result['count'],1)
        self.assertFalse(result['partial'])
        article=store.read('investor/news')['articles'][0]
        self.assertTrue(intel.matches(self.item,article))
        self.assertEqual(article['evidence_scope'],'rss_summary')
        discovery.refresh([self.item],transport=httpx.MockTransport(lambda r:self.fail('Unexpected request')))

    def test_failed_search_is_not_no_news(self):
        result=discovery.refresh([self.item],transport=httpx.MockTransport(lambda r:httpx.Response(503)))
        self.assertTrue(result['partial'])
        self.assertEqual(discovery.coverage_status(self.item,[],None,store.read('investor/news'))['status'],'coverage_incomplete')

    def test_google_original_and_unresolved_links(self):
        url='https://www.moneycontrol.com/news/example'
        token=base64.urlsafe_b64encode(b'\x08\x13'+url.encode()+b'\xd2\x01\x00').decode().rstrip('=')
        self.assertEqual(discovery.publisher_link('https://news.google.com/rss/articles/'+token),url)
        opaque='https://news.google.com/rss/articles/CAopaque'
        self.assertEqual(discovery.publisher_link(opaque),opaque)
        calls=[]
        def handler(r):
            calls.append(r.url.host)
            return httpx.Response(200,text=self.rss(opaque if r.url.host=='news.google.com' else url))
        discovery.refresh([self.item],transport=httpx.MockTransport(handler))
        self.assertEqual(len(calls),3)
        self.assertEqual(len(store.read('investor/news')['articles']),1)
        self.assertEqual(store.read('investor/news')['articles'][0]['url'],url)
        self.assertEqual(len(list((store.DATA/'investor/articles').glob('*.json'))),3)

    def test_archive_restores_both_environments_and_preserves_state(self):
        discovery.refresh([self.item],transport=httpx.MockTransport(lambda r:httpx.Response(200,text=self.rss())))
        article=store.read('investor/news')['articles'][0]
        store.write('investor/news',dict(articles=[]))
        store.write('investor/settings',dict(enabled=False))
        with patch('core.research.investor_database.read',return_value=dict(articles=[article],next_offset=None)) as read:
            result=discovery.restore_archive([self.item])
        self.assertEqual(read.call_count,2)
        self.assertEqual(result['count'],1)
        self.assertFalse(result['partial'])
        self.assertEqual(store.read('investor/settings'),dict(enabled=False))
        self.assertEqual(len(store.read('investor/news')['articles']),1)

    def test_coverage_distinguishes_empty_failed_unreadable_and_reviewed(self):
        news=dict(discovery_coverage=[dict(id=e,isin=self.item['isin'],status='empty',checked_at=self.at.isoformat(),skipped=0) for e in ('google_news','bing')])
        store.write('investor/discovery/archive',dict(as_of=self.at.isoformat(),isins=[self.item['isin']],partial=False))
        self.assertEqual(discovery.coverage_status(self.item,[],None,news)['status'],'no_relevant_news_found')
        store.write('investor/discovery/archive',dict(partial=True))
        self.assertEqual(discovery.coverage_status(self.item,[],None,news)['status'],'coverage_incomplete')
        a=dict(id='a',sha256='version')
        self.assertEqual(discovery.coverage_status(self.item,[a],None,news)['status'],'needs_full_article_review')
        store.write('investor/full_articles/a',dict(status='paywalled'))
        self.assertEqual(discovery.coverage_status(self.item,[a],None,news)['status'],'full_article_unavailable')
        store.write('investor/full_articles/a',dict(status='available',response_sha256='body'))
        review=dict(full_text=True,as_of=self.at.isoformat(),article_summaries=[dict(article_id='a')],articles=[dict(a,full_document_sha256='body')])
        self.assertEqual(discovery.coverage_status(self.item,[a],review,news)['status'],'reviewed')
        self.assertEqual(discovery.coverage_status(self.item,[dict(a,sha256='changed')],review,news)['status'],'needs_full_article_review')

    def test_invalid_feed_is_failed_not_empty(self):
        result=discovery.refresh([self.item],transport=httpx.MockTransport(lambda r:httpx.Response(200,text='<html/>')))
        self.assertTrue(result['partial'])

    def test_opaque_google_resolution_cache_and_fail_closed(self):
        url='https://news.google.com/rss/articles/opaque'
        original='https://www.moneycontrol.com/news/example'
        calls=[]
        def handler(r):
            calls.append(r)
            if r.method=='GET':return httpx.Response(200,text='<div data-n-a-sg="signature" data-n-a-ts="123"></div>')
            return httpx.Response(200,text=")]}'\n\n"+json.dumps([['wrb.fr','Fbv4je',json.dumps(['garturlres',original])]]))
        self.assertEqual(discovery.resolve_google(url,transport=httpx.MockTransport(handler)),original)
        self.assertEqual(discovery.resolve_google(url,transport=httpx.MockTransport(lambda r:self.fail('Cache missed'))),original)
        self.assertEqual(len(calls),2)
        unresolved=url+'2'
        self.assertEqual(discovery.resolve_google(unresolved,transport=httpx.MockTransport(lambda r:httpx.Response(200,text='Consent required'))),unresolved)

    def test_google_redirect_cannot_fetch_arbitrary_hosts(self):
        url='https://news.google.com/rss/articles/opaque'
        calls=[]
        def handler(r):
            calls.append(str(r.url));return httpx.Response(302,headers={'location':'http://127.0.0.1/private'})
        self.assertEqual(discovery.resolve_google(url,transport=httpx.MockTransport(handler)),url)
        self.assertEqual(len(calls),1)


if __name__=='__main__':unittest.main()

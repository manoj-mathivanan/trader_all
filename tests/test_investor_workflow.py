import io
import json
import math
import unittest
from datetime import timedelta
from unittest.mock import patch
import httpx
from pypdf import PdfWriter
from core.research import investor_articles as articles, investor_breakouts as breakout, investor_workflow as workflow, store
from tests.test_investor_intelligence import InvestorTests, ISIN, ITEM, rss, intel


class WorkflowTests(InvestorTests):
    def fixture_article(self):
        intel.refresh_feeds(transport=httpx.MockTransport(lambda r:httpx.Response(200,content=rss(url='https://www.business-standard.com/news/test'))))
        return intel.evidence(self.cfg,ISIN)['articles'][0]

    def article_transport(self,body=None):
        text=body or 'Order economics are not disclosed. '+'The company reported a development with uncertain financial impact. '*30
        content=json.dumps({'@type':'NewsArticle','articleBody':text})
        return httpx.MockTransport(lambda r:httpx.Response(200,content='<html><script type="application/ld+json">'+content+'</script></html>',headers={'content-type':'text/html'}))

    def llm_transport(self,value,requests=None):
        def handle(r):
            if requests is not None:requests.append(json.loads(r.content))
            return httpx.Response(200,json={'status':'completed','output':[{'content':[{'type':'output_text','text':json.dumps(value)}]}]})
        return httpx.MockTransport(handle)

    def output(self,a):
        return dict(events=[],unknowns=['Order economics unknown'],article_summaries=[dict(article_id=a['id'],summary='The reported order lacks disclosed economics and its financial impact remains uncertain.',sentiment='neutral',citations=[dict(article_id=a['id'],excerpt='Order economics are not disclosed.')])],thesis_assessment=dict(status='unknown',reason='No dated thesis.',citations=[]))

    def test_full_body_archived_and_cached(self):
        a=self.fixture_article();doc=articles.read(a,transport=self.article_transport())
        self.assertEqual(doc['status'],'available');self.assertGreater(len(doc['text']),2000)
        self.assertTrue(doc['raw_base64']);self.assertEqual(len(list((store.DATA/'investor/article_documents').glob('*.json'))),1)
        with patch.object(httpx.Client,'stream',side_effect=AssertionError('Network')):
            self.assertEqual(articles.read(a),doc)

    def test_redirect_ssrf_is_blocked(self):
        a=self.fixture_article();calls=[]
        def handler(r):calls.append(str(r.url));return httpx.Response(302,headers={'location':'http://127.0.0.1/private'})
        doc=articles.read(a,transport=httpx.MockTransport(handler))
        self.assertEqual(len(calls),1);self.assertEqual(doc['status'],'unavailable')
        self.assertFalse(articles.allowed('https://www.business-standard.com@localhost/a'))

    def test_paywall_and_teaser_do_not_qualify(self):
        body=b'<script type="application/ld+json">{"@type":"NewsArticle","isAccessibleForFree":false}</script>'
        self.assertEqual(articles.extract(body,'text/html')[1],'paywalled')
        self.assertEqual(articles.extract(b'<html><article>A short teaser only.</article></html>','text/html')[1],'incomplete')
        self.assertEqual(articles.canonical_text('India&#39;s\u200c company &ldquo;reported&rdquo;\xa0 growth'), 'India\'s company "reported" growth')

    def test_pdf_blank_page_requires_ocr(self):
        w=PdfWriter();w.add_blank_page(width=100,height=100);b=io.BytesIO();w.write(b)
        self.assertEqual(articles.extract(b.getvalue(),'application/pdf')[1],'incomplete')

    def test_full_interpretation_supplies_entire_body_and_saves_summary(self):
        a=self.fixture_article();requests=[];text='Order economics are not disclosed. '+'Whole body text. '*140+'End of entire article.'
        intel.interpret(self.cfg,ISIN,full_text=True,article_transport=self.article_transport(text),transport=self.llm_transport(self.output(a),requests))
        self.assertIn('End of entire article.',requests[0]['input'])
        review=store.read('investor/latest/'+ISIN);self.assertTrue(review['full_text'])
        self.assertEqual(review['article_summaries'][0]['article_id'],a['id'])
        self.assertEqual(len(list((store.DATA/'investor/article_summaries').glob('*.json'))),1)
        from scripts.sync_investor_data import bundle
        kinds={d['kind'] for d in bundle(store.DATA)['documents']}
        self.assertTrue({'article_documents','article_summaries','llm_responses','reviews'}<=kinds)

    def test_missing_summary_rejected_and_no_rss_fallback(self):
        a=self.fixture_article();value=self.output(a);value['article_summaries']=[]
        with self.assertRaisesRegex(ValueError,'Missing full-article summaries'):
            intel.interpret(self.cfg,ISIN,full_text=True,article_transport=self.article_transport(),transport=self.llm_transport(value))
        self.assertIsNone(store.read('investor/latest/'+ISIN))
        with patch.object(httpx.Client,'post',side_effect=AssertionError('LLM must not run')):
            with self.assertRaisesRegex(ValueError,'No complete accessible'):
                intel.interpret(self.cfg,ISIN,full_text=True,force=True,article_transport=httpx.MockTransport(lambda r:httpx.Response(403)))

    def test_quote_reference_is_resolved_and_unknown_reference_rejected(self):
        a=self.fixture_article();value=self.output(a)
        value['article_summaries'][0]['citations']=[dict(article_id=a['id'],quote_id='q1')]
        intel.interpret(self.cfg,ISIN,full_text=True,article_transport=self.article_transport(),transport=self.llm_transport(value))
        review=store.read('investor/latest/'+ISIN)
        self.assertEqual(review['article_summaries'][0]['citations'][0]['excerpt'],'Order economics are not disclosed.')
        value['article_summaries'][0]['citations'][0]['quote_id']='q99999'
        with self.assertRaisesRegex(ValueError,'Unsupported quote reference'):
            intel.interpret(self.cfg,ISIN,full_text=True,force=True,article_transport=self.article_transport(),transport=self.llm_transport(value))
        self.assertEqual(store.read('investor/latest/'+ISIN)['id'],review['id'])

    def test_old_news_cannot_create_exit_review(self):
        a=self.fixture_article();value=self.output(a);value['thesis_assessment']=dict(status='challenged',reason='The thesis is challenged.',citations=[dict(article_id=a['id'],excerpt='Order economics are not disclosed.')])
        context=dict(holding=True,thesis='Orders must support growth',entry_date=intel.company.utcnow().astimezone(intel.company.IST).date().isoformat())
        with self.assertRaisesRegex(ValueError,'preceding the holding'):
            intel.interpret(self.cfg,ISIN,full_text=True,context=context,article_transport=self.article_transport(),transport=self.llm_transport(value))
        self.assertIsNone(store.read('investor/latest/'+ISIN));self.assertFalse((store.DATA/'investor/article_summaries').exists())

    def test_cycle_prioritizes_holdings_then_candidates_and_reuses_current(self):
        holding=dict(isin=ISIN,company=ITEM,thesis='Growth',entry_date='2020-01-01',news_count=1,last_review=None,review_status='needs_full_article_review')
        candidate=dict(holding,isin='INE000A01002',company=dict(ITEM,isin='INE000A01002'))
        view=dict(holdings=[holding],candidates=[candidate],catalysts=[])
        store.write('investor/settings',dict(max_reviews=1))
        calls=[]
        def interpret(cfg,isin,**kw):
            calls.append(isin);store.write('investor/latest/'+isin,dict(id='x',full_text=True,context=kw['context'],thesis_assessment={'status':'unknown'}));return dict(review_id='x',isin=isin)
        with patch.object(intel,'refresh_feeds',return_value={'partial':False}),patch.object(breakout,'scan',return_value={'price_date':'2026-10-09','matches':[]}),patch.object(workflow,'queues',return_value=view),patch.object(intel,'interpret',side_effect=interpret):
            first=workflow.cycle(self.cfg);self.assertEqual(calls,[ISIN]);self.assertEqual(first['pending'],1)
            holding.update(review_status='no_material_adverse_event_found',last_review=store.now())
            workflow.cycle(self.cfg);self.assertEqual(calls,[ISIN,candidate['isin']])

    def test_thesis_change_creates_deduplicated_advisory_alert(self):
        row=dict(isin=ISIN,company=ITEM,thesis='Growth',entry_date='2020-01-01',news_count=1,last_review=None,review_status='needs_full_article_review')
        def interpret(*args,**kwargs):store.write('investor/latest/'+ISIN,dict(id='x',thesis_assessment={'status':'challenged','reason':'Growth cancelled','citations':[]}));return {'review_id':'x'}
        with patch.object(intel,'refresh_feeds',return_value={'partial':False}),patch.object(breakout,'scan',return_value={'price_date':'2026-10-09','matches':[]}),patch.object(workflow,'queues',return_value=dict(holdings=[row],candidates=[],catalysts=[])),patch.object(intel,'interpret',side_effect=interpret):
            workflow.cycle(self.cfg);workflow.cycle(self.cfg)
        paths=list((store.DATA/'investor/alerts').glob('*.json'));self.assertEqual(len(paths),1)
        alert=json.loads(paths[0].read_text());self.assertIn('No portfolio orders',alert['notice'])
        self.assertEqual(workflow.acknowledge(alert['id'])['status'],'acknowledged')


class BreakoutTests(unittest.TestCase):
    def bars(self,breaks=False):
        rows=[]
        for i in range(101):
            close=80+i*.2 if i<80 else 99+(i-80)*.025
            spread=1 if i<95 else .3
            rows.append(dict(date=(intel.company.utcnow().date()-timedelta(days=101-i)).isoformat(),open=close,high=close+spread,low=close-spread,close=close,volume=500000 if i<95 else 200000))
        if breaks:
            pivot=max(b['high'] for b in rows[-41:-1]);rows[-1].update(close=pivot*1.01,high=pivot*1.012,volume=800000)
        return rows

    def test_approach_breakout_and_prior_pivot(self):
        for breaks,stage in [(False,'approaching_breakout'),(True,'early_breakout')]:
            b=self.bars(breaks);r=breakout.setup(b,breakout.Rules());self.assertIsNotNone(r);self.assertEqual(r['stage'],stage)
            self.assertEqual(r['pivot'],max(x['high'] for x in b[-41:-1]))

    def test_rejects_chased_illiquid_invalid_and_short_history(self):
        for kind in ('extension','liquidity','invalid','short'):
            b=self.bars(True)
            if kind=='extension':b[-1]['close']*=1.1
            if kind=='liquidity':
                for x in b:x['volume']=10
            if kind=='invalid':b[-1]['volume']=math.nan
            if kind=='short':b=b[-99:]
            self.assertIsNone(breakout.setup(b,breakout.Rules()))

    def test_scan_excludes_incomplete_today_bar(self):
        import tempfile
        from pathlib import Path
        from core.research.config import Settings
        b=self.bars();expected=b[-1]['date']
        b.append(dict(b[-1],date=intel.company.utcnow().astimezone(intel.company.IST).date().isoformat(),close=9999,high=9999))
        with tempfile.TemporaryDirectory() as folder,patch.object(store,'DATA',Path(folder)),patch.object(intel.company,'instruments',return_value=[ITEM]),patch.object(breakout.market_history,'evidence',return_value={}),patch.object(breakout.market_history,'prepare',return_value=(b,{})),patch.object(breakout.corporate_actions,'adjusted_bars',side_effect=lambda bars,at:bars),patch.object(breakout.data_quality,'audit',return_value={'findings':[]}):
            store.write('bars/'+ISIN,{'bars':b})
            result=breakout.scan(Settings())
            self.assertEqual(result['price_date'],expected);self.assertEqual(result['matches'][0]['price_date'],expected)


if __name__=='__main__':unittest.main()

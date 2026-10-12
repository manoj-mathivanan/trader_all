import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import httpx
from core.research import investor_details as details, investor_intelligence as intel, investor_workflow as workflow, store


class DetailsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.data=patch.object(store,'DATA',Path(self.temp.name));self.data.start()
        self.token=patch.object(store,'token',return_value='fixture-secret');self.token.start()
        self.item=dict(isin='INE000A01001',symbol='EXAMPLE',name='Example')

    def tearDown(self):
        self.token.stop();self.data.stop();self.temp.cleanup()

    def test_complete_endpoints_full_statements_cache_and_safe_archive(self):
        requests=[]
        def handler(r):
            requests.append(r)
            if 'market-quote' in r.url.path:
                value={'NSE_EQ:EXAMPLE':dict(instrument_token='NSE_EQ|'+self.item['isin'],last_price=100)}
            elif r.url.path.endswith('key-ratios'):value=[]
            elif r.url.path.endswith(('share-holdings','corporate-actions','competitors')):value=[]
            else:value={}
            return httpx.Response(200,json=dict(status='success',data=value))
        with patch.object(details,'technical',return_value=dict(status='unavailable')):
            result=details.refresh([self.item],transport=httpx.MockTransport(handler))
            self.assertFalse(result['partial']);self.assertEqual(len(requests),10)
            self.assertTrue(any(r.url.params.get('time_period')=='quarterly' and r.url.params.get('fs')=='true' for r in requests))
            self.assertTrue(any('NSE_EQ|' in r.url.path and r.url.path.endswith('competitors') for r in requests))
            requests.clear();details.refresh([self.item],transport=httpx.MockTransport(handler))
            self.assertEqual(len(requests),1)
        from scripts.sync_investor_data import bundle
        saved=bundle(store.DATA)
        self.assertIn('stock_details',{r['kind'] for r in saved['documents']})
        self.assertNotIn('fixture-secret',str(saved))

    def test_failed_endpoint_does_not_silently_reuse_old_data_for_purchase(self):
        store.write('investor/stock_details/'+self.item['isin'],dict(sections=dict(profile=dict(status='available',data=dict(sector='Old'),as_of=store.now()))))
        with patch.object(details,'technical',return_value={}):
            details.refresh([self.item],force=True,transport=httpx.MockTransport(lambda r:httpx.Response(503)))
        saved=store.read('investor/stock_details/'+self.item['isin'])
        self.assertTrue(saved['partial']);self.assertEqual(saved['sections']['profile']['data']['sector'],'Old')
        self.assertIsNone(saved['fundamentals']['sector'])

    def fixture(self):
        article=dict(id='article',text='Supported article',published_at=store.now())
        evidence=dict(articles=[article],review=dict(id='review',as_of=store.now(),full_text=True,news_input_sha256=workflow.news_digest([article]),
                                                    article_summaries=[dict(article_id='article')],article_coverage=[dict(status='available')],events=[]))
        financials=dict(sector='Manufacturing',metrics=dict(net_profit=dict(value=10,quarterly=dict(value=5)),revenue=dict(value=100,annual_yoy_pct=10,quarterly=dict(period=intel.company.utcnow().strftime('%b %Y'))),operating_cash_flow=dict(value=20)),ratios={'P/E':dict(company=15,sector=20)})
        snapshot=dict(as_of=store.now(),partial=False,technical=dict(status='available',trend='bullish'),fundamentals=financials)
        return dict(stage='early_breakout'),evidence,snapshot

    def test_buy_candidate_requires_full_news_financials_and_confirmed_breakout(self):
        row,evidence,snapshot=self.fixture()
        self.assertEqual(details.assessment(row,evidence,snapshot)['decision'],'buy_candidate')
        row['stage']='approaching_breakout'
        self.assertEqual(details.assessment(row,evidence,snapshot)['decision'],'wait')
        row['stage']='early_breakout';snapshot['fundamentals']['ratios']={}
        self.assertEqual(details.assessment(row,evidence,snapshot)['decision'],'insufficient_data')

    def test_adverse_news_and_missing_article_summary_block_buy(self):
        row,evidence,snapshot=self.fixture()
        evidence['review']['events']=[dict(direction='negative',materiality='high')]
        self.assertEqual(details.assessment(row,evidence,snapshot)['decision'],'avoid')
        evidence['review']['events']=[];evidence['review']['article_summaries']=[]
        self.assertEqual(details.assessment(row,evidence,snapshot)['decision'],'insufficient_data')

    def test_known_negative_cash_flow_is_wait_not_missing_data(self):
        row,evidence,snapshot=self.fixture()
        snapshot['fundamentals']['metrics']['operating_cash_flow']['value']=-1
        result=details.assessment(row,evidence,snapshot)
        self.assertEqual(result['decision'],'wait');self.assertEqual(result['blockers'],[])
        snapshot['fundamentals']['metrics']['net_profit']['quarterly']['value']=-1
        self.assertEqual(details.assessment(row,evidence,snapshot)['decision'],'avoid')

    def test_weekends_off_hours_and_exchange_holidays_skip_monitoring(self):
        no_network=httpx.MockTransport(lambda r:self.fail('No market call outside market hours'))
        self.assertFalse(details.market_open(datetime(2026,10,11,10,0,tzinfo=intel.company.IST),transport=no_network))
        self.assertFalse(details.market_open(datetime(2026,10,12,16,0,tzinfo=intel.company.IST),transport=no_network))
        closed=httpx.MockTransport(lambda r:httpx.Response(200,json=dict(status='success',data=dict(exchange='NSE',status='CLOSING_END'))))
        self.assertFalse(details.market_open(datetime(2026,10,12,10,0,tzinfo=intel.company.IST),transport=closed))
        self.assertFalse(details.market_open(datetime(2026,10,12,10,0,tzinfo=intel.company.IST),transport=no_network))

    def test_holdings_alert_only_on_measured_deterioration(self):
        old=dict(technical=dict(trend='bullish'),fundamentals=dict(metrics=dict(net_profit=dict(quarterly=dict(value=10,period='Mar 2026')))))
        new=dict(technical=dict(trend='bearish'),fundamentals=dict(metrics=dict(net_profit=dict(quarterly=dict(value=-2,period='Jun 2026')))))
        self.assertEqual(len(details.holding_changes(old,new)),2)
        self.assertEqual(details.holding_changes({},new),[])
        self.assertEqual(details.holding_changes(old,dict(new,partial=True)),[])

    def test_manual_review_preserves_imported_holding_context(self):
        from dashboard.api import investor_intelligence as api
        holding=dict(isin=self.item['isin'],thesis='',entry_date='2026-10-07')
        def submit(label,run,payload,**kwargs):return run(lambda message:None,'fixture')
        with patch.object(api,'current_settings',return_value=object()), \
             patch.object(intel,'selected_company',return_value=self.item), \
             patch.object(intel.company,'llm_status',return_value=dict(enabled=True)), \
             patch.object(workflow,'paper_holdings',return_value=[holding]), \
             patch.object(api.jobs,'submit',side_effect=submit), \
             patch.object(intel,'interpret',return_value={}) as review:
            api.interpret(intel.ResearchRequest(isin=self.item['isin']))
        self.assertEqual(review.call_args.kwargs['context'],dict(thesis='',entry_date='2026-10-07',holding=True))

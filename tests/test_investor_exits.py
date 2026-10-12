import unittest
from copy import deepcopy
from datetime import datetime,timedelta
from unittest.mock import patch
from core.research import investor_exits as exits,investor_discovery as discovery,store
from core.portfolio import paper
from tests.test_investor_intelligence import InvestorTests,ITEM,ISIN
import httpx


class ExitTests(unittest.TestCase):
    def setUp(self):
        self.clock=datetime(2026,10,12,10,0,tzinfo=paper.IST)
        self.portfolio=dict(id='swing_patterns',strategy_name='swing_patterns',mode='paper',status='active',config=paper.PaperConfig(capital=10000,acknowledge_limitations=True).model_dump(mode='json'),ledger=dict(cash=8998,positions={'EXAMPLE':dict(entry=100,entry_date='2026-10-07',entry_cost=1002,entry_fee=2,quantity=10,initial_risk=50)},marks={'EXAMPLE':105},orders=[],trades=[],curve=[]))
        stamp=int(self.clock.timestamp()*1000)
        self.quote=dict(timestamp=stamp,last_trade_time=stamp,last_price=110,depth=dict(buy=[dict(price=110,quantity=100)],sell=[dict(price=111,quantity=100)]))
        self.review=dict(id='r',as_of=self.clock.isoformat(),full_text=True,articles=[dict(id='a',published_at=(self.clock-timedelta(hours=1)).isoformat(),text='A major order was cancelled.')],events=[dict(direction='negative',materiality='high',evidence_quality='moderate',citations=[dict(article_id='a',excerpt='A major order was cancelled.')])],thesis_assessment=dict(status='unknown'))

    def run_exit(self,**kw):
        with patch.object(exits.intel.company,'utcnow',return_value=self.clock):
            return exits.transition(kw.get('portfolio',self.portfolio),'EXAMPLE',kw.get('quote',self.quote),kw.get('review',self.review),kw.get('clock',self.clock),'alert')

    def test_profitable_fill_accounts_and_idempotence(self):
        old=deepcopy(self.portfolio);updated,result=self.run_exit()
        self.assertEqual(result['status'],'executed');self.assertEqual(self.portfolio,old)
        self.assertNotIn('EXAMPLE',updated['ledger']['positions']);self.assertGreater(updated['ledger']['cash'],10000)
        self.assertAlmostEqual(updated['ledger']['trades'][0]['pnl'],result['net_profit'])
        again,outcome=self.run_exit(portfolio=updated);self.assertEqual(outcome['status'],'already_closed');self.assertEqual(again,updated)
        self.assertEqual(updated['ledger']['curve'],[])

    def test_gross_profit_but_net_loss_does_not_exit(self):
        q=deepcopy(self.quote);q['depth']['buy'][0]['price']=100.05;q['depth']['sell'][0]['price']=100.1;q['last_price']=100.05
        updated,result=self.run_exit(quote=q);self.assertEqual(result['status'],'not_profitable_after_costs');self.assertEqual(updated,self.portfolio)

    def test_stale_illiquid_weekend_quote_and_old_evidence_do_not_exit(self):
        q=deepcopy(self.quote);q['timestamp']-=120000
        self.assertEqual(self.run_exit(quote=q)[1]['status'],'waiting_fresh_quote')
        q=deepcopy(self.quote);q['depth']['buy'][0]['quantity']=1
        self.assertEqual(self.run_exit(quote=q)[1]['status'],'waiting_bid_liquidity')
        self.assertEqual(self.run_exit(clock=self.clock-timedelta(days=1))[1]['status'],'waiting_market_open')
        r=deepcopy(self.review);r['articles'][0]['published_at']='2026-10-06T10:00:00+05:30'
        self.assertEqual(self.run_exit(review=r)[1]['status'],'no_current_post_entry_discrepancy')

    def test_missing_full_text_or_mixed_sentiment_does_not_exit(self):
        r=deepcopy(self.review);r['full_text']=False
        self.assertEqual(self.run_exit(review=r)[1]['status'],'no_current_post_entry_discrepancy')
        r=deepcopy(self.review);r['events'][0]['direction']='mixed'
        self.assertEqual(self.run_exit(review=r)[1]['status'],'no_current_post_entry_discrepancy')


class DiscoveryTests(InvestorTests):
    def test_direct_publisher_url_date_matching_and_cache(self):
        date=(discovery.intel.company.utcnow()-timedelta(days=1)).strftime('%a, %d %b %Y %H:%M:%S GMT')
        body=f'<rss><channel><item><title>Example Industries wins an order</title><description>Financial terms not disclosed.</description><link>http://www.bing.com/news/apiclick.aspx?url=https%3A%2F%2Fwww.business-standard.com%2Fnews%2Ftest</link><pubDate>{date}</pubDate></item></channel></rss>'.encode()
        calls=[]
        def handler(r):calls.append(r);return httpx.Response(200,content=body)
        result=discovery.refresh([ITEM],transport=httpx.MockTransport(handler));self.assertEqual(result['count'],1)
        a=store.read('investor/news')['articles'][0];self.assertEqual(a['url'],'https://www.business-standard.com/news/test');self.assertEqual(a['discovery_isin'],ISIN)
        discovery.refresh([ITEM],transport=httpx.MockTransport(handler));self.assertEqual(len(calls),2)


if __name__=='__main__':unittest.main()

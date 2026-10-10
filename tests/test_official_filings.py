import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import httpx
from core.research import official_filings as filing, store

ITEM = dict(isin='INE467B01029', symbol='TCS', sector='Information Technology')
URL = 'https://nsearchives.nseindia.com/corporate/ixbrl/INTEGRATED_FILING_INDAS_173420_09072026183620_iXBRL_WEB.html'
PRIOR = 'https://nsearchives.nseindia.com/corporate/ixbrl/INTEGRATED_FILING_INDAS_123420_09072025183620_iXBRL_WEB.html'
AT = datetime(2026, 10, 8, tzinfo=timezone.utc)


def document(year=2026, revenue='1,10,000.00', profit='(1,200.00)', unit='Lakhs', basis='Consolidated', isin=ITEM['isin']):
    rows = [('ISIN', isin), ('NSE Symbol', 'TCS'), ('Description of presentation currency', 'INR'),
            ('Level of rounding used in financial results', unit),
            ('Date of start of reporting period', f'01-04-{year}', f'01-04-{year}'),
            ('Date of end of reporting period', f'30-06-{year}', f'30-06-{year}'),
            ('Nature of report standalone or consolidated', basis, basis),
            ('Date of board meeting when results were approved', f'09-07-{year}'),
            ('Declaration of unmodified opinion or statement on impact of audit qualification', 'Declaration of unmodified opinion'),
            ('Revenue from operations', revenue, '9,99,999'),
            ('Total profit (loss) for period', profit, '9,99,999'),
            ('Total profit before tax', '1500', '9,99,999'), ('Finance costs', '100', '9,99,999'),
            ('Debt equity ratio', '0', '0')]
    return '<table>'+''.join('<tr>'+''.join('<td>'+v+'</td>' for v in row)+'</tr>' for row in rows)+'</table>'


class OfficialFilingTests(unittest.TestCase):
    def test_repeat_retrieval_reuses_verified_bytes_without_http_requests(self):
        requests=[]
        def respond(request):
            requests.append(str(request.url))
            return httpx.Response(200,headers={'content-type':'text/html'},text=document())
        with tempfile.TemporaryDirectory() as directory, patch.object(store,'DATA',Path(directory)):
            transport=httpx.MockTransport(respond)
            first=filing.retrieve(ITEM,[{'url':URL}],AT,transport=transport)
            second=filing.retrieve(ITEM,[{'url':URL}],AT,transport=transport)
            self.assertEqual(requests,[URL])
            self.assertEqual(first['snapshot'],second['snapshot'])
            self.assertEqual(first['documents'],second['documents'])

    def test_new_filing_downloads_only_missing_document(self):
        requests=[]
        def respond(request):
            requests.append(str(request.url))
            return httpx.Response(200,headers={'content-type':'text/html'},text=document(
                year=2025,revenue='100000',profit='1000') if str(request.url)==PRIOR else document(profit='1200'))
        with tempfile.TemporaryDirectory() as directory, patch.object(store,'DATA',Path(directory)):
            transport=httpx.MockTransport(respond)
            filing.retrieve(ITEM,[{'url':PRIOR}],AT,transport=transport)
            requests.clear()
            result=filing.retrieve(ITEM,[{'url':URL},{'url':PRIOR}],AT,transport=transport)
        self.assertEqual(requests,[URL])
        self.assertAlmostEqual(result['snapshot']['revenue_growth_pct'],10)

    def test_tampered_filing_cache_is_redownloaded_and_repaired(self):
        requests=[]
        def respond(request):
            requests.append(str(request.url))
            return httpx.Response(200,headers={'content-type':'text/html'},text=document())
        with tempfile.TemporaryDirectory() as directory, patch.object(store,'DATA',Path(directory)):
            transport=httpx.MockTransport(respond)
            first=filing.retrieve(ITEM,[{'url':URL}],AT,transport=transport)
            path=store.DATA/first['documents'][0]['artifact']
            path.write_bytes(b'tampered')
            second=filing.retrieve(ITEM,[{'url':URL}],AT,transport=transport)
            third=filing.retrieve(ITEM,[{'url':URL}],AT,transport=transport)
        self.assertEqual(requests,[URL,URL])
        self.assertEqual(first['snapshot'],second['snapshot'])
        self.assertEqual(second['snapshot'],third['snapshot'])

    def test_existing_document_metadata_seeds_cache_without_redownload(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory, patch.object(store,'DATA',Path(directory)):
            raw=document().encode()
            digest=hashlib.sha256(raw).hexdigest()
            artifact='company/filings/'+digest+'.html'
            path=store.DATA/artifact
            path.parent.mkdir(parents=True)
            path.write_bytes(raw)
            requests=[]
            transport=httpx.MockTransport(lambda request: requests.append(request) or httpx.Response(500))
            result=filing.retrieve(ITEM,[{'url':URL}],AT,transport=transport,
                                   cached_documents=[dict(url=URL,sha256=digest,artifact=artifact)])
        self.assertEqual(requests,[])
        self.assertEqual(result['status'],'available')

    def test_bank_and_nbfc_growth_uses_taxonomy_and_no_industrial_ratios(self):
        for taxonomy,kind,revenue,profit in (
            ('BANKING','bank','Total income','Net profit (loss) for the period'),
            ('NBFC_INDAS','nbfc','Total Revenue From Operations','Total profit (loss) for period')):
            with self.subTest(kind=kind):
                current=document(profit='1200').replace('Revenue from operations',revenue).replace('Total profit (loss) for period',profit)
                previous=document(year=2025,revenue='100000',profit='1000').replace('Revenue from operations',revenue).replace('Total profit (loss) for period',profit)
                parsed=filing.parse(current,URL.replace('FILING_INDAS_','FILING_'+taxonomy+'_'),ITEM,AT)
                prior=filing.parse(previous,PRIOR.replace('FILING_INDAS_','FILING_'+taxonomy+'_'),ITEM,AT)
                snapshot=filing.calculate([parsed,prior],ITEM)
                self.assertEqual(snapshot['company_type'],kind)
                self.assertAlmostEqual(snapshot['revenue_growth_pct'],10)
                self.assertAlmostEqual(snapshot['profit_growth_pct'],20)
                for field in ('roce_pct','debt_equity','interest_coverage','cash_profit_ratio','net_npa_pct','capital_adequacy_pct'):
                    self.assertNotIn(field,snapshot)

    def test_history_discovery_keeps_intermediate_quarters(self):
        payload = {'data': [dict(symbol='TCS',qe_Date=period,consolidated='Consolidated',ixbrl=URL)
                            for period in ('30-Jun-2026','31-Mar-2026','31-Dec-2025','30-Sep-2025')]}
        transport = httpx.MockTransport(lambda request:httpx.Response(200,json=payload))
        current = filing.discover(ITEM,AT,transport=transport)
        history = filing.discover(ITEM,AT,transport=transport,history=True)
        self.assertNotIn('2025-12-31',{s['period_end'] for s in current['sources']})
        self.assertEqual({s['period_end'] for s in history['sources']},
                         {'2026-06-30','2026-03-31','2025-12-31','2025-09-30'})

    def test_segment_revenue_does_not_replace_primary_results(self):
        segment = ('<table><tr><td>Date of start of reporting period</td><td>01-04-2026</td></tr>'
                   '<tr><td>Segment Revenue (Income)</td></tr>'
                   '<tr><td>Revenue from operations</td><td>0</td></tr>'
                   '<tr><td>Total profit (loss) for period</td><td>999999</td></tr></table>')
        parsed = filing.parse(document(profit='1200') + segment, URL, ITEM, AT)
        self.assertEqual(parsed['amounts']['revenue'], '110000.00')
        self.assertEqual(parsed['amounts']['profit'], '1200')
        snapshot = filing.calculate([parsed, self.parse(year=2025, revenue='100000', profit='1000')], ITEM)
        self.assertAlmostEqual(snapshot['revenue_growth_pct'], 10)
        self.assertAlmostEqual(snapshot['profit_growth_pct'], 20)

    def test_conflicting_primary_revenue_is_still_rejected(self):
        conflict = '<tr><td>Revenue from operations</td><td>123</td></tr>'
        html = document().replace('</table>', conflict + '</table>')
        with self.assertRaisesRegex(ValueError, 'unambiguous'):
            filing.parse(html, URL, ITEM, AT)

    def test_full_year_ratios_use_ytd_and_average_balance_sheet(self):
        def annual_doc(year, equity, assets, liabilities):
            html=document(year=year, profit='100')
            html=html.replace(f'01-04-{year}',f'01-01-{year}').replace(f'30-06-{year}',f'31-03-{year}')
            html=html.replace('100</td><td>9,99,999','100</td><td>1200')
            html=html.replace('1500</td><td>9,99,999','1500</td><td>1600')
            html=html.replace('100</td><td>9,99,999','100</td><td>200')
            # Specify the annual finance cost independently of quarterly profit.
            html=html.replace('Finance costs</td><td>100</td><td>1200','Finance costs</td><td>100</td><td>200')
            rows=[('Date of start of financial year',f'01-04-{year-1}'),('Date of end of financial year',f'31-03-{year}'),
                  ('Total equity',str(equity)),('Total assets',str(assets)),('Total current liabilities',str(liabilities)),
                  ('Borrowings, current','50'),('Borrowings, non-current','100'),('Lease liabilities','20'),('Lease liabilities','30'),
                  ('Net cash flows from (used in) operating activities','1500'),('Date of start of reporting period',f'01-04-{year-1}')]
            return html+'<table>'+''.join('<tr>'+''.join('<td>'+v+'</td>' for v in row)+'</tr>' for row in rows)+'</table>'
        annual=filing.parse(annual_doc(2026,4000,8000,2000),URL,ITEM,AT)
        prior=filing.parse(annual_doc(2025,2000,6000,2000),PRIOR,ITEM,AT)
        snapshot=filing.calculate([self.parse(profit='1200'),annual,prior],ITEM)
        self.assertAlmostEqual(snapshot['roe_pct'],40) # 1200 / average(4000,2000)
        self.assertAlmostEqual(snapshot['roce_pct'],36) # (1600+200) / average(6000,4000)
        self.assertAlmostEqual(snapshot['debt_equity'],.05) # includes both lease liabilities
        self.assertAlmostEqual(snapshot['interest_coverage'],9)
        self.assertAlmostEqual(snapshot['cash_profit_ratio'],1.25)
        without_prior=filing.calculate([self.parse(),annual],ITEM)
        self.assertNotIn('roe_pct',without_prior)
        self.assertNotIn('roce_pct',without_prior)
        self.assertIn('cash_profit_ratio',without_prior)
    def parse(self, **kwargs):
        return filing.parse(document(**kwargs), URL if kwargs.get('year', 2026) == 2026 else PRIOR, ITEM, AT)

    def test_identity_dates_and_negative_indian_numbers(self):
        parsed = self.parse()
        self.assertEqual(parsed['amounts']['revenue'], '110000.00')
        self.assertEqual(parsed['amounts']['profit'], '-1200.00')
        self.assertEqual(parsed['filed_at'], '2026-07-09T18:36:20+05:30')
        with self.assertRaisesRegex(ValueError, 'identity'):
            self.parse(isin='INE000A01002')
        with self.assertRaisesRegex(ValueError, 'future'):
            filing.parse(document(), URL, ITEM, datetime(2026, 1, 1, tzinfo=timezone.utc))

    def test_growth_matches_period_units_basis_and_ignores_ytd(self):
        current = self.parse(profit='1200')
        previous = self.parse(year=2025, revenue='100000', profit='1000')
        snapshot = filing.calculate([previous, current], ITEM)
        self.assertAlmostEqual(snapshot['revenue_growth_pct'], 10)
        self.assertAlmostEqual(snapshot['profit_growth_pct'], 20)
        self.assertNotIn('debt_equity', snapshot)  # A template zero is not validated debt evidence.
        self.assertEqual(len(snapshot['metric_sources']), 5)
        self.assertEqual(snapshot['calculations'][0]['prior'], '10000000000')
        for mismatch in [dict(basis='Standalone')]:
            previous = self.parse(year=2025, **mismatch)
            self.assertNotIn('revenue_growth_pct', filing.calculate([previous, current], ITEM))

    def test_old_nse_dates_and_actual_rupees_normalize_before_growth(self):
        old = document(year=2025, revenue='10000000000', profit='100000000')
        old = old.replace('INR</td>', 'INR (in Actuals)</td>').replace('01-04-2025','01-Apr-2025').replace('30-06-2025','30-Jun-2025').replace('09-07-2025','09-Jul-2025')
        previous = filing.parse(old, PRIOR, ITEM, AT)
        snapshot = filing.calculate([previous, self.parse(profit='1200')], ITEM)
        self.assertAlmostEqual(snapshot['revenue_growth_pct'], 10)
        self.assertAlmostEqual(snapshot['profit_growth_pct'], 20)

    def test_negative_base_and_conflicting_revisions_excluded(self):
        current = self.parse()
        previous = self.parse(year=2025, profit='-100')
        self.assertNotIn('profit_growth_pct', filing.calculate([previous, current], ITEM))
        revised = self.parse(year=2025, profit='200')
        self.assertNotIn('revenue_growth_pct', filing.calculate([previous, revised, current], ITEM))

    def test_download_persists_original_and_hash(self):
        def respond(request):
            self.assertEqual(request.headers['user-agent'], 'TraderCompanyResearch/1.0')
            return httpx.Response(200, headers={'content-type': 'text/html'}, text=document())
        with tempfile.TemporaryDirectory() as directory, patch.object(store, 'DATA', Path(directory)):
            result = filing.retrieve(ITEM, [{'url': URL+'?utm_source=openai'}], AT, transport=httpx.MockTransport(respond))
            self.assertEqual(result['status'], 'available')
            saved = result['documents'][0]
            self.assertTrue((Path(directory)/saved['artifact']).exists())
            self.assertEqual(len(saved['sha256']), 64)
            self.assertEqual(result['snapshot']['provenance'], 'official_nse_filing')

    def test_download_errors_do_not_create_financial_snapshot(self):
        for status, headers, text in [(403, {}, ''), (302, {'location': 'https://127.0.0.1'}, ''),
                                      (200, {'content-type': 'text/html'}, document(isin='INE000A01002')),
                                      (200, {'content-type': 'text/html'}, 'x'*(filing.MAX_BYTES+1))]:
            with self.subTest(status=status):
                transport = httpx.MockTransport(lambda request: httpx.Response(status, headers=headers, text=text))
                result = filing.retrieve(ITEM, [{'url': URL}], AT, transport=transport)
                self.assertEqual(result['status'], 'unavailable')
                self.assertIsNone(result['snapshot'])
                self.assertEqual(len(result['failures']), 1)

    def test_only_supported_official_urls_are_requested(self):
        for url in ['https://127.0.0.1/private', URL.replace('nsearchives.nseindia.com','evil.example'),
                    URL.replace('https://', 'http://'), URL.replace('https://','https://user:password@')]:
            self.assertIsNone(filing.filing_url(url))
        result = filing.retrieve(ITEM, [{'url': 'https://example.com/results'}], AT)
        self.assertEqual(result['status'], 'no_supported_filings')
        with tempfile.TemporaryDirectory() as directory, patch.object(store,'DATA',Path(directory)):
            response=httpx.MockTransport(lambda request:httpx.Response(200,headers={'content-type':'text/html'},text=document()))
            financial=filing.retrieve({**ITEM,'sector':'Financial Services'}, [{'url':URL}], AT,transport=response)
            self.assertEqual(financial['status'],'available')

    def test_exchange_index_discovers_current_and_prior_without_llm_sources(self):
        def respond(request):
            self.assertEqual(request.headers['user-agent'], 'TraderCompanyResearch/1.0')
            if request.url.host == 'www.nseindia.com':
                self.assertEqual(request.url.params['symbol'], 'TCS')
                return httpx.Response(200,json={'data':[
                    dict(symbol='TCS',ixbrl=URL,qe_Date='30-JUN-2026',consolidated='Consolidated'),
                    dict(symbol='TCS',ixbrl=PRIOR,qe_Date='30-JUN-2025',consolidated='Consolidated'),
                    dict(symbol='OTHER',ixbrl=URL,qe_Date='30-JUN-2026',consolidated='Consolidated')]})
            return httpx.Response(200,headers={'content-type':'text/html'},text=document(
                year=2025, revenue='100000', profit='1000') if str(request.url)==PRIOR else document(profit='1200'))
        with tempfile.TemporaryDirectory() as directory, patch.object(store, 'DATA', Path(directory)):
            result=filing.retrieve(ITEM,[],AT,transport=httpx.MockTransport(respond),discover_index=True)
            self.assertEqual(result['index']['status'],'available')
            self.assertEqual(len(result['documents']),2)
            self.assertAlmostEqual(result['snapshot']['revenue_growth_pct'],10)


if __name__ == '__main__':
    unittest.main()

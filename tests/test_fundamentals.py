import hashlib
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from core.research import fundamentals as f, official_filings as nse, store, company_review as cr
from tests.test_official_filings import ITEM, URL, PRIOR, document, AT


class FundamentalsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patch=patch.object(store,'DATA',Path(self.tmp.name))
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.docs=[]; parsed=[]
        for url,year,revenue,profit in [(URL,2026,'110000','1200'),(PRIOR,2025,'100000','1000')]:
            raw=document(year,revenue,profit).encode()
            digest=hashlib.sha256(raw).hexdigest()
            artifact='company/filings/'+digest+'.html'
            path=store.DATA/artifact;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            self.docs.append(dict(url=url,sha256=digest,artifact=artifact))
            parsed.append(nse.parse(raw.decode(),url,ITEM,AT))
        self.snapshot=nse.calculate(parsed,ITEM)
        self.index=dict(status='available',url='https://www.nseindia.com/api/integrated-filing-results',sources=[
            dict(url=URL,period_end='2026-06-30',basis='consolidated'),dict(url=PRIOR,period_end='2025-06-30',basis='consolidated')])
        self.result=dict(snapshot=self.snapshot,documents=self.docs,failures=[])

    def pull(self,at=AT):
        with patch.object(nse,'discover',return_value=self.index), patch.object(nse,'retrieve',return_value=self.result):
            return f.pull_stock(ITEM,at=at)

    def test_quarter_boundaries_and_leap_year(self):
        self.assertEqual(str(f.completed_quarter(date(2026,10,8))),'2026-09-30')
        self.assertEqual(str(f.completed_quarter(date(2026,6,30))),'2026-06-30')
        self.assertEqual(str(f.completed_quarter(date(2024,2,29))),'2023-12-31')
        self.assertEqual(f.next_quarter('2026-12-31'),'2027-03-31')

    def test_unavailable_supported_filings_report_unsupported_and_retain_snapshot(self):
        self.pull()
        original=store.read(f.key(ITEM['isin']))['snapshot']
        with patch.object(nse,'discover',return_value=dict(status='available',sources=[])),patch.object(f.time,'sleep'):
            result=f.pull([ITEM],at=AT+timedelta(days=1))
        self.assertEqual(result['counts'],{'unsupported':1})
        self.assertTrue(result['partial'])
        self.assertEqual(store.read(f.key(ITEM['isin']))['snapshot'],original)

    def test_pull_lock_prevents_concurrent_process_writers(self):
        with f.pull_lock():
            with self.assertRaisesRegex(ValueError,'Another fundamentals pull'):
                with f.pull_lock():pass

    def test_api_persists_per_strategy_screen_and_returns_buy_rejection(self):
        from fastapi.testclient import TestClient
        from dashboard.api.main import app
        client=TestClient(app)
        self.pull()
        config=dict(min_score=100,min_coverage_pct=100,max_age_days=90)
        response=client.put('/api/company/buy-screen/intraday_momentum',json=config,headers={'x-trader-request':'local-ui'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(client.get('/api/company/buy-screen/intraday_momentum').json(),config)
        check=client.get('/api/company/buy-check/intraday_momentum/'+ITEM['isin']).json()
        self.assertFalse(check['buy_allowed'])
        self.assertEqual(check['screen'],config)
        self.assertEqual(client.get('/api/company/buy-screen/swing_patterns').json()['min_score'],60)
        self.assertEqual(client.put('/api/company/buy-screen/swing_patterns',json=dict(config,min_score=101),
                                    headers={'x-trader-request':'local-ui'}).status_code,422)

    def test_paper_can_use_retained_version_without_seeing_newer_quarter(self):
        self.pull()
        old=store.read(f.key(ITEM['isin']))
        newer=dict(old['snapshot'],recorded_at='2026-10-10T00:00:00+00:00',period_end='2026-09-30')
        store.write(f.key(ITEM['isin']),dict(old,snapshot=newer))
        selected=cr.latest_snapshot(dict(fundamentals=[]),ITEM['isin'],AT)
        self.assertEqual(selected['id'],old['snapshot']['id'])

    def test_store_validate_and_repeat_same_day_without_network(self):
        self.assertEqual(self.pull()['status'],'updated')
        record=store.read(f.key(ITEM['isin']))
        self.assertEqual(record['last_pulled_at'],AT.isoformat())
        self.assertEqual(record['last_period_end'],'2026-06-30')
        self.assertEqual(record['next_quarter_end'],'2026-09-30')
        self.assertEqual(record['validation']['status'],'passed')
        with patch.object(nse,'discover') as discover:
            self.assertEqual(f.pull_stock(ITEM,at=AT)['status'],'skipped_checked_today')
            discover.assert_not_called()
        self.assertEqual(f.audit([ITEM])['counts']['passed'],1)

    def test_current_quarter_skipped_even_on_later_day(self):
        at=datetime(2026,7,10,tzinfo=timezone.utc)
        self.pull(at)
        with patch.object(nse,'discover') as discover:
            self.assertEqual(f.pull_stock(ITEM,at=datetime(2026,8,10,tzinfo=timezone.utc))['status'],'skipped_current')
            discover.assert_not_called()

    def test_successful_check_reused_across_midnight_but_rechecked_after_24_hours(self):
        checked = datetime(2026,10,8,23,30,tzinfo=timezone.utc)
        self.pull(checked)
        with patch.object(nse,'discover',return_value=self.index) as discover, patch.object(nse,'retrieve') as retrieve:
            self.assertEqual(f.pull_stock(ITEM,at=checked+timedelta(hours=1))['status'],'skipped_recent_check')
            discover.assert_not_called()
            self.assertEqual(f.pull_stock(ITEM,at=checked+timedelta(hours=24))['status'],'awaiting_next_quarter')
            discover.assert_called_once()
            retrieve.assert_not_called()

    def test_bulk_cached_refresh_has_no_network_or_per_company_delay(self):
        self.pull()
        with patch.object(nse,'discover') as discover, patch.object(nse,'retrieve') as retrieve, \
             patch.object(f.time,'sleep') as sleep, patch.object(store,'write', wraps=store.write) as write:
            result=f.pull([ITEM]*75, at=AT+timedelta(hours=1))
        self.assertEqual(result['counts'],{'skipped_checked_today':75})
        discover.assert_not_called()
        retrieve.assert_not_called()
        sleep.assert_not_called()
        progress_writes=[call for call in write.call_args_list if call.args[0]=='company/fundamentals_pull']
        self.assertEqual(len(progress_writes),5)  # Start, three checkpoints, completion.

    def test_pull_passes_retained_documents_for_new_quarter_comparables(self):
        self.pull()
        saved=store.read(f.key(ITEM['isin']))
        self.index['sources'][0]['period_end']='2026-09-30'
        with patch.object(nse,'discover',return_value=self.index), \
             patch.object(nse,'retrieve',return_value=dict(snapshot=None)) as retrieve:
            f.pull_stock(ITEM,at=AT+timedelta(days=1))
        self.assertEqual(retrieve.call_args.kwargs['cached_documents'],saved['documents'])

    def test_unpublished_next_quarter_checks_index_without_redownload(self):
        self.pull()
        at=datetime(2026,10,9,tzinfo=timezone.utc)
        with patch.object(nse,'discover',return_value=self.index),patch.object(nse,'retrieve') as retrieve:
            self.assertEqual(f.pull_stock(ITEM,at=at)['status'],'awaiting_next_quarter')
            retrieve.assert_not_called()
        self.assertEqual(store.read(f.key(ITEM['isin']))['last_pulled_at'],AT.isoformat())

    def test_failed_new_quarter_retains_old_snapshot_and_explicit_retry(self):
        self.pull()
        old=store.read(f.key(ITEM['isin']))['snapshot']
        self.index['sources'][0]['period_end']='2026-09-30'
        at=datetime(2026,10,9,tzinfo=timezone.utc)
        with patch.object(nse,'discover',return_value=self.index),patch.object(nse,'retrieve',return_value=dict(snapshot=None)) as retrieve:
            self.assertEqual(f.pull_stock(ITEM,at=at)['status'],'failed')
            self.assertEqual(store.read(f.key(ITEM['isin']))['snapshot'],old)
            check=f.buy_check(ITEM['isin'],'swing_patterns',at=at,screen=f.BuyScreen(min_score=0,min_coverage_pct=0))
            self.assertIn('Newer published quarter has not passed validation',check['block_reasons'])
            self.assertEqual(f.pull_stock(ITEM,at=at)['status'],'skipped_checked_today')
            self.assertEqual(f.pull_stock(ITEM,at=at,retry_failed=True)['status'],'failed')
            self.assertEqual(retrieve.call_count,2)

    def test_tampered_hash_or_metric_rejected(self):
        self.pull()
        (store.DATA/self.docs[0]['artifact']).write_bytes(b'tampered')
        self.assertEqual(f.audit([ITEM])['counts']['failed'],1)
        with self.assertRaises(ValueError):
            f.validate(self.snapshot,self.docs,ITEM,AT)

    def test_same_metrics_but_altered_value_rejected(self):
        bad=dict(self.snapshot,revenue_growth_pct=999)
        with self.assertRaises(ValueError): f.validate(bad,self.docs,ITEM,AT)

    def test_buy_thresholds_both_strategies_missing_stale_and_point_in_time(self):
        self.assertFalse(f.buy_check(ITEM['isin'],'swing_patterns',at=AT)['buy_allowed'])
        self.pull()
        for strategy in ('swing_patterns','intraday_momentum'):
            screen=f.BuyScreen(min_score=0,min_coverage_pct=0,max_age_days=180)
            self.assertTrue(f.buy_check(ITEM['isin'],strategy,at=AT,screen=screen)['buy_allowed'])
            self.assertFalse(f.buy_check(ITEM['isin'],strategy,at=AT,screen=f.BuyScreen(min_score=100))['buy_allowed'])
            self.assertFalse(f.buy_check(ITEM['isin'],strategy,at=AT,screen=f.BuyScreen(min_score=0,min_coverage_pct=0,max_age_days=1))['buy_allowed'])
            earlier=datetime(2026,10,7,tzinfo=timezone.utc)
            self.assertFalse(f.buy_check(ITEM['isin'],strategy,at=earlier,screen=screen)['buy_allowed'])
        self.assertEqual(cr.latest_snapshot(dict(fundamentals=[]),ITEM['isin'],AT)['period_end'],'2026-06-30')

    def test_bulk_continues_after_bad_identity_and_mismatched_snapshot(self):
        items=[dict(ITEM,isin='invalid'),dict(ITEM,isin='INE089C01029',sector='Financial Services'),ITEM]
        with patch.object(nse,'discover',return_value=self.index),patch.object(nse,'retrieve',return_value=self.result),patch.object(f.time,'sleep'):
            result=f.pull(items,at=AT)
        self.assertEqual(result['counts'],dict(unsupported=1,failed=1,updated=1))
        self.assertEqual(len(result['stocks']),3)

    def test_bulk_continues_after_unexpected_stock_failure_without_logging_credentials(self):
        with patch.object(f,'pull_stock',side_effect=[OSError('private-header'),dict(symbol='TEST',isin=ITEM['isin'],status='updated')]),patch.object(f.time,'sleep'):
            result=f.pull([ITEM,ITEM])
        self.assertEqual(result['counts'],dict(failed=1,updated=1))
        self.assertTrue(result['partial'])
        self.assertNotIn('private-header',str(result))

    def test_coverage_distinguishes_comparative_filings_from_snapshot_quarters(self):
        self.docs[0].update(end='2026-06-30',filed_at='2026-07-09T18:36:20+05:30')
        self.docs[1].update(end='2025-06-30',filed_at='2025-07-09T18:36:20+05:30')
        self.pull()
        coverage=f.coverage([ITEM,dict(ITEM,isin='INE089C01029')])
        self.assertEqual(coverage['validated_symbols'],1)
        self.assertEqual(coverage['retained_snapshot_versions'],1)
        self.assertEqual(coverage['companies_with_multiple_snapshot_periods'],0)
        self.assertEqual(coverage['snapshot_periods'],{'2026-06-30':1})
        self.assertEqual(coverage['source_periods'],{'2025-06-30':1,'2026-06-30':1})
        from fastapi.testclient import TestClient
        from dashboard.api.main import app
        with TestClient(app) as client:
            response=client.get('/api/company/fundamentals-history')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['distinct_company_periods'],1)


if __name__=='__main__':unittest.main()

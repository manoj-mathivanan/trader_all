from datetime import date, datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.research import options_backtest as bt, options_extended as ext, options_history as history
from scripts.research_options_extended import BudgetTransport, completed_month
import httpx


def stamp(day, clock):
    return int(datetime.fromisoformat(day+'T'+clock+':00+05:30').timestamp()*1000)


class ExtendedTests(unittest.TestCase):
    def test_atomic_json_retries_transient_windows_sharing_failure(self):
        original=Path.replace
        attempts=[]
        def replace(source,destination):
            attempts.append(source)
            if len(attempts)<3:
                raise PermissionError('Windows sharing violation')
            return original(source,destination)
        with tempfile.TemporaryDirectory() as tmp,patch.object(Path,'replace',replace),patch.object(history.time,'sleep'):
            path=Path(tmp)/'state.json'
            path.write_text('{"old":true}')
            history.save_json(path,{'complete':True})
            self.assertEqual(json.loads(path.read_text()),{'complete':True})
            self.assertEqual(len(attempts),3)
            self.assertEqual(list(Path(tmp).glob('*.tmp')),[])

    def test_atomic_json_exhaustion_preserves_existing_state(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(Path,'replace',side_effect=PermissionError('locked')),patch.object(history.time,'sleep'):
            path=Path(tmp)/'state.json'
            path.write_text('{"old":true}')
            with self.assertRaises(PermissionError):
                history.save_json(path,{'complete':True})
            self.assertEqual(json.loads(path.read_text()),{'old':True})
            self.assertEqual(list(Path(tmp).glob('*.tmp')),[])

    def test_completed_month_requires_matching_source_manifests(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            history.save_json(p/'research-manifest.json',dict(status='research_downloaded',failures=[]))
            history.save_json(p/'underlying-manifest.json',dict(status='underlying_downloaded'))
            records=[dict(file=name,sha256=hashlib.sha256((p/name).read_bytes()).hexdigest()) for name in ('research-manifest.json','underlying-manifest.json')]
            history.save_json(p/'research-results.json',dict(status='diagnostic_research_only',source_manifests=records))
            self.assertTrue(completed_month(p))
            (p/'underlying-manifest.json').write_text('{}')
            self.assertFalse(completed_month(p))

    def test_thirty_minute_budget_waits_instead_of_sending_extra_requests(self):
        timer=[10001.0]
        sent=[]
        transport=httpx.MockTransport(lambda req:(sent.append(timer[0]) or httpx.Response(200)))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'times.json'
            history.save_json(path,[10000.0]*1800)
            with patch('scripts.research_options_extended.time.time',side_effect=lambda:timer[0]),patch('scripts.research_options_extended.time.sleep',side_effect=lambda seconds:timer.__setitem__(0,timer[0]+seconds)):
                with httpx.Client(transport=BudgetTransport(path,transport)) as client:
                    client.get('https://example.test/')
            self.assertGreaterEqual(sent[0],11801.0)
            self.assertEqual(len(json.loads(path.read_text())),1)

    def test_budget_counts_retries_and_restores_recent_requests(self):
        transport=httpx.MockTransport(lambda req:httpx.Response(200,json={'ok':True}))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'times.json'
            with httpx.Client(transport=BudgetTransport(path,transport)) as client:
                client.get('https://example.test/')
            self.assertEqual(len(json.loads(path.read_text())),1)
            restored=BudgetTransport(path,transport)
            self.assertEqual(len(restored.times),1)

    def test_full_month_underlying_is_split_into_provider_safe_chunks(self):
        calls=[]
        def handler(req):
            calls.append(req.url.path)
            day=req.url.path.split('/')[-2]
            return httpx.Response(200,json=dict(status='success',data=dict(candles=[
                [day+'T09:15:00+05:30',100,101,99,100,0]])))
        with tempfile.TemporaryDirectory() as tmp,httpx.Client(transport=httpx.MockTransport(handler)) as client:
            result=history.download_underlying(client,'secret',start=date(2026,4,1),end=date(2026,4,30),output=tmp)
            self.assertEqual(result['status'],'underlying_downloaded')
            minute_calls=[p for p in calls if '/minutes/' in p]
            self.assertEqual(len(minute_calls),2)
            for path in minute_calls:
                last,first=map(date.fromisoformat,path.split('/')[-2:])
                self.assertLessEqual((last-first).days,27)

    def test_continuous_cash_is_not_reset_at_month_boundary(self):
        months=['2026-04','2026-05']
        days=['2026-04-06','2026-05-04']
        expiries=['2026-04-07','2026-05-05']
        events=[]
        fixtures={}
        for index,(month,day,expiry) in enumerate(zip(months,days,expiries)):
            contract=dict(instrument_key=month,expiry=expiry,underlying_key=history.UNDERLYING,
                          instrument_type='CE',strike_price=25000,lot_size=100)
            fixtures['catalog-'+month]=[contract]
            fixtures['prices-'+month]=dict(raw_response=dict(data=dict(candles=[
                [day+'T09:59:00+05:30',900 if index==0 else 250,901 if index==0 else 251,899 if index==0 else 249,900 if index==0 else 250,100],
                [day+'T10:00:00+05:30',900 if index==0 else 250,901 if index==0 else 251,899 if index==0 else 249,900 if index==0 else 250,100],
                [day+'T10:03:00+05:30',10 if index==0 else 300,11 if index==0 else 301,9 if index==0 else 299,10 if index==0 else 300,100]])))
            for clock,enter,exit in [('10:00',True,False),('10:03',False,True),('10:06',False,False)]:
                events.append(dict(date=day,time=clock,timestamp=stamp(day,clock),ready=True,
                    call=enter,put=False,exit_call=exit,exit_put=False,entry_window=True,underlying_close=25000))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for month,day,expiry in zip(months,days,expiries):
                directory=root/month
                directory.mkdir()
                history.save_json(directory/'underlying-manifest.json',{})
                history.save_json(directory/'research-manifest.json',dict(status='research_downloaded',failures=[],
                    catalogs=[dict(expiry=expiry,file='catalog-'+month)],
                    files=[dict(instrument=fixtures['catalog-'+month][0],file='prices-'+month,start=day,end=day)]))
            audit=dict(events=events,excluded_sessions=[])
            with patch.object(bt,'load_underlying',return_value=({},[],[])),patch.object(bt,'read_evidence',side_effect=lambda directory,record:fixtures[record['file']]),patch.object(bt,'prepare_signals',return_value=audit):
                result=ext.compare_period(root,'test',months,date(2026,4,1),date(2026,5,31))
            value=result['replays']['3m_fixed_250_observed_public_10bps']
            self.assertEqual(len(value['trades']),1)
            self.assertTrue(any('Insufficient cash' in x['reason'] for x in value['skipped_entries']))
            self.assertFalse(result['monthly_cash_reset'])

    def test_conflicting_overlapping_candles_are_not_silently_overwritten(self):
        values={1:dict(timestamp=1,close=100)}
        with self.assertRaises(ValueError):
            ext.merge_unique(values,[dict(timestamp=1,close=200)],'timestamp')


if __name__ == '__main__':
    unittest.main()

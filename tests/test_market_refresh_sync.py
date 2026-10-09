from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from scripts.market_data_bundle import export
from scripts.sync_market_refresh import local, ready_refresh, identity


class RefreshSyncTests(unittest.TestCase):
    def test_delta_archives_fundamentals_and_filters_candle_window(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'data'
            (source / 'bars').mkdir(parents=True)
            (source / 'company/fundamentals').mkdir(parents=True)
            (source / 'run_data').mkdir()
            isin = 'INE001A01036'
            bar = dict(date='2026-10-08', open=100, high=101, low=99, close=100, volume=10)
            fetched = '2026-10-09T06:00:00+00:00'
            record = dict(instrument=dict(isin=isin, symbol='T', key='NSE_EQ|T'), fetched_at=fetched,
                          bars=[dict(bar, date='2020-01-01'), bar])
            (source / f'bars/{isin}.json').write_text(json.dumps(record))
            (source / f'company/fundamentals/{isin}.json').write_text(json.dumps({'last_checked_at': fetched}))
            (source / 'run_data/frozen.json').write_text('{}')
            refresh = dict(job_id='test', started_at=fetched, completed_at='2026-10-09T06:01:00+00:00',
                           daily_start='2025-10-08', minute_start='2026-09-29', partial=True)
            clock = datetime.fromisoformat(fetched).timestamp()
            for path in source.rglob('*.json'):
                os.utime(path, (clock, clock))
            result = export(source, Path(directory) / 'bundle', 'local', refresh=refresh)
            self.assertEqual(result['counts']['daily'], 1)
            self.assertEqual(result['refresh'], refresh)
            self.assertEqual(len(result['files']), 2)

    def test_running_refresh_is_not_queued_and_completed_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / 'market_fetch.json').write_text(json.dumps({'started_at': '2026-10-09T06:00:00+00:00'}))
            self.assertIsNone(ready_refresh(source))
            refresh = dict(job_id='test', started_at='2026-10-09T06:00:00+00:00',
                           completed_at='2026-10-09T06:01:00+00:00')
            (source / 'market_fetch.json').write_text(json.dumps(refresh))
            state = source / 'private/sync'
            state.mkdir(parents=True)
            (state / 'progress.json').write_text(json.dumps({'status': 'complete', 'token': identity(refresh, 'local')}))
            with patch('scripts.sync_market_refresh.bundle_for') as make_bundle:
                local(SimpleNamespace(source=source, state=state))
                make_bundle.assert_not_called()

    def test_failed_receipt_does_not_mark_queued_import_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / 'progress.json').write_text(json.dumps({'status': 'queued', 'token': 'local-abc'}))
            with patch('scripts.sync_market_refresh.ssh', return_value=SimpleNamespace(returncode=1)):
                local(SimpleNamespace(source=state, state=state))
            self.assertEqual(json.loads((state / 'progress.json').read_text())['status'], 'queued')


if __name__ == '__main__':
    unittest.main()

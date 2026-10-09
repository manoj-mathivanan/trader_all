"""Exercise real COPY, conflict retention, replay and rollback in a disposable DB."""
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import secrets
import tempfile

from psycopg import sql
from import_market_data import connect, run
from market_data_bundle import export


password = Path('/srv/market-data/private/admin_password')
schema = Path('/opt/market-data/schema.sql')
database = 'market_import_test_' + secrets.token_hex(5)
with connect(password) as admin:
    admin.autocommit = True
    admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
try:
    with tempfile.TemporaryDirectory(prefix='market-import-test-') as directory:
        root = Path(directory)
        instrument = {'isin': 'TESTISIN', 'symbol': 'TEST', 'key': 'NSE_EQ|TESTISIN'}
        instant = datetime(2026, 10, 8, 9, 15, tzinfo=timezone(timedelta(hours=5, minutes=30)))
        for version, price, fetched in [(1, 100, '2026-10-08T12:00:00+00:00'),
                                         (2, 101, '2026-10-08T13:00:00+00:00'),
                                         (3, 99, '2026-10-08T11:00:00+00:00')]:
            source = root / ('source' + str(version))
            bundle = root / ('bundle' + str(version))
            for name in ('bars', 'intraday/5m/TESTISIN'):
                (source / name).mkdir(parents=True)
            bar = dict(date='2026-10-08', open=price, high=price+2, low=price-2, close=price, volume=10)
            record = dict(instrument=instrument, fetched_at=fetched, bars=[bar])
            (source / 'bars/TESTISIN.json').write_text(json.dumps(record))
            minute = dict(bar, timestamp=int(instant.timestamp()*1000))
            (source / 'intraday/5m/TESTISIN/2026-10-08.json').write_text(json.dumps(dict(record, bars=[minute])))
            fundamentals = source / 'company/fundamentals/INE001A01036.json'
            fundamentals.parent.mkdir(parents=True)
            fundamentals.write_text(json.dumps({'last_checked_at': fetched, 'last_pulled_at': fetched,
                                                'snapshot': {'test_price': price}}))
            export(source, bundle, 'local')
            manifest_path = bundle / 'manifest.json'
            manifest = json.loads(manifest_path.read_text())
            manifest['refresh'] = {'job_id': 'refresh-' + str(version), 'started_at': fetched,
                                   'completed_at': fetched, 'partial': version == 3}
            manifest_path.write_text(json.dumps(manifest))
            result = run(bundle, password, schema, None, database)
            assert result['source_candles'] == {'daily': 1, 'five_minute': 1}
            assert result['unmatched_candles'] == 0
            if version == 2:
                assert run(bundle, password, schema, None, database) == result
        with connect(password, database) as conn:
            assert conn.execute('SELECT count(*) FROM market.candles').fetchone()[0] == 2
            assert conn.execute('SELECT DISTINCT close FROM market.candles').fetchall() == [(101,)]
            assert conn.execute('SELECT count(*) FROM market.candle_revisions').fetchone()[0] == 6
            assert conn.execute('SELECT count(*) FROM market.source_files').fetchone()[0] == 9
            assert conn.execute('SELECT count(*) FROM market.refreshes').fetchone()[0] == 3
            assert conn.execute("SELECT record->'snapshot'->>'test_price' FROM market.fundamentals").fetchone()[0] == '101'
            before = conn.execute('SELECT count(*) FROM market.candles').fetchone()[0]
        # Corrupt the expected count only; imported CSV still has valid checksum.
        manifest_path = bundle / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['counts']['daily'] = 2
        manifest_path.write_text(json.dumps(manifest))
        try:
            run(bundle, password, schema, None, database)
        except ValueError as exc:
            assert 'counts' in str(exc)
        else:
            raise AssertionError('Corrupt manifest was accepted')
        with connect(password, database) as conn:
            assert conn.execute('SELECT count(*) FROM market.candles').fetchone()[0] == before
    print('PASS: COPY, exact values, newer/older conflicts, refresh timestamps, fundamentals, replay and rollback.')
finally:
    with connect(password) as admin:
        admin.autocommit = True
        admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(database)))

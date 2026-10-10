"""Exercise the real importer SQL on temporary PostgreSQL tables only."""
import json
from pathlib import Path
from import_market_data import connect, merge_candles, save_fundamental


class TemporaryTables:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, query, *args):
        for name in ('candle_revisions', 'candles', 'fundamentals'):
            query = query.replace('market.' + name, 'test_' + name)
        return self.conn.execute(query, *args)


with connect(Path('/srv/market-data/private/admin_password')) as conn:
    conn.execute('CREATE TEMP TABLE test_candles (LIKE market.candles INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING INDEXES)')
    conn.execute('CREATE TEMP TABLE test_candle_revisions (LIKE market.candle_revisions INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING INDEXES)')
    conn.execute('CREATE TEMP TABLE test_fundamentals (LIKE market.fundamentals INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING INDEXES)')
    conn.execute('CREATE TEMP TABLE stage (LIKE test_candles INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING INDEXES)')
    reader = TemporaryTables(conn)
    base = ('TEST', 1440, 1, '2026-10-08', 100, 105, 99, 101, 10, 'a'*64, '2026-10-08T12:00:00+00:00', 'test-original')
    conn.execute('INSERT INTO test_candles VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)', base)
    original = conn.execute('SELECT ctid,fetched_at,import_id FROM test_candles WHERE timestamp_ms=1').fetchone()
    newer = list(base)
    newer[-2:] = ['2026-10-09T12:00:00+00:00', 'test-refresh']
    conn.execute('INSERT INTO stage VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)', newer)
    missing = list(newer)
    missing[2:4] = [2, '2026-10-09']
    missing[9] = 'b'*64
    conn.execute('INSERT INTO stage VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)', missing)
    first = merge_candles(reader)
    assert first['inserted_candles'] == 1 and first['updated_candles'] == 0, first
    assert conn.execute('SELECT ctid,fetched_at,import_id FROM test_candles WHERE timestamp_ms=1').fetchone() == original
    before = conn.execute('SELECT timestamp_ms,ctid FROM test_candles ORDER BY timestamp_ms').fetchall()
    repeat = merge_candles(reader)
    assert repeat['inserted_candles'] == repeat['updated_candles'] == 0, repeat
    assert conn.execute('SELECT timestamp_ms,ctid FROM test_candles ORDER BY timestamp_ms').fetchall() == before
    conn.execute("UPDATE stage SET close=102,sha256=%s WHERE timestamp_ms=1", ('c'*64,))
    correction = merge_candles(reader)
    assert correction['updated_candles'] == 1, correction
    assert conn.execute('SELECT count(*) FROM test_candle_revisions').fetchone()[0] == 2
    conn.execute("UPDATE stage SET close=103,sha256=%s,fetched_at='2026-10-07T12:00:00+00:00' WHERE timestamp_ms=1", ('d'*64,))
    older = merge_candles(reader)
    assert older['updated_candles'] == 0, older
    assert conn.execute('SELECT close FROM test_candles WHERE timestamp_ms=1').fetchone()[0] == 102
    record = dict(last_checked_at='2026-10-09T12:00:00+00:00')
    raw = json.dumps(record).encode()
    path = 'company/fundamentals/INE467B01029.json'
    save_fundamental(reader, path, 'a'*64, 'test-original', raw)
    original_fundamental = conn.execute('SELECT ctid FROM test_fundamentals').fetchone()
    save_fundamental(reader, path, 'a'*64, 'test-refresh', raw)
    assert conn.execute('SELECT ctid FROM test_fundamentals').fetchone() == original_fundamental
    record['last_checked_at'] = '2026-10-10T12:00:00+00:00'
    save_fundamental(reader, path, 'b'*64, 'test-new-check', json.dumps(record).encode())
    assert conn.execute('SELECT import_id FROM test_fundamentals').fetchone()[0] == 'test-new-check'
    conn.rollback()
    print(json.dumps(dict(status='passed', missing_inserted=True, unchanged_rows_untouched=True,
                          repeat_import_no_writes=True, changed_versions_preserved=True,
                          older_versions_do_not_replace_newer=True, unchanged_fundamentals_untouched=True)))

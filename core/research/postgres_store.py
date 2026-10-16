"""PostgreSQL persistence, content-addressed snapshots and queryable accounting.

No operation falls back to JSON. Existing document contracts are preserved while
market candles, run settings, portfolios, jobs and trade records have SQL indexes.
"""
from contextlib import contextmanager
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
from threading import RLock
from functools import wraps
import time

import psycopg
from psycopg.types.json import Jsonb

_lock = RLock()
_conn = None
_identity = None


def session(function):
    """One bounded connection per process; hold it for the whole transaction.

    Serializing DB operations also prevents two request threads from accidentally
    sharing a transaction. Long-running runner locks use a separate session.
    """
    @wraps(function)
    def wrapped(*args, **kwargs):
        with _lock:
            return function(*args, **kwargs)
    return wrapped


def namespace():
    value = os.environ.get('TRADER_DB_NAMESPACE', os.environ.get('TRADER_ENV', 'local'))
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', value):
        raise ValueError('Invalid database namespace.')
    return value


def dsn():
    value = os.environ.get('TRADER_DB_DSN')
    if not value and os.environ.get('TRADER_DB_DSN_FILE'):
        value = Path(os.environ['TRADER_DB_DSN_FILE']).read_text().strip()
    if not value:
        raise ValueError('PostgreSQL storage requires TRADER_DB_DSN or TRADER_DB_DSN_FILE.')
    return value


def connection():
    global _conn, _identity
    identity = (dsn(), os.getpid())
    if _identity != identity or _conn is None or _conn.closed:
        if _conn is not None:
            _conn.close()
        try:
            _conn = psycopg.connect(identity[0], autocommit=True, connect_timeout=10,
                                   options='-c statement_timeout=120000 -c lock_timeout=15000',
                                   application_name='trader-application')
        except psycopg.Error:
            raise ValueError('Database storage unavailable. No filesystem fallback was used.') from None
        _identity = identity
    return _conn


@session
def close():
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


@session
def initialize():
    with connection().transaction():
        connection().execute(Path(__file__).with_name('postgres_schema.sql').read_text())


def lock_id(name):
    return int.from_bytes(hashlib.sha256((namespace()+':'+name).encode()).digest()[:8], 'big', signed=True)


@contextmanager
def transaction():
    with _lock:
        conn = connection()
        with conn.transaction():
            conn.execute('SELECT pg_advisory_xact_lock(%s)', (lock_id('document-write'),))
            yield conn


@contextmanager
def mutex(name, timeout=5):
    # A dedicated session holds the lock while a long-running runner continues
    # committing short accounting transactions on its normal connection.
    conn = psycopg.connect(dsn(), autocommit=True, connect_timeout=10)
    deadline = time.monotonic()+timeout
    try:
        while not conn.execute('SELECT pg_try_advisory_lock(%s)', (lock_id(name),)).fetchone()[0]:
            if time.monotonic() >= deadline:
                raise ValueError('Database process lock is busy.')
            time.sleep(.02)
        yield
    finally:
        conn.close()


def pack(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode()


def put_content(raw):
    digest = hashlib.sha256(raw).hexdigest()
    connection().execute('INSERT INTO trader.contents(sha256,content,raw_bytes) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',
                         (digest, gzip.compress(raw, compresslevel=6, mtime=0), len(raw)))
    return digest


def unpack(raw, digest):
    value = gzip.decompress(bytes(raw))
    if hashlib.sha256(value).hexdigest() != digest:
        raise ValueError('Database content checksum mismatch.')
    return value


@session
def read(name, default=None):
    row = connection().execute('SELECT c.content,d.sha256 FROM trader.documents d JOIN trader.contents c USING(sha256) WHERE d.namespace=%s AND d.name=%s',
                               (namespace(), name)).fetchone()
    return json.loads(unpack(*row)) if row else default


def metadata(name, value):
    if not isinstance(value, dict):
        return {}
    # Keep large frozen datasets compressed; metadata remains cheap to query.
    if name.startswith(('run_data/', 'run_intraday/', 'run_fundamentals/')):
        return {'snapshot': True}
    fields = ('id','name','strategy_id','status','as_of','isin','symbol','published_at',
              'recorded_at','pull_status','period_end','title','url','company','requested_start','requested_end')
    return {key: value[key] for key in fields if key in value}


def write(name, value):
    raw = pack(value)
    digest = hashlib.sha256(raw).hexdigest()
    previous = connection().execute('SELECT sha256 FROM trader.documents WHERE namespace=%s AND name=%s', (namespace(), name)).fetchone()
    if previous and previous[0] == digest:
        return
    if previous and name.startswith(('run_data/', 'run_intraday/', 'run_fundamentals/')):
        raise ValueError('Frozen backtest inputs are immutable. Create a new run instead.')
    put_content(raw)
    connection().execute('INSERT INTO trader.documents(namespace,name,sha256,metadata) VALUES (%s,%s,%s,%s) '
                         'ON CONFLICT(namespace,name) DO UPDATE SET sha256=EXCLUDED.sha256,metadata=EXCLUDED.metadata,revision=trader.documents.revision+1,updated_at=now()',
                         (namespace(), name, digest, Jsonb(metadata(name, value))))
    project(name, value, digest)
    if previous:
        discard_unreferenced(previous[0])


def discard_unreferenced(digest):
    # Mutable job logs and ledgers must not leave a full abandoned blob on every
    # update. Frozen runs and any other referencing document retain their bytes.
    connection().execute('DELETE FROM trader.contents c WHERE c.sha256=%s '
                         'AND NOT EXISTS (SELECT 1 FROM trader.documents d WHERE d.sha256=c.sha256) '
                         'AND NOT EXISTS (SELECT 1 FROM trader.artifacts a WHERE a.sha256=c.sha256) '
                         'AND NOT EXISTS (SELECT 1 FROM trader.intraday_sessions s WHERE s.source_sha256=c.sha256) '
                         'AND NOT EXISTS (SELECT 1 FROM trader.runs r WHERE r.source_sha256=c.sha256) '
                         'AND NOT EXISTS (SELECT 1 FROM trader.portfolios p WHERE p.source_sha256=c.sha256)',(digest,))


def project(name, value, digest):
    conn, ns = connection(), namespace()
    if isinstance(value, dict) and name.startswith('intraday/') and isinstance(value.get('bars'),list):
        project_intraday(name,value,digest)
    if isinstance(value, dict) and name.startswith('bars/') and isinstance(value.get('bars'), list):
        parts = name.split('/')
        isin, interval = parts[1], 1440
        conn.execute('DELETE FROM trader.candles WHERE namespace=%s AND document_name=%s', (ns, name))
        with conn.cursor().copy('COPY trader.candles(namespace,document_name,ordinal,isin,interval_minutes,session,open,high,low,close,volume,bar) FROM STDIN') as copy:
            for ordinal, bar in enumerate(value['bars']):
                copy.write_row((ns, name, ordinal, isin, interval, bar['date'], *[bar[k] for k in ('open','high','low','close','volume')], Jsonb(bar)))
    if isinstance(value, dict) and name.startswith('runs/'):
        conn.execute('INSERT INTO trader.runs VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(namespace,id) DO UPDATE SET strategy_id=EXCLUDED.strategy_id,config=EXCLUDED.config,metrics=EXCLUDED.metrics,source_sha256=EXCLUDED.source_sha256',
                     (ns, name[5:], value.get('strategy_id','swing_patterns'), Jsonb(value.get('config',{})), Jsonb(value.get('metrics',{})), digest))
        project_trades('backtest', name[5:], value.get('trades',[]))
    if isinstance(value, dict) and name.startswith(('portfolios/', 'portfolio_scenarios/')):
        identity, ledger = value.get('id',name.rsplit('/',1)[-1]), value.get('ledger', {})
        conn.execute('INSERT INTO trader.portfolios VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(namespace,id) DO UPDATE SET config=EXCLUDED.config,status=EXCLUDED.status,cash=EXCLUDED.cash,last_session=EXCLUDED.last_session,source_sha256=EXCLUDED.source_sha256',
                     (ns, identity, value.get('strategy_name',identity), Jsonb(value.get('config',{})), value.get('status','active'), ledger.get('cash'), ledger.get('last_session'), digest))
        for kind in ('trades','orders','positions'):
            rows = ledger.get(kind, [])
            if isinstance(rows, dict):
                rows = [dict(position, symbol=symbol) for symbol, position in rows.items()]
            project_trades('paper_'+kind, identity, rows)
    if name=='jobs' and isinstance(value,list):
        conn.execute('DELETE FROM trader.jobs WHERE namespace=%s', (ns,))
        with conn.cursor().copy('COPY trader.jobs(namespace,id,status,record) FROM STDIN') as copy:
            for job in value:
                copy.write_row((ns,job['id'],job['status'],Jsonb(job)))


def project_trades(kind, identity, rows):
    conn, ns = connection(), namespace()
    conn.execute('DELETE FROM trader.trade_records WHERE namespace=%s AND owner_kind=%s AND owner_id=%s', (ns,kind,identity))
    with conn.cursor().copy('COPY trader.trade_records(namespace,owner_kind,owner_id,ordinal,symbol,pnl,record) FROM STDIN') as copy:
        for index, record in enumerate(rows):
            copy.write_row((ns,kind,identity,index,record.get('symbol'),record.get('pnl'),Jsonb(record)))


def project_intraday(name, value, digest):
    parts=name.split('/')
    if len(parts)!=4 or not parts[1].endswith('m'):
        raise ValueError('Invalid intraday session key.')
    connection().execute('INSERT INTO trader.intraday_sessions(namespace,document_name,isin,interval_minutes,session,bars,source_sha256) VALUES (%s,%s,%s,%s,%s,%s,%s) '
                         'ON CONFLICT(namespace,document_name) DO UPDATE SET bars=EXCLUDED.bars,source_sha256=EXCLUDED.source_sha256',
                         (namespace(),name,parts[2],int(parts[1][:-1]),parts[3],Jsonb(value['bars']),digest))


@session
def keys(prefix='', recursive=False):
    escaped = prefix.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
    rows = connection().execute('SELECT name FROM trader.documents WHERE namespace=%s AND name LIKE %s ORDER BY name', (namespace(),escaped+'%')).fetchall()
    return [row[0] for row in rows if recursive or '/' not in row[0][len(prefix):]]


@session
def version(name):
    row = connection().execute('SELECT revision FROM trader.documents WHERE namespace=%s AND name=%s', (namespace(),name)).fetchone()
    return ('postgres', hashlib.sha256(dsn().encode()).hexdigest(), namespace(), row[0]) if row else None


@session
def read_bytes(name):
    row = connection().execute('SELECT c.content,a.sha256 FROM trader.artifacts a JOIN trader.contents c USING(sha256) WHERE a.namespace=%s AND a.name=%s', (namespace(),name)).fetchone()
    if not row:
        raise FileNotFoundError(name)
    return unpack(*row)


def write_bytes(name, raw):
    previous=connection().execute('SELECT sha256 FROM trader.artifacts WHERE namespace=%s AND name=%s',(namespace(),name)).fetchone()
    digest = put_content(bytes(raw))
    connection().execute('INSERT INTO trader.artifacts VALUES (%s,%s,%s) ON CONFLICT(namespace,name) DO UPDATE SET sha256=EXCLUDED.sha256', (namespace(),name,digest))
    if previous and previous[0]!=digest:
        discard_unreferenced(previous[0])


@session
def token_saved(owner):
    return bool(connection().execute('SELECT 1 FROM trader.credentials WHERE namespace=%s AND owner_id=%s AND provider=%s',(namespace(),owner,'upstox')).fetchone())


def save_token(owner, encrypted):
    connection().execute('INSERT INTO trader.credentials(namespace,owner_id,provider,encrypted_value) VALUES (%s,%s,%s,%s) ON CONFLICT(namespace,owner_id,provider) DO UPDATE SET encrypted_value=EXCLUDED.encrypted_value,updated_at=now()', (namespace(),owner,'upstox',encrypted))


@session
def token(owner):
    row = connection().execute('SELECT encrypted_value FROM trader.credentials WHERE namespace=%s AND owner_id=%s AND provider=%s',(namespace(),owner,'upstox')).fetchone()
    return bytes(row[0]) if row else None


@session
def read_many(names):
    rows = connection().execute('SELECT d.name,c.content,d.sha256 FROM trader.documents d JOIN trader.contents c USING(sha256) WHERE d.namespace=%s AND d.name=ANY(%s)',
                                 (namespace(),list(names))).fetchall()
    return {name:json.loads(unpack(content,digest)) for name,content,digest in rows}


@session
def available_window(items, warmup):
    """Compact SQL coverage: don't transfer or decode every candle for a form."""
    names = ['bars/'+item['isin'] for item in items]
    rows = connection().execute('SELECT d.name,d.metadata,count(c.ordinal),min(c.session),max(c.session),min(c.session) FILTER (WHERE c.ordinal=%s) '
                                'FROM trader.documents d LEFT JOIN trader.candles c ON c.namespace=d.namespace AND c.document_name=d.name '
                                'WHERE d.namespace=%s AND d.name=ANY(%s) GROUP BY d.name,d.metadata',
                                (warmup+1,namespace(),names)).fetchall()
    summaries={row[0]:row for row in rows}
    loaded=[r for r in rows if r[2]]
    ready=[r for r in loaded if r[2]>warmup+2]
    result=dict(start=None,end=None,warmup_sessions=warmup+1,ready_symbols=len(ready),total_symbols=len(items),
                history_start=min((r[3] for r in loaded),default=None),history_end=max((r[4] for r in loaded),default=None),
                missing_symbols=[item['symbol'] for item in items if not summaries.get('bars/'+item['isin'],[None,None,0])[2]])
    if ready:
        start=max(max(r[5],r[1].get('requested_start') or r[3]) for r in ready)
        end=min(min(r[4],r[1].get('requested_end') or r[4]) for r in ready)
        if start<end:result.update(start=start,end=end)
    return result

"""Create a read-only research login; keep its password in a root-only file."""
import os
from pathlib import Path
import secrets

import psycopg
from psycopg import sql


private = Path('/srv/market-data/private')
password_path = private / 'reader_password'
if not password_path.exists():
    descriptor = os.open(password_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write(secrets.token_urlsafe(40) + '\n')
password_path.chmod(0o600)
with psycopg.connect(host='127.0.0.1', dbname='market_data', user='market_admin',
                     password=(private / 'admin_password').read_text().strip()) as conn:
    if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname='market_research'").fetchone():
        conn.execute('CREATE ROLE market_research LOGIN IN ROLE market_reader')
    conn.execute(sql.SQL('ALTER ROLE market_research PASSWORD {}').format(sql.Literal(password_path.read_text().strip())))
    conn.execute('ALTER ROLE market_research SET default_transaction_read_only=on')
    conn.execute("ALTER ROLE market_research SET statement_timeout='120s'")
with psycopg.connect(host='127.0.0.1', dbname='market_data', user='market_research',
                     password=password_path.read_text().strip()) as conn:
    conn.execute('SELECT count(*) FROM market.instruments').fetchone()
    if conn.execute("SELECT has_table_privilege(current_user, 'market.candles', 'INSERT,UPDATE,DELETE,TRUNCATE')").fetchone()[0]:
        raise RuntimeError('Reader unexpectedly has write privileges')
    try:
        conn.execute('DELETE FROM market.instruments WHERE false')
    except (psycopg.errors.ReadOnlySqlTransaction, psycopg.errors.InsufficientPrivilege):
        conn.rollback()
    else:
        raise RuntimeError('Reader unexpectedly has write access')
print('Read-only research login verified; password stored in private/reader_password.')

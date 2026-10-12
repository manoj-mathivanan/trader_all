"""Provision an append-only investor archive connection without exposing credentials."""
import os
from pathlib import Path
import secrets
from urllib.parse import quote
import psycopg
from psycopg import sql

private=Path('/srv/market-data/private')
path=private/'investor_app_password'
if not path.exists():
    with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as f:f.write(secrets.token_urlsafe(40))
path.chmod(0o600)
password=path.read_text().strip()
with psycopg.connect(host='127.0.0.1',dbname='market_data',user='market_admin',password=(private/'admin_password').read_text().strip()) as conn:
    if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname='investor_app'").fetchone():conn.execute('CREATE ROLE investor_app LOGIN')
    conn.execute(sql.SQL('ALTER ROLE investor_app PASSWORD {}').format(sql.Literal(password)))
    conn.execute('GRANT CONNECT ON DATABASE market_data TO investor_app')
    conn.execute('GRANT USAGE ON SCHEMA investor TO investor_app')
    conn.execute('GRANT SELECT,INSERT ON ALL TABLES IN SCHEMA investor TO investor_app')
    conn.execute("ALTER ROLE investor_app SET statement_timeout='60s'")
    if conn.execute("SELECT has_table_privilege('investor_app','market.candles','INSERT,UPDATE,DELETE,TRUNCATE')").fetchone()[0]:raise ValueError('Archive role has unexpected market-data permissions')
    if conn.execute("SELECT has_table_privilege('investor_app','investor.documents','UPDATE,DELETE,TRUNCATE')").fetchone()[0]:raise ValueError('Archive role must be append-only')
with psycopg.connect(host='127.0.0.1',dbname='market_data',user='investor_app',password=password) as conn:
    conn.execute('SELECT count(*) FROM investor.documents').fetchone()
env=Path('/srv/trader/private/investor-openai.env')
lines=[line for line in env.read_text().splitlines() if not line.startswith('TRADER_INVESTOR_DB_DSN=')]
dsn='postgresql://investor_app:'+quote(password,safe='')+'@127.0.0.1:5432/market_data'
pending=env.with_suffix('.pending')
with os.fdopen(os.open(pending,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600),'w') as f:f.write('\n'.join(lines+['TRADER_INVESTOR_DB_DSN='+dsn])+'\n')
pending.replace(env);env.chmod(0o600)
print('Investor database role verified and private production connection configured.')

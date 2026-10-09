"""Populate queryable fundamentals from the existing verified source archives."""
import gzip
from pathlib import Path
from import_market_data import connect, save_fundamental

with connect(Path('/srv/market-data/private/admin_password')) as conn:
    conn.execute(Path('/opt/market-data/schema.sql').read_text())
    with conn.cursor(name='fundamental_backfill') as cursor:
        cursor.itersize = 1
        cursor.execute("SELECT s.relative_path,s.sha256,s.import_id,b.gzip_data FROM market.source_files s "
                       "JOIN market.imports i ON i.id=s.import_id JOIN market.blobs b ON b.sha256=s.sha256 "
                       "WHERE i.status='complete' AND s.relative_path ~ '^company/fundamentals/IN[A-Z0-9]{10}[.]json$'")
        for path, sha, import_id, compressed in cursor:
            save_fundamental(conn, path, sha, import_id, gzip.decompress(compressed))
    print({'fundamentals': conn.execute('SELECT count(*) FROM market.fundamentals').fetchone()[0]})

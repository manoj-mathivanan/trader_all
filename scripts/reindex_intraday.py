"""Backfill bounded intraday JSONB sessions from verified database documents."""
import json
from core.research import postgres_store as pg,store


def run(log=print):
    pg.initialize()
    conn,ns=pg.connection(),pg.namespace()
    with pg.mutex('intraday-reindex',timeout=0):
        names=[r[0] for r in conn.execute("SELECT d.name FROM trader.documents d LEFT JOIN trader.intraday_sessions s ON s.namespace=d.namespace AND s.document_name=d.name WHERE d.namespace=%s AND d.name LIKE 'intraday/%%' AND (s.document_name IS NULL OR s.source_sha256<>d.sha256) ORDER BY d.name",(ns,))]
        for start in range(0,len(names),64):
            with pg.transaction():
                rows=conn.execute('SELECT d.name,d.sha256,c.content FROM trader.documents d JOIN trader.contents c USING(sha256) WHERE d.namespace=%s AND d.name=ANY(%s)',(ns,names[start:start+64])).fetchall()
                for name,digest,content in rows:
                    value=json.loads(pg.unpack(content,digest))
                    if not isinstance(value,dict) or not isinstance(value.get('bars'),list):
                        raise ValueError('An intraday document does not contain a candle array: '+name)
                    pg.project_intraday(name,value,digest)
            if start%1024==0:log(f'Indexed {min(start+64,len(names))}/{len(names)} intraday sessions.',flush=True)
        with pg.transaction():
            missing=conn.execute("SELECT count(*) FROM trader.documents d LEFT JOIN trader.intraday_sessions s ON s.namespace=d.namespace AND s.document_name=d.name WHERE d.namespace=%s AND d.name LIKE 'intraday/%%' AND (s.document_name IS NULL OR s.source_sha256<>d.sha256)",(ns,)).fetchone()[0]
            if missing:raise ValueError('Intraday session projection is incomplete.')
            sessions,candles=conn.execute('SELECT count(*),coalesce(sum(candle_count),0) FROM trader.intraday_sessions WHERE namespace=%s',(ns,)).fetchone()
            # Only redundant indexes are removed. Canonical document bytes and
            # the complete native JSONB candle arrays remain unchanged.
            conn.execute('DELETE FROM trader.candles WHERE namespace=%s AND interval_minutes<>1440',(ns,))
            receipt=dict(status='verified',sessions=sessions,candles=int(candles),at=store.now())
            pg.write('storage/intraday_projection',receipt)
        log(json.dumps(receipt),flush=True)
        return receipt


if __name__=='__main__':
    try:run()
    finally:pg.close()

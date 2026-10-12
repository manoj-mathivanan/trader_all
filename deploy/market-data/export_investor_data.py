"""Read shared investor history without changing either environment's working state."""
import hashlib
import json
from pathlib import Path
import sys

KINDS={'refreshes','reviews','llm_responses','feed_responses','news','article_documents','article_summaries',
       'scans','monitor_runs','alerts','article_coverage','watchlist','settings','rules','portfolio_snapshot',
       'scan','monitor','discovery','execution','stock_details','assessments','latest','full_articles',
       'analysis_jobs','validation_reports','article_versions'}

def run(query, dsn=None):
    import psycopg
    environment=query.get('environment','local')
    if environment not in ('local','production'):raise ValueError('Unknown analysis environment')
    operation=query.get('operation','inventory')
    if operation not in ('inventory','list','document'):raise ValueError('Unknown archive operation')
    kind=query.get('kind','monitor_runs')
    if kind not in KINDS:raise ValueError('Unknown archive kind')
    connection=dict(connect_timeout=10,application_name='investor-history-reader')
    if not dsn:connection.update(host='127.0.0.1',dbname='market_data',user='market_admin',password=Path('/srv/market-data/private/admin_password').read_text().strip())
    with psycopg.connect(dsn or '',**connection) as conn:
        conn.execute('SET TRANSACTION READ ONLY')
        conn.execute("SET LOCAL statement_timeout='15s'")
        if operation=='inventory':
            counts=dict(conn.execute("SELECT kind,count(*) FROM investor.documents WHERE environment=%s GROUP BY kind UNION ALL SELECT 'article_versions',count(*) FROM investor.article_versions WHERE environment=%s",(environment,environment)).fetchall())
            receipt=conn.execute('SELECT result,synced_at FROM investor.sync_receipts WHERE environment=%s ORDER BY synced_at DESC LIMIT 1',(environment,)).fetchone()
            return dict(environment=environment,counts=counts,last_sync=receipt[1].isoformat() if receipt else None)
        table='investor.article_versions' if kind=='article_versions' else 'investor.documents'
        identity='article_id' if kind=='article_versions' else 'document_id'
        where='environment=%s';args=[environment]
        if kind!='article_versions':where+=' AND kind=%s';args.append(kind)
        if operation=='list':
            limit=max(1,min(int(query.get('limit',50)),100));offset=max(0,int(query.get('offset',0)))
            rows=conn.execute(f'SELECT {identity},sha256,archived_at,record->>\'as_of\',record->\'company\' FROM {table} WHERE {where} ORDER BY archived_at DESC,{identity},sha256 LIMIT %s OFFSET %s',(*args,limit,offset)).fetchall()
            return dict(environment=environment,kind=kind,offset=offset,limit=limit,documents=[dict(id=r[0],sha256=r[1],archived_at=r[2].isoformat(),as_of=r[3],company=r[4]) for r in rows])
        document_id=query.get('id')
        if not isinstance(document_id,str) or not 1<=len(document_id)<=200:raise ValueError('Invalid archive identity')
        where+=f' AND {identity}=%s';args.append(document_id)
        if query.get('sha256'):where+=' AND sha256=%s';args.append(query['sha256'])
        row=conn.execute(f'SELECT sha256,record FROM {table} WHERE {where} ORDER BY archived_at DESC,sha256 LIMIT 1',args).fetchone()
        if not row:raise ValueError('Archived document not found')
        if hashlib.sha256(json.dumps(row[1],sort_keys=True).encode()).hexdigest()!=row[0]:raise ValueError('Archived document integrity check failed')
        return dict(environment=environment,kind=kind,id=document_id,sha256=row[0],record=row[1])

if __name__=='__main__':
    print(json.dumps(run(json.loads(sys.stdin.buffer.read(10001)))))

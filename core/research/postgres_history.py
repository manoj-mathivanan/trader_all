"""Investor history queries against the application's authoritative database."""
import hashlib
import os
from core.research import postgres_store as pg

KINDS=frozenset(('refreshes','reviews','llm_responses','feed_responses','news','article_documents',
    'article_summaries','scans','monitor_runs','alerts','article_coverage','watchlist','settings',
    'rules','portfolio_snapshot','scan','monitor','discovery','execution','stock_details',
    'assessments','latest','full_articles','analysis_jobs','validation_reports','article_versions'))


@pg.session
def read(query):
    environment=os.environ.get('TRADER_ENV','local')
    if query.get('environment','local')!=environment:
        raise ValueError('This database contains a different environment.')
    operation=query.get('operation','inventory')
    kind=query.get('kind','monitor_runs')
    if operation not in ('inventory','list','document','recent_articles') or kind not in KINDS:
        raise ValueError('Unknown database history operation or kind.')
    conn,ns=pg.connection(),pg.namespace()
    if operation=='inventory':
        rows=conn.execute("SELECT split_part(name,'/',2),count(*) FROM trader.documents WHERE namespace=%s AND name LIKE 'investor/%%' GROUP BY 1",(ns,)).fetchall()
        counts={('article_versions' if k=='articles' else k):n for k,n in rows}
        counts['analysis_jobs']=conn.execute("SELECT count(*) FROM trader.jobs WHERE namespace=%s AND (record->>'type' LIKE 'Investor %%' OR record->>'type' LIKE 'Early breakout%%')",(ns,)).fetchone()[0]
        last=conn.execute("SELECT max(updated_at) FROM trader.documents WHERE namespace=%s AND name LIKE 'investor/%%'",(ns,)).fetchone()[0]
        return dict(environment=environment,counts=counts,last_sync=last.isoformat() if last else None,storage='postgres')
    if operation=='recent_articles':
        offset=max(0,int(query.get('offset',0)))
        rows=conn.execute("SELECT DISTINCT ON (d.metadata->>'id') c.content,d.sha256 FROM trader.documents d JOIN trader.contents c USING(sha256) WHERE d.namespace=%s AND d.name LIKE 'investor/articles/%%' AND (d.metadata->>'published_at')::timestamptz BETWEEN now()-interval '30 days' AND now() ORDER BY d.metadata->>'id',d.updated_at DESC,d.sha256 LIMIT 501 OFFSET %s",(ns,offset)).fetchall()
        import json
        return dict(environment=environment,articles=[json.loads(pg.unpack(*row)) for row in rows[:500]],
                    next_offset=offset+500 if len(rows)>500 else None)
    limit=max(1,min(int(query.get('limit',50)),100));offset=max(0,int(query.get('offset',0)))
    if kind=='analysis_jobs':
        records=conn.execute("SELECT record FROM trader.jobs WHERE namespace=%s AND (record->>'type' LIKE 'Investor %%' OR record->>'type' LIKE 'Early breakout%%') ORDER BY record->>'created_at' DESC",(ns,)).fetchall()
        values=[dict(id=r[0]['id'],sha256=hashlib.sha256(pg.pack(r[0])).hexdigest(),record=r[0]) for r in records]
        if operation=='list':
            return dict(environment=environment,kind=kind,offset=offset,limit=limit,documents=[dict(id=r['id'],sha256=r['sha256'],archived_at=r['record'].get('updated_at',r['record'].get('created_at')),as_of=None,company=None) for r in values[offset:offset+limit]])
        row=next((r for r in values if r['id']==query.get('id') and (not query.get('sha256') or r['sha256']==query['sha256'])),None)
        if not row:raise ValueError('Database history document not found.')
        return dict(environment=environment,kind=kind,**row)
    prefix='investor/'+('articles' if kind=='article_versions' else kind)
    where='d.namespace=%s AND (d.name=%s OR starts_with(d.name,%s))'
    args=[ns,prefix,prefix+'/']
    identity="d.metadata->>'id'" if kind=='article_versions' else "regexp_replace(d.name,'^.*/','')"
    if operation=='list':
        rows=conn.execute(f'SELECT {identity},d.sha256,d.updated_at,d.metadata FROM trader.documents d WHERE {where} ORDER BY d.updated_at DESC,d.name,d.sha256 LIMIT %s OFFSET %s',(*args,limit,offset)).fetchall()
        return dict(environment=environment,kind=kind,offset=offset,limit=limit,documents=[dict(id=r[0],sha256=r[1],archived_at=r[2].isoformat(),as_of=r[3].get('as_of'),company=r[3].get('company')) for r in rows])
    document_id=query.get('id')
    if not isinstance(document_id,str) or not 1<=len(document_id)<=200:
        raise ValueError('Invalid database history identity.')
    where+=f' AND {identity}=%s';args.append(document_id)
    if query.get('sha256'):where+=' AND d.sha256=%s';args.append(query['sha256'])
    row=conn.execute(f'SELECT c.content,d.sha256 FROM trader.documents d JOIN trader.contents c USING(sha256) WHERE {where} ORDER BY d.updated_at DESC,d.sha256 LIMIT 1',args).fetchone()
    if not row:raise ValueError('Database history document not found.')
    import json
    return dict(environment=environment,kind=kind,id=document_id,sha256=row[1],record=json.loads(pg.unpack(*row)))

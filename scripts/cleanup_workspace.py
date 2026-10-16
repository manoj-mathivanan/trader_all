"""Recoverable cleanup of completed backtests and paper-only workspace state."""
import argparse
import gzip
import json
import tarfile
from uuid import uuid4
from core.research import store,postgres_store as pg
from psycopg.types.json import Jsonb


def promote_reference_run(bundle):
    """Copy only an explicitly selected historical result and its frozen inputs.

    Trading state and credentials are never part of this promotion.
    """
    from scripts.migrate_storage import load_manifest,checked_content
    with tarfile.open(bundle,'r') as archive:
        manifest,fingerprint=load_manifest(archive)
        identity=manifest.get('run_id')
        if not identity or len(identity)!=12 or any(c not in '0123456789abcdef' for c in identity):
            raise ValueError('Invalid reference-run identity.')
        allowed={prefix+'/'+identity for prefix in ('runs','run_data','run_intraday','run_fundamentals','run_sector')}
        if any(r['kind']!='document' or r['name'] not in allowed for r in manifest['records']):
            raise ValueError('Reference promotion may contain only the selected run and frozen inputs.')
        names={r['name'] for r in manifest['records']}
        if not {'runs/'+identity,'run_data/'+identity}<=names:
            raise ValueError('The reference result or its frozen candles are missing.')
        conn,ns=pg.connection(),pg.namespace()
        result=None
        for record in manifest['records']:
            content=checked_content(archive,record)
            digest,name=record['sha256'],record['name']
            previous=conn.execute('SELECT sha256 FROM trader.documents WHERE namespace=%s AND name=%s',(ns,name)).fetchone()
            if previous and previous[0]!=digest:
                raise ValueError('Conflicting reference-run input; promotion refused.')
            if name=='runs/'+identity:
                result=json.loads(gzip.decompress(content))
                if result.get('config',{}).get('simulation_model')!='banana_proxy_v1':
                    raise ValueError('The selected result does not use the reference-pattern model.')
            if not previous:
                conn.execute('INSERT INTO trader.contents(sha256,content,raw_bytes) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',(digest,content,record['raw_bytes']))
                conn.execute('INSERT INTO trader.documents(namespace,name,sha256,metadata) VALUES (%s,%s,%s,%s)',(ns,name,digest,Jsonb(record.get('metadata',{}))))
                if name=='runs/'+identity:pg.project(name,result,digest)
        runs=store.read('runs_index',[])
        if not any(r['id']==identity for r in runs):
            runs.insert(0,{k:result[k] for k in ('id','created_at','config','universe','metrics')})
            store.write('runs_index',runs)
        store.write('reference_run_promotion',dict(run_id=identity,manifest_sha256=fingerprint,at=store.now()))


def apply(*, clear_paper=False, reference_strategies_only=False, reference_bundle=None):
    if not store.database_enabled():
        raise ValueError('Complete the PostgreSQL migration before workspace cleanup.')
    store.ensure_ready()
    batch='archive/workspace-'+uuid4().hex[:12]
    with pg.mutex('application-instance',timeout=0), pg.mutex('scalping_runner',timeout=0), store.LOCK:
        if any(j['status'] in ('queued','running') for j in store.read('jobs',[])):
            raise ValueError('Wait for active jobs before clearing the workspace.')
        if reference_bundle:promote_reference_run(reference_bundle)
        runs=store.read('runs_index',[])
        matches=[r for r in runs if r.get('config',{}).get('simulation_model')=='banana_proxy_v1']
        if runs and not matches:
            raise ValueError('No matching reference-pattern backtest found; no backtests were cleared.')
        keep=max(matches,key=lambda r:(r.get('created_at',''),r['id'])) if matches else None
        archived=[r for r in runs if not keep or r['id']!=keep['id']]
        if archived:
            store.write(batch+'/runs_index',runs)
            store.write('runs_index',[keep] if keep else [])
            prior=store.read('archived_runs_index',[])
            known={r['id'] for r in prior}
            store.write('archived_runs_index',prior+[r for r in archived if r['id'] not in known])
        paper_names=[]
        if clear_paper:
            prefixes=('portfolios/','portfolio_scenarios/','paper_schedules/','paper_scenario_schedules/',
                      'paper_sector/','scalping_stream/','investor/assessments/composite-paper-')
            singles=('paper_portfolio','paper_schedule','investor/portfolio_snapshot','investor/execution')
            paper_names=[name for name in store.keys('',recursive=True)
                         if name.startswith(prefixes) or name in singles]
            conn,ns=pg.connection(),pg.namespace()
            for name in paper_names:
                # Renaming a document retains its exact bytes and every frozen
                # ledger, while active APIs can no longer find the old key.
                conn.execute('UPDATE trader.documents SET name=%s,updated_at=now() WHERE namespace=%s AND name=%s',
                             (batch+'/'+name,ns,name))
            conn.execute('DELETE FROM trader.trade_records WHERE namespace=%s AND owner_kind LIKE %s',(ns,'paper_%'))
            conn.execute('DELETE FROM trader.portfolios WHERE namespace=%s',(ns,))
            store.write('investor/paper_control',dict(enabled=False,reason='Paper workspace cleared by owner',at=store.now()))
            settings=store.read('investor/settings')
            if settings and settings.get('profit_exit_enabled'):
                store.write(batch+'/investor-settings-before-cleanup',settings)
                store.write('investor/settings',dict(settings,profit_exit_enabled=False))
        result=dict(at=store.now(),archive=batch,kept_backtest=keep['id'] if keep else None,
                    kept_pattern=keep.get('config',{}).get('pattern') if keep else None,
                    archived_backtests=len(archived),archived_paper_documents=len(paper_names),
                    paper_portfolios_remaining=len(store.keys('portfolios/'))+len(store.keys('portfolio_scenarios/',recursive=True)))
        if reference_strategies_only:
            catalog=store.read('strategy_catalog',[])
            selected=[p for p in catalog if (p.get('backtest_defaults') or {}).get('simulation_model')=='banana_proxy_v1']
            labels={'vcp':'VCP breakout','blue_sky':'Blue sky breakout','multiyear':'Multi-year breakout','ipo':'IPO base'}
            if {p['pattern'] for p in selected}!=set(labels):
                raise ValueError('The four fixed-rule strategy definitions are incomplete; cleanup rolled back.')
            for name in ('strategy_catalog','screens','archived_screens','strategy_catalog_policy'):
                value=store.read(name)
                if value is not None:store.write(batch+'/'+name,value)
            selected.sort(key=lambda p:list(labels).index(p['pattern']))
            for preset in selected:
                preset['name']=labels[preset['pattern']]
                preset['description']='Fixed breakout rules with saved risk and execution settings.'
                for key in ('backtest_defaults','paper_defaults'):
                    if preset.get(key):preset[key]['name']=preset['name']
            ids={p['id'] for p in selected}
            store.write('strategy_catalog',selected)
            store.write('screens',[])
            store.write('archived_screens',[p for p in store.read('archived_screens',[]) if p['id'] not in ids])
            store.write('strategy_catalog_policy',dict(mode='reference_only',updated_at=store.now()))
            result['strategies_remaining']=[p['name'] for p in selected]
        store.write(batch+'/receipt',result)
        store.write('workspace_cleanup',result)
        return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clear-paper',action='store_true')
    parser.add_argument('--reference-strategies-only',action='store_true')
    parser.add_argument('--reference-bundle')
    args=parser.parse_args()
    print(json.dumps(apply(clear_paper=args.clear_paper,reference_strategies_only=args.reference_strategies_only,reference_bundle=args.reference_bundle)))

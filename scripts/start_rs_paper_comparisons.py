"""Create the six owner-requested paper comparisons from captured source histories."""
from copy import deepcopy
from datetime import date
import json
from types import SimpleNamespace

from core.research import store, jobs, identity, four_indicator_swing as fs
from core.portfolio import manager, four_indicator_paper as paper


SOURCES = [('indicator_all4_20261012','2026-10-12','12 Oct 2026'),
           ('indicator_all4_20251030','2025-10-30','Full year from 30 Oct 2025')]
VARIANTS = [('base','Baseline','turnover',1),('rs126','RS126','rs_126',1),
            ('rs126_75','RS126 · 75% slots','rs_126',.75)]


def specs():
    for source,start,label in SOURCES:
        for short,title,ranking,scale in VARIANTS:
            pid='cmp_'+short+'_'+start.replace('-','')
            config=paper.PaperConfig(name=identity.label(title+' · '+label),start_session=start,
                                     rule_set='bollinger',capital=1000000,max_positions=10,rsi_threshold=65,
                                     bollinger_multiplier=2.5,slippage_bps=10,candidate_ranking=ranking,
                                     slot_scale=scale,auto_run=True)
            yield source,pid,config


def create(log,job_id):
    requested=list(specs())
    with store.LOCK:
        existing={pid:manager.get(fs.STRATEGY,pid) for _,pid,_ in requested}
        if any(existing.values()):
            if not all(existing.values()): raise ValueError('Only some comparison portfolios exist; no overwrite performed.')
            for _,pid,cfg in requested:
                p=existing[pid]
                if p['config']!=cfg.model_dump(mode='json') or not p['ledger'].get('last_session'):
                    raise ValueError('Existing comparison differs or is incomplete: '+pid)
            return dict(already_created=True,portfolios=[summary(p) for p in existing.values()])
        sources={source:manager.get(fs.STRATEGY,source) for source,_,_ in SOURCES}
        before={key:fs.digest(value) for key,value in store.records('portfolio_scenarios/'+fs.STRATEGY+'/')}
        index=store.read('bars/NIFTY50',{}).get('bars',[])
        inputs={}
        for source,_,_ in SOURCES:
            p=sources[source]
            if not p or not p['ledger'].get('last_session'): raise ValueError('Source paper history missing: '+source)
            f=store.read(p['input_reference'])
            if not f or fs.digest(f)!=p['cycles'][-1]['input_sha256']: raise ValueError('Source paper checksum mismatch: '+source)
            inputs[source]=deepcopy(f)
    staged=[]
    for source,start,_ in SOURCES:
        frozen=inputs[source]
        end=sources[source]['ledger']['last_session']
        frozen['benchmark']=[b for b in index if b['date']<=end]
        signal_values=fs.features(frozen['datasets'],log,rsi_threshold=65,bollinger_multiplier=2.5)
        digest=fs.digest(frozen)
        for requested_source,pid,cfg in requested:
            if requested_source!=source: continue
            simcfg=SimpleNamespace(**cfg.model_dump(),start=date.fromisoformat(start),end=date.fromisoformat(end))
            result=fs.simulate(frozen['datasets'],signal_values,simcfg,fs.RULES[3],liquidate=False,
                               instruments=frozen['universe']['instruments'],benchmark=frozen['benchmark'])
            at=store.now()
            reference='paper_inputs/'+pid+'/'+job_id
            ledger=result['ledger']
            for order in ledger['orders']:
                order.update(mode='historical_replay',job_id=job_id,status='Simulated · historical replay')
            cycle=dict(job_id=job_id,at=at,start=start,end=end,config=cfg.model_dump(mode='json'),
                       input_reference=reference,input_sha256=digest,status='active',trigger='owner_requested_comparison_replay')
            p=dict(id=pid,strategy_name=fs.STRATEGY,mode='paper',status='active',created_at=at,updated_at=at,
                   created_by=identity.username(),start_session=start,universe=sources[source]['universe'],
                   config=cfg.model_dump(mode='json'),ledger=ledger,metrics=result['metrics'],cycles=[cycle],
                   config_history=[],input_reference=reference,universe_snapshot=frozen['universe'],
                   excluded=frozen['exclusion_reasons'],replay_through=end,
                   reconstruction_notice='Comparison history through '+end+' is replayed simulation with detailed Upstox Plus fees throughout. Later cycles carry holdings forward. No broker orders.',
                   comparison_group='rs126_20261030',source_portfolio=source,fee_model='upstox_plus')
            expected=cfg.capital+sum(t['pnl'] for t in ledger['trades'])+sum(x['quantity']*ledger['marks'][s]-x['entry_cost'] for s,x in ledger['positions'].items())
            if abs(expected-result['metrics']['final_equity'])>1e-5 or ledger['cash']<-.001:
                raise ValueError('Comparison accounting failed: '+pid)
            staged.append((pid,p,reference,frozen))
            log(pid+': replay ready; return '+f'{result["metrics"]["return_pct"]:.2f}%')
    # A single database transaction makes all six records and their input references visible together.
    with store.LOCK:
        active={j['id'] for j in store.read('jobs',[]) if j['status'] in ('queued','running')}
        if active!={job_id}: raise ValueError('Another job is active; no comparison portfolios were written.')
        current={key:fs.digest(value) for key,value in store.records('portfolio_scenarios/'+fs.STRATEGY+'/')}
        if current!=before: raise ValueError('Paper portfolios changed during calculation; no comparisons were written.')
        for pid,p,reference,frozen in staged:
            if manager.get(fs.STRATEGY,pid) or store.read(reference) is not None:
                raise ValueError('Comparison identity already exists; no overwrite performed: '+pid)
        for pid,p,reference,frozen in staged:
            store.write(reference,frozen)
            store.write(manager.key(fs.STRATEGY,pid),p)
        for key,digest in before.items():
            if fs.digest(store.read(key))!=digest: raise ValueError('Existing paper portfolio changed unexpectedly.')
    return dict(already_created=False,portfolios=[summary(p) for _,p,_,_ in staged],existing_portfolios_preserved=True)


def summary(p):
    return dict(id=p['id'],name=p['config']['name'],ranking=p['config']['candidate_ranking'],slot_scale=p['config']['slot_scale'],
                start=p['start_session'],last_session=p['ledger']['last_session'],status=p['status'],auto_run=p['config']['auto_run'],
                capital=p['config']['capital'],metrics=p['metrics'],open_positions=len(p['ledger']['positions']))


if __name__=='__main__':
    with identity.scope({'username':'manoj'}):
        job=jobs.submit('Replay six RS126 paper comparisons',create,{'strategy_id':fs.STRATEGY,'trigger':'owner_requested'})
        print('Queued comparison replay '+job['id'],flush=True)
        jobs.POOL.shutdown(wait=True)
        saved=next(j for j in store.read('jobs',[]) if j['id']==job['id'])
        if saved['status']!='success':
            print(saved['logs'][-1]['message'],flush=True)
            raise SystemExit(1)
        print(json.dumps(saved['result'],indent=2),flush=True)

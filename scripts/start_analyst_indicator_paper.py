"""Create two explicitly labelled hindsight seeds, then use causal analyst paper cycles."""
from copy import deepcopy
from datetime import date
from types import SimpleNamespace
import json

from core.research import store, jobs, identity, indian_api, four_indicator_swing as fs
from core.research.analyst_consensus import ConsensusGate
from core.portfolio import manager, registry, refresh_followup, analyst_indicator_paper as analyst
from core.portfolio.five_indicator_paper import published_end

SOURCES=[('indicator_all4_20251030','analyst75_20251030','2025-10-30','One year from 30 Oct 2025'),
         ('indicator_all4_20261012','analyst75_20261012','2026-10-12','From 12 Oct 2026')]


def summaries():
    return [dict(id=p['id'],name=p['config']['name'],start=p['start_session'],through=p['ledger']['last_session'],
                 status=p['status'],auto_run=p['config']['auto_run'],metrics=p['metrics'])
            for _,pid,_,_ in SOURCES if (p:=manager.get(analyst.STRATEGY,pid))]


def create(log,job_id):
    with store.LOCK:
        existing=[manager.get(analyst.STRATEGY,pid) for _,pid,_,_ in SOURCES]
        if any(existing):
            if not all(existing):raise ValueError('Only part of the analyst paper group exists; no overwrite performed.')
            return dict(already_created=True,portfolios=summaries())
        before={manager.key(s,p['id']):fs.digest(p) for s in registry.PLUGINS for p in manager.list_portfolios(s)}
        schedule=deepcopy(store.read(refresh_followup.KEY,{}))
        sources={source:deepcopy(manager.get(fs.STRATEGY,source)) for source,_,_,_ in SOURCES}
        inputs={}
        for source,_,_,_ in SOURCES:
            p=sources[source]
            if not p:raise ValueError('Missing four-indicator reference portfolio: '+source)
            frozen=store.read(p['input_reference'])
            if not frozen or fs.digest(frozen)!=p['cycles'][-1]['input_sha256']:
                raise ValueError('Source paper inputs are unavailable or changed: '+source)
            inputs[source]=deepcopy(frozen)
    staged=[]
    for source,pid,start,label in SOURCES:
        frozen=inputs[source]
        end=str(published_end(frozen['universe'],date.fromisoformat(sources[source]['ledger']['last_session']),frozen['datasets']))
        frozen['datasets']={s:[b for b in rows if b['date']<=end] for s,rows in frozen['datasets'].items()}
        frozen['benchmark']=[b for b in frozen.get('benchmark',[]) if b['date']<=end]
        cfg=analyst.PaperConfig(name=identity.label('Analyst 75% · '+label),start_session=start,auto_run=True)
        simcfg=SimpleNamespace(**cfg.model_dump(),start=date.fromisoformat(start),end=date.fromisoformat(end))
        signals=fs.features(frozen['datasets'],log,rsi_threshold=65,bollinger_multiplier=2.5)
        items={i['symbol']:i for i in frozen['universe']['instruments']}
        observations={}
        def gate(symbol,signal_date,entry_date):
            if symbol not in observations:
                observations[symbol]=indian_api.collect(items[symbol],log)
            observation=observations[symbol]
            return ConsensusGate({symbol:observation} if observation else {},threshold_pct=75,allow_hindsight=True)(symbol,signal_date,entry_date)
        result=fs.simulate(frozen['datasets'],signals,simcfg,fs.RULES[3],liquidate=False,
                           instruments=frozen['universe']['instruments'],entry_filter=gate)
        frozen['analyst_observations']={s:o for s,o in observations.items() if o}
        frozen['analyst_provenance']='HINDSIGHT ONLY: creation-time opinions applied to historical entries.'
        digest=fs.digest(frozen);at=store.now();ref='paper_inputs/'+pid+'/'+job_id
        ledger=result['ledger']
        for order in ledger['orders']:
            order.update(mode='historical_replay',job_id=job_id,status='Simulated · HINDSIGHT analyst replay')
        notice=('HINDSIGHT historical seed through '+end+': analyst opinions collected at creation were applied to older trades; '
                'this history is not a point-in-time backtest. Future buys require a stored, ISIN-verified snapshot observed before '
                'the entry open, no more than 7 days old, with Buy + Strong Buy >=75%. Missing/invalid data blocks buys; exits remain active. '
                'Published daily candles only. No broker orders.')
        p=dict(id=pid,strategy_name=analyst.STRATEGY,mode='paper',status='active',created_at=at,updated_at=at,
               created_by=identity.username(),start_session=start,universe=sources[source]['universe'],config=cfg.model_dump(mode='json'),
               ledger=ledger,metrics=result['metrics'],cycles=[dict(job_id=job_id,at=at,start=start,end=end,config=cfg.model_dump(mode='json'),
                   input_reference=ref,input_sha256=digest,status='active',trigger='owner_requested_hindsight_seed')],
               config_history=[],input_reference=ref,universe_snapshot=frozen['universe'],excluded=frozen.get('exclusion_reasons',{}),
               replay_through=end,analyst_hindsight_through=end,reconstruction_notice=notice,fee_model='upstox_plus',
               last_entry_filter_decisions=result.get('entry_filter_decisions',[]))
        equity=ledger['cash']+sum(x['quantity']*ledger['marks'][s] for s,x in ledger['positions'].items())
        if abs(equity-result['metrics']['final_equity'])>1e-5:raise ValueError('New paper accounting failed: '+pid)
        staged.append((pid,p,ref,frozen))
        log(pid+': hindsight seed ready; '+f'{result["metrics"]["return_pct"]:.2f}%'+'.')
    with store.LOCK:
        if {j['id'] for j in store.read('jobs',[]) if j['status'] in ('queued','running')}!={job_id}:
            raise ValueError('Other work is active; no portfolios were created.')
        current={manager.key(s,p['id']):fs.digest(p) for s in registry.PLUGINS for p in manager.list_portfolios(s)}
        if current!=before or store.read(refresh_followup.KEY,{})!=schedule:raise ValueError('Paper state changed; no portfolios were created.')
        for pid,p,ref,frozen in staged:
            store.write(ref,frozen);store.write(manager.key(analyst.STRATEGY,pid),p)
        settings=deepcopy(schedule);settings['enabled']=True
        settings['strategy_ids']=sorted(set(settings.get('strategy_ids',[]))|{s for s,plugin in registry.PLUGINS.items() if plugin.trigger_mode=='batch'})
        settings['updated_at']=store.now();store.write(refresh_followup.KEY,settings)
        for k,digest in before.items():
            if fs.digest(store.read(k))!=digest:raise ValueError('An existing portfolio changed unexpectedly.')
    return dict(existing_portfolios_preserved=True,portfolios=summaries())


if __name__=='__main__':
    with identity.scope({'username':'manoj'}):
        job=jobs.submit('Create analyst-filter paper portfolios',create,{'strategy_id':analyst.STRATEGY,'trigger':'owner_requested'})
        print('Queued analyst paper creation '+job['id'],flush=True)
        jobs.POOL.shutdown(wait=True)
        saved=next(j for j in store.read('jobs',[]) if j['id']==job['id'])
        if saved['status']!='success':print(saved['logs'][-1]['message']);raise SystemExit(1)
        print(json.dumps(saved['result'],indent=2),flush=True)

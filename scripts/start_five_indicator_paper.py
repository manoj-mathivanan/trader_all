"""Create the two owner-requested five-indicator paper portfolios from cached data."""
from copy import deepcopy
from datetime import date
import json
from types import SimpleNamespace

from core.research import store,jobs,identity,four_indicator_swing as fs
from core.research.config import Settings
from core.portfolio import manager,paper,five_indicator_paper as five,refresh_followup
from core.research import current_session


STARTS=[('five_20261012','2026-10-12','12 Oct 2026'),('five_20260930','2026-09-30','Last month from 30 Sep 2026')]


def create(log,job_id):
    configs={pid:five.PaperConfig(name=identity.label('Five indicators · '+label),start_session=start,auto_run=True)
             for pid,start,label in STARTS}
    with store.LOCK:
        existing={pid:manager.get(five.STRATEGY,pid) for pid,_,_ in STARTS}
        if any(existing.values()):
            if not all(existing.values()):raise ValueError('Only part of the five-indicator group exists; no overwrite performed.')
            for pid,p in existing.items():
                if p['config']!=configs[pid].model_dump(mode='json') or not p.get('ledger',{}).get('last_session'):
                    raise ValueError('Existing five-indicator portfolio differs: '+pid)
            return dict(already_created=True,portfolios=[summary(p) for p in existing.values()])
        before={key:fs.digest(value) for key,value in store.records('portfolio_scenarios/',recursive=True)}
        settings_before=store.read(refresh_followup.KEY,{})
        cutoff=current_session.completed_day(paper.local_now())
        index=store.read('bars/NIFTY50',{}).get('bars',[])
        completed=[b['date'] for b in index if b['date']<=str(cutoff)]
        if not completed:raise ValueError('No cached completed benchmark sessions.')
        universe=store.read('universes/niftytotalmarket')
        if not universe:raise ValueError('The cached stock universe is unavailable.')
        end=str(five.published_end(universe,date.fromisoformat(max(completed))))
        if end<max(start for _,start,_ in STARTS):raise ValueError('Published prices do not yet cover the requested replay starts.')
    research=SimpleNamespace(start=date(2026,9,30),end=date.fromisoformat(end),comparison_run_id=None,coverage_mode='available_history')
    frozen=fs.prepare(Settings(universe='niftytotalmarket'),research,log)
    signals=fs.features(frozen['datasets'],log,rsi_threshold=65,bollinger_multiplier=2.5)
    digest=fs.digest(frozen)
    staged=[]
    for pid,start,_ in STARTS:
        cfg=configs[pid]
        simcfg=SimpleNamespace(**cfg.model_dump(),start=date.fromisoformat(start),end=date.fromisoformat(end))
        result=fs.simulate(frozen['datasets'],signals,simcfg,fs.RULES[3],liquidate=False,
                           instruments=frozen['universe']['instruments'],benchmark=frozen['benchmark'])
        ledger=result['ledger'];at=store.now()
        for order in ledger['orders']:
            order.update(mode='historical_replay',job_id=job_id,status='Simulated · historical replay')
        reference='paper_inputs/'+pid+'/'+job_id
        p=dict(id=pid,strategy_name=five.STRATEGY,mode='paper',status='active',created_at=at,updated_at=at,created_by=identity.username(),
               start_session=start,universe='niftytotalmarket',config=cfg.model_dump(mode='json'),ledger=ledger,metrics=result['metrics'],
               cycles=[dict(job_id=job_id,at=at,start=start,end=end,config=cfg.model_dump(mode='json'),input_reference=reference,
                            input_sha256=digest,status='active',trigger='owner_requested_five_indicator_replay')],
               config_history=[],input_reference=reference,universe_snapshot=frozen['universe'],excluded=frozen['exclusion_reasons'],
               replay_through=end,reconstruction_notice='Four entry conditions plus RS126 candidate ranking. History through '+end+' is simulated replay with detailed Upstox Plus fees. Subsequent cycles use published daily candles and carry holdings forward; provisional aggregates are deferred. No broker orders.',
               fee_model='upstox_plus')
        equity=ledger['cash']+sum(x['quantity']*ledger['marks'][s] for s,x in ledger['positions'].items())
        if abs(equity-result['metrics']['final_equity'])>1e-5 or ledger['cash']<-.001:raise ValueError('Paper accounting failed: '+pid)
        staged.append((pid,p,reference))
        log(pid+': '+f'{result["metrics"]["return_pct"]:.2f}% return; replay ready.')
    with store.LOCK:
        if {j['id'] for j in store.read('jobs',[]) if j['status'] in ('queued','running')}!={job_id}:
            raise ValueError('Other work started; no five-indicator portfolios were written.')
        current={key:fs.digest(value) for key,value in store.records('portfolio_scenarios/',recursive=True)}
        if current!=before or store.read(refresh_followup.KEY,{})!=settings_before:
            raise ValueError('Paper state changed during calculation; no portfolios were written.')
        for pid,p,ref in staged:
            if manager.get(five.STRATEGY,pid) or store.read(ref) is not None:raise ValueError('Paper identity already exists: '+pid)
        for pid,p,ref in staged:
            store.write(ref,frozen);store.write(manager.key(five.STRATEGY,pid),p)
        settings=deepcopy(settings_before)
        ids=settings.setdefault('strategy_ids',[])
        if five.STRATEGY not in ids:ids.append(five.STRATEGY)
        store.write(refresh_followup.KEY,settings)
        for key,value in before.items():
            if fs.digest(store.read(key))!=value:raise ValueError('An existing portfolio changed unexpectedly.')
    return dict(already_created=False,existing_portfolios_preserved=True,portfolios=[summary(p) for _,p,_ in staged])


def summary(p):
    return dict(id=p['id'],name=p['config']['name'],strategy=p['strategy_name'],start=p['start_session'],
                through=p['ledger']['last_session'],status=p['status'],auto_run=p['config']['auto_run'],
                capital=p['config']['capital'],metrics=p['metrics'])


if __name__=='__main__':
    with identity.scope({'username':'manoj'}):
        j=jobs.submit('Replay five-indicator paper portfolios',create,{'strategy_id':five.STRATEGY,'trigger':'owner_requested'})
        print('Queued five-indicator replay '+j['id'],flush=True)
        jobs.POOL.shutdown(wait=True)
        saved=next(x for x in store.read('jobs',[]) if x['id']==j['id'])
        if saved['status']!='success':
            print(saved['logs'][-1]['message'],flush=True);raise SystemExit(1)
        print(json.dumps(saved['result'],indent=2),flush=True)

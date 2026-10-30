"""Prospectively frozen EOD shadow paper; market-data GETs only."""
from datetime import date, datetime, timedelta, timezone
from html import escape
import json
import hashlib
import os
from pathlib import Path
import sqlite3
import sys
from urllib.parse import quote

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from core.research import options_backtest as bt, options_history as h, jobs, store
from core.research.options_extended import DiskPrices, merge_unique
from scripts.analyse_options_risk import digest, stats
from scripts.research_options_extended import BudgetTransport
from scripts.research_options_premium_stop import risk

ROOT=Path('artifacts/options_forward_server_v1').resolve()
SOURCES=['scripts/forward_options_paper.py','core/research/options_backtest.py',
    'core/research/options_strategy.py','core/research/options_history.py','core/research/options_costs.py',
    'core/research/options_extended.py','core/research/upstox.py','core/research/intraday_data.py',
    'core/strategies/four_indicator.py','core/execution/upstox.py','scripts/analyse_options_risk.py',
    'scripts/research_options_premium_stop.py','scripts/research_options_extended.py',
    'scripts/research_options_sample.py','scripts/run_options_forward_service.py']


def first_session(clock):
    day=clock.date()
    if clock.strftime('%H:%M') >= '09:15':
        day+=timedelta(days=1)
    while day.weekday()>=5:
        day+=timedelta(days=1)
    return day


def freeze(root,clock):
    root.mkdir(parents=True,exist_ok=True)
    path=root/'frozen-plan.json'
    if path.exists():
        plan=json.loads(path.read_text())
        for p,sha in plan['source_hashes'].items():
            if digest(Path(p))!=sha or digest(root/'source-snapshot'/p)!=sha:
                raise ValueError('Frozen source changed: '+p+'. Restore the recorded version or create a separate forward study; do not revise this ledger.')
        return plan
    plan=dict(created_at=clock.isoformat(),first_eligible_session=str(first_session(clock)),
        mode='forward_end_of_day_shadow_paper',initial_cash=100000,timeframe=3,premium_variant='fixed_250',
        slippage_bps_each_side=10,breakeven_activation_fraction=.2,fixed_premium_loss_stop=None,
        contract_policy='Nearest-expiry full catalog captured before 09:15 IST for that date. Rank positive-volume observed prior-minute closes nearest INR250. Missing candidates remain diagnostic.',
        processing='Following-morning reconstruction from completed candles; not real-time executable paper orders. No historical trades before activation imported. Warmup history only.',
        comparison='Original exits versus protected exits, each independently funded with INR100000; fees from frozen shared Plus model.',
        review_after=dict(completed_observed_sessions=60,protected_closed_trades=100),
        review_policy='Review only after both minimums; do not stop early because of favorable performance. Missing eligible-session evidence prevents a validation claim. No automatic promotion to live trading.',
        limits=['No bid/ask execution validation.','Protection does not guarantee breakeven fills.',
            'No threshold tuning during collection.','Weekday calendar is provisional; provider candles establish actual sessions.'],
        source_hashes={p:digest(Path(p)) for p in SOURCES})
    for p in SOURCES:
        target=root/'source-snapshot'/p
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(Path(p).read_bytes())
    h.save_json(path,plan)
    return plan


def capture_catalog(client,token,root,plan,clock):
    day=clock.date()
    if day.weekday()>=5 or str(day)<plan['first_eligible_session'] or clock.strftime('%H:%M')>='09:15':
        return None
    path=root/'catalogs'/f'{day}.json'
    if path.exists():
        return json.loads(path.read_text())
    payload=h.request(client,token,'/v2/option/contract',{'instrument_key':h.UNDERLYING})
    expiries=sorted({c['expiry'] for c in payload['data'] if c['expiry']>=str(day)})
    if not expiries:
        raise ValueError('No current NIFTY expiry catalog available.')
    contracts=h.validate_contracts([c for c in payload['data'] if c['expiry']==expiries[0]],expiries[0])
    snapshot=dict(session=str(day),captured_at=clock.isoformat(),expiry=expiries[0],contracts=contracts)
    h.save_json(path,snapshot)
    return snapshot


def validate_snapshot(snapshot,plan):
    instant=datetime.fromisoformat(snapshot['captured_at']).astimezone(h.IST)
    if instant.date().isoformat()!=snapshot['session'] or instant.strftime('%H:%M')>='09:15' or snapshot['session']<plan['first_eligible_session']:
        raise ValueError('Catalog was not prospectively captured before the eligible session.')
    return h.validate_contracts(snapshot['contracts'],snapshot['expiry'])


def collect(client,token,root,snapshot,plan,clock,log):
    contracts=validate_snapshot(snapshot,plan)
    day=date.fromisoformat(snapshot['session'])
    if day>=clock.date():
        raise ValueError('Only completed prior-day candles may be collected.')
    directory=root/'sessions'/str(day)
    path=directory/'research-manifest.json'
    if path.exists():
        previous=json.loads(path.read_text())
        if previous.get('status')=='research_downloaded':
            for record in previous['files']+previous['catalogs']:
                bt.read_evidence(directory,record)
            return
    h.download_underlying(client,token,start=day,end=day,output=directory)
    _,minutes,_=bt.load_underlying(directory)
    if not any(b['date']==str(day) for b in minutes):
        raise ValueError('No provider underlying session found; retain catalog and investigate calendar/data availability.')
    cat=directory/'catalog.json'
    h.save_json(cat,contracts)
    manifest=dict(status='downloading',underlying_key=h.UNDERLYING,start=str(day),end=str(day),
        catalog_snapshot_sha256=digest(root/'catalogs'/f'{day}.json'),
        catalogs=[dict(file=cat.name,sha256=digest(cat),expiry=snapshot['expiry'])],files=[],failures=[])
    old_records={r['instrument']['instrument_key']:r for r in previous.get('files',[])} if path.exists() else {}
    expired={}
    if snapshot['expiry']<str(clock.date()):
        response=h.request(client,token,'/v2/expired-instruments/option/contract',
            {'instrument_key':h.UNDERLYING,'expiry_date':snapshot['expiry']})
        expired={str(c['exchange_token']):c for c in h.validate_contracts(response['data'],snapshot['expiry'])}
        h.save_json(directory/'expired-catalog-response.json',response)
    h.save_json(path,manifest)
    for index,item in enumerate(contracts):
        old=old_records.get(item['instrument_key'])
        if old:
            bt.read_evidence(directory,old)
            manifest['files'].append(old)
            continue
        request_key=item['instrument_key']
        if expired:
            mapped=expired.get(str(item['exchange_token']))
            if not mapped or any(mapped[k]!=item[k] for k in ('expiry','strike_price','instrument_type','lot_size','underlying_key')):
                raise ValueError('Expired contract identity does not match prospective catalog.')
            request_key=mapped['instrument_key']
            endpoint=f'/v2/expired-instruments/historical-candle/{quote(request_key,safe="")}/1minute/{day}/{day}'
        else:
            endpoint=f'/v3/historical-candle/{quote(request_key,safe="")}/minutes/1/{day}/{day}'
        payload=h.request(client,token,endpoint)
        filename='option-'+hashlib.sha256(item['instrument_key'].encode()).hexdigest()[:20]+'.json'
        record=h.archive(directory/filename,payload,day,day)
        manifest['files'].append(dict(record,instrument=item,start=str(day),end=str(day),provider_request_key=request_key))
        h.save_json(path,manifest)
        if index%25==0:
            log(f'{day}: archived {index+1}/{len(contracts)} contracts.')
    manifest['status']='research_downloaded'
    h.save_json(path,manifest)
    log(f'{day}: complete; {len(contracts)} contract records archived.')


def evaluate(root,plan):
    directories=sorted(p.parent for p in (root/'sessions').glob('*/research-manifest.json')
        if json.loads(p.read_text()).get('status')=='research_downloaded')
    if not directories:
        return dict(status='waiting_for_first_completed_session',completed_observed_sessions=0,closed_trades=0)
    minutes,daily,session_catalogs={},{},{}
    connection=sqlite3.connect(':memory:')
    connection.execute('CREATE TABLE prices(instrument TEXT,timestamp INTEGER,open REAL,close REAL,volume REAL,PRIMARY KEY(instrument,timestamp)) WITHOUT ROWID')
    inputs=[]
    try:
        for directory in directories:
            _,m,d=bt.load_underlying(directory)
            merge_unique(minutes,m,'timestamp')
            merge_unique(daily,d,'date')
            manifest=json.loads((directory/'research-manifest.json').read_text())
            snapshot=json.loads((root/'catalogs'/f'{directory.name}.json').read_text())
            validate_snapshot(snapshot,plan)
            if digest(root/'catalogs'/f'{directory.name}.json')!=manifest['catalog_snapshot_sha256']:
                raise ValueError('Prospective catalog checksum changed.')
            session_catalogs[directory.name]={r['expiry']:bt.read_evidence(directory,r) for r in manifest['catalogs']}
            for r in manifest['files']:
                raw=bt.read_evidence(directory,r)
                bars=h.normalize_candles(raw['raw_response']['data']['candles'],date.fromisoformat(directory.name),date.fromisoformat(directory.name))
                connection.executemany('INSERT INTO prices VALUES(?,?,?,?,?)',[(r['instrument']['instrument_key'],b['timestamp'],b['open'],b['close'],b['volume']) for b in bars])
            inputs.append(dict(session=directory.name,manifest_sha256=digest(directory/'research-manifest.json')))
        start=date.fromisoformat(plan['first_eligible_session']); end=date.fromisoformat(directories[-1].name)
        audit=bt.prepare_signals(sorted(minutes.values(),key=lambda b:b['timestamp']),sorted(daily.values(),key=lambda b:b['date']),start=start,end=end,timeframe=3)
        # Warmup/fetched sessions without a prospective catalog cannot create paper entries.
        observed=set(session_catalogs)
        unobserved=sorted({e['date'] for e in audit['events']}-observed)
        audit['events']=[e for e in audit['events'] if e['date'] in observed]
        prices=DiskPrices(connection)
        replays={}
        for key,activation in [('baseline',None),('protection',.2)]:
            replay=bt.replay(audit,prices,{},[],bt.ReplayConfig(chain_policy='observed_traded',slippage_bps=10,
                breakeven_activation_fraction=activation),session_catalogs=session_catalogs)
            replays[key]=replay
        valid=all(r['diagnostic_summary'] is not None and not r['skipped_entries'] for r in replays.values()) and not audit['excluded_sessions']
        return dict(status='forward_diagnostic_updated' if valid else 'incomplete_forward_inputs',
            completed_observed_sessions=len(directories),closed_trades=len(replays['protection']['trades']),
            review_minimums_reached=valid and not unobserved and len(directories)>=60 and len(replays['protection']['trades'])>=100,
            unobserved_provider_sessions=unobserved,excluded_sessions=audit['excluded_sessions'],inputs=inputs,replays=replays,
            summary={key:dict(**stats(r['trades']),**risk(connection,r)) for key,r in replays.items()} if valid else None)
    finally:
        connection.close()


def render(root,status):
    recent=[j for j in store.read('jobs',[]) if j.get('payload',{}).get('study')=='options_forward_v1'][:8]
    html='<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="60"><title>Forward options paper</title><style>body{font:16px system-ui;max-width:1050px;margin:35px auto;padding:20px}pre{white-space:pre-wrap;background:#eef2f7;padding:15px}</style><h1>Forward options: frozen shadow paper</h1><p>Following-morning reconstruction, not real-time execution. Separate forward ledger; jobs and logs use the shared dashboard job store.</p><pre>'+escape(json.dumps(status,indent=2))+'</pre><h2>Actual study jobs and logs</h2>'
    for job in recent:
        html+='<h3>'+escape(job['created_at']+' · '+job['id']+' · '+job['status'])+'</h3><pre>'+escape('\n'.join(x['at']+' '+x['message'] for x in job['logs']))+'</pre>'
    html+='<p><a href="frozen-plan.json">Frozen plan</a> · <a href="forward-results.json">Forward ledger</a></p>'
    (root/'status.html').write_text(html,encoding='utf-8')


def main():
    if store.database_enabled() and os.environ.get('TRADER_DB_NAMESPACE')!='local':
        raise ValueError('This study must use the local database namespace.')
    if not store.database_enabled():
        store.DATA=ROOT/'job-store'
    clock=datetime.now(h.IST)
    status=dict(status='checking',checked_at=clock.isoformat())
    def run(log,job_id):
        def message(value):
            log(value); render(ROOT,status)
        try:
            plan=freeze(ROOT,clock)
            token=store.token()
            with httpx.Client(transport=BudgetTransport(ROOT/'request-times.json'),timeout=45) as client:
                snapshot=capture_catalog(client,token,ROOT,plan,clock)
                if snapshot:
                    message(f"Prospective catalog saved for {snapshot['session']}: {len(snapshot['contracts'])} contracts, expiry {snapshot['expiry']}.")
                collection_issues=[]
                for path in sorted((ROOT/'catalogs').glob('*.json')):
                    snapshot=json.loads(path.read_text())
                    if snapshot['session']<str(clock.date()):
                        try:
                            collect(client,token,ROOT,snapshot,plan,clock,message)
                        except h.ProviderError:
                            raise
                        except ValueError as exc:
                            collection_issues.append(dict(session=snapshot['session'],reason=str(exc)))
                            message(snapshot['session']+': '+str(exc))
            result=evaluate(ROOT,plan)
            result['collection_issues']=collection_issues
            if collection_issues:
                result['status']='incomplete_forward_inputs'
                result['review_minimums_reached']=False
            h.save_json(ROOT/'forward-results.json',result)
            status.update(status=result['status'],first_eligible_session=plan['first_eligible_session'],
                completed_observed_sessions=result['completed_observed_sessions'],closed_trades=result['closed_trades'],
                catalog_captured_for=str(clock.date()) if (ROOT/'catalogs'/f'{clock.date()}.json').exists() else None,
                next_cycle='Daily 08:45 IST: archive prior captured sessions and snapshot today before open.',
                review_minimums=plan['review_after'])
            message('Forward study checked. '+result['status']+'.')
            h.save_json(ROOT/'status.json',status)
            return dict(study='options_forward_v1',status=result['status'],partial=result['status']=='incomplete_forward_inputs')
        except Exception:
            status.update(status='needs_attention',message='Cycle failed; inspect the local job log. Existing archives retained.')
            h.save_json(ROOT/'status.json',status)
            raise
    job=jobs.submit('Options forward paper cycle',run,dict(study='options_forward_v1'),after_complete=lambda:render(ROOT,status))
    print('Submitted actual local job '+job['id'],flush=True)


if __name__=='__main__':
    main()

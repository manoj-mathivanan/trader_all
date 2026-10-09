"""Backfill four published quarters from official NSE filings, without backdating collection."""
import argparse
import hashlib
import json
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from core.research import store, fundamentals, official_filings as filing, company_review


def periods(sources, quarters=4):
    return sorted({s['period_end'] for s in sources},reverse=True)[:quarters]


def sources_for_period(sources, period):
    basis='consolidated' if any(s['period_end']==period and s['basis']=='consolidated' for s in sources) else 'standalone'
    day=date.fromisoformat(period)
    wanted={period,day.replace(year=day.year-1).isoformat()}
    for month in (3,12):
        annual=sorted({s['period_end'] for s in sources if s['period_end']<=period and s['period_end'][5:]==f'{month:02d}-31'},reverse=True)
        wanted.update(annual[:2])
    return [s for s in sources if s['basis']==basis and s['period_end'] in wanted]


class CacheTransport(httpx.BaseTransport):
    def __init__(self,cache):
        self.cache=cache; self.network=httpx.HTTPTransport()

    def handle_request(self,request):
        entry=self.cache.get(str(request.url))
        if entry:
            path=store.DATA/entry['artifact']
            if path.exists():
                raw=path.read_bytes()
                if hashlib.sha256(raw).hexdigest()==entry['sha256']:
                    return httpx.Response(200,headers={'content-type':'text/html'},content=raw)
        return self.network.handle_request(request)

    def close(self): self.network.close()


def install(item,result,at):
    snapshot=result['snapshot']
    validation=fundamentals.validate(snapshot,result['documents'],item,at)
    key=fundamentals.key(item['isin']); current=store.read(key,{})
    versions=[current]+[store.read(key+'/history/'+p.stem,{}) for p in (store.DATA/key/'history').glob('*.json')]
    fields=company_review.FundamentalInput.model_fields
    existing=next((v for v in versions if v.get('validation',{}).get('status')=='passed'
                   and all(v.get('snapshot',{}).get(f)==snapshot.get(f) for f in fields)),None)
    if existing: return 'retained'
    snapshot.update(id=uuid.uuid4().hex,recorded_at=at.isoformat())
    record={'company':item,'snapshot':snapshot,'documents':result['documents'],'validation':validation,
            'score':company_review.score(snapshot,at=at),'last_pulled_at':at.isoformat(),
            'last_checked_at':at.isoformat(),'last_period_end':snapshot['period_end'],
            'next_quarter_end':fundamentals.next_quarter(snapshot['period_end']),
            'pull_status':'updated','reason':'','history_collection':'four published quarters; collected retrospectively'}
    store.write(key+'/history/'+snapshot['id'],record)
    if not current.get('snapshot') or snapshot['period_end']>=current['snapshot']['period_end']:
        store.write(key,{**current,**record})
    return 'added'


def pull(items,quarters=4,log=print,workers=3):
    all_items=store.read('universes/niftytotalmarket',{})['instruments']
    cache={}
    for path in (store.DATA/'company/filings').glob('*.json'):
        try:
            doc=json.loads(path.read_text(encoding='utf-8')); cache[doc['url']]=doc
        except (ValueError,KeyError): pass
    report={'started_at':store.now(),'quarters':quarters,'collection':'retrospective; publication and recorded timestamps retained','stocks':[]}
    def collect(item):
        row={'symbol':item['symbol'],'isin':item['isin'],'periods':[]}
        at=datetime.now(timezone.utc)
        index=filing.discover(item,at,history=True)
        targets=periods(index['sources'],quarters)
        row['status']='unavailable_index' if not targets else 'checked'
        for period in targets:
            entry={'period_end':period}
            try:
                result=filing.retrieve(item,sources_for_period(index['sources'],period),at,transport=CacheTransport(cache))
                for doc in result['documents']: cache[doc['url']]=doc
                if not result['snapshot'] or result['snapshot']['period_end']!=period:
                    entry.update(status='unavailable_metrics',validated_documents=len(result['documents']),download_failures=result['failures'])
                else: entry['status']=install(item,result,at)
            except Exception as exc:
                entry.update(status='failed',reason=str(exc) if isinstance(exc,ValueError) else type(exc).__name__)
            row['periods'].append(entry)
        time.sleep(.2)
        return row
    with fundamentals.pull_lock(), ThreadPoolExecutor(max_workers=workers) as pool:
        pending={pool.submit(collect,item):item for item in items}
        for pos,future in enumerate(as_completed(pending),1):
            try: row=future.result()
            except Exception as exc:
                row={'symbol':pending[future]['symbol'],'isin':pending[future]['isin'],
                     'status':'failed','reason':type(exc).__name__,'periods':[]}
            report['stocks'].append(row)
            if pos%10==0 or pos==len(items):
                store.write('company/fundamentals_history_pull',report)
                log(f'Quarter history {pos}/{len(items)}: {sum(p["status"]=="added" for r in report["stocks"] for p in r["periods"])} snapshots added',flush=True)
    report.update(completed_at=store.now(),coverage=fundamentals.coverage(all_items))
    store.write('company/fundamentals_history_pull',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--quarters',type=int,default=4,choices=range(1,5))
    parser.add_argument('--symbols',nargs='*')
    parser.add_argument('--workers',type=int,choices=(1,2,3),default=3)
    args=parser.parse_args()
    items=store.read('universes/niftytotalmarket',{})['instruments']
    if args.symbols: items=[i for i in items if i['symbol'] in args.symbols]
    report=pull(items,args.quarters,workers=args.workers)
    print(json.dumps(report['coverage'],indent=2))

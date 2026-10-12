"""Investor intelligence under the dashboard's existing auth/origin boundary."""
from fastapi import APIRouter
from core.research import investor_intelligence as investor, investor_workflow as workflow, investor_breakouts as breakouts, investor_database as database, jobs, store
from typing import Literal
from core.research.config import current_settings

router = APIRouter(prefix='/api/investor')

def submit_analysis(label,function,payload=None):
    return jobs.submit(label,function,payload,after_complete=database.after_job)

@router.get('/database')
def shared_history(environment: Literal['local','production']='local'):
    return database.read(dict(operation='inventory',environment=environment))

@router.get('/database/documents')
def shared_documents(environment: Literal['local','production']='local',kind: str='monitor_runs',limit: int=50,offset: int=0):
    return database.read(dict(operation='list',environment=environment,kind=kind,limit=limit,offset=offset))

@router.get('/database/document/{environment}/{kind}/{document_id}')
def shared_document(environment: Literal['local','production'],kind: str,document_id: str,sha256: str|None=None):
    return database.read(dict(operation='document',environment=environment,kind=kind,id=document_id,sha256=sha256))

@router.post('/database/sync')
def sync_database():
    return submit_analysis('Investor database sync',lambda log,job_id:database.sync(log))


def require_production():
    import os
    if os.environ.get('TRADER_ENV','local')!='production':
        raise ValueError('Investor jobs run in production: https://trader.manojmathivanan.com/#investor')


@router.get('')
def overview():
    return investor.overview(current_settings())


@router.get('/company/{isin}')
def evidence(isin: str):
    value=investor.evidence(current_settings(), isin)
    history=[]
    for path in (store.DATA/'investor/reviews').glob('*.json'):
        import json
        review=json.loads(path.read_text(encoding='utf-8'))
        if review['company']['isin']==isin:
            history.append({k:review.get(k) for k in ('id','as_of','outlook','model','full_text')})
    value['review_history']=sorted(history,key=lambda r:r['as_of'],reverse=True)[:100]
    return value


@router.post('/refresh')
def refresh(value: investor.RefreshRequest = investor.RefreshRequest()):
    cfg=current_settings()
    if value.isin:
        investor.selected_company(cfg,value.isin)
    return submit_analysis('Investor news refresh', lambda log, job_id:workflow.refresh_news(cfg,force=value.force,isin=value.isin,log=log))


@router.post('/interpret')
def interpret(value: investor.ResearchRequest):
    cfg = current_settings()
    investor.selected_company(cfg, value.isin)
    if not investor.company.llm_status()['enabled']:
        raise ValueError(investor.company.llm_status()['reason'])
    tracked=next((r for r in store.read('investor/watchlist',[]) if r['isin']==value.isin and r['kind']=='holding'),None)
    if tracked is None:
        tracked=next((r for r in workflow.paper_holdings(cfg) if r['isin']==value.isin),{})
    context=dict(thesis=tracked.get('thesis',''),entry_date=tracked.get('entry_date'),holding=bool(tracked))
    return submit_analysis('Investor interpretation',
                       lambda log, job_id:investor.interpret(cfg, value.isin, force=value.force, full_text=value.full_text, context=context, log=log), value.model_dump())


@router.post('/scan')
def scan(value: breakouts.Rules = breakouts.Rules()):
    cfg=current_settings()
    def run(log,job_id):
        store.write('investor/rules',value.model_dump())
        return dict(scan_id=breakouts.scan(cfg,value)['id'])
    return submit_analysis('Early breakout scan',run)


@router.post('/cycle')
def cycle():
    cfg=current_settings()
    return submit_analysis('Investor monitoring',lambda log,job_id:workflow.cycle(cfg,log=log))


@router.put('/tracking')
def tracking(value: workflow.TrackingInput):
    return workflow.tracking(current_settings(),value)


@router.delete('/tracking/{kind}/{isin}')
def untrack(kind: str,isin: str):
    investor.selected_company(current_settings(),isin)
    return workflow.untrack(isin,kind)


@router.put('/monitor-settings')
def settings(value: workflow.MonitorSettings):
    store.write('investor/settings',value.model_dump())
    return value.model_dump()


@router.post('/alerts/{alert_id}/acknowledge')
def acknowledge(alert_id: str):
    return workflow.acknowledge(alert_id)


@router.get('/articles/{article_id}')
def article(article_id: str):
    import re
    if not re.fullmatch('[a-f0-9]{24}',article_id):raise ValueError('Invalid article identity.')
    result=store.read('investor/full_articles/'+article_id)
    if not result:raise ValueError('Full article has not been retrieved yet.')
    return {k:v for k,v in result.items() if k!='raw_base64'}


@router.get('/reviews/{review_id}')
def review(review_id: str):
    import re
    if not re.fullmatch('[a-f0-9]{32}',review_id):raise ValueError('Invalid review identity.')
    result=store.read('investor/reviews/'+review_id)
    if not result:raise ValueError('Review not found.')
    return result

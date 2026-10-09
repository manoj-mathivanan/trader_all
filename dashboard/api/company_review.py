"""Company research routes; inherits the main application's auth/origin boundary."""
from fastapi import APIRouter, HTTPException
from core.research import company_review as research, store, jobs
from core.research import fundamentals
from core.research.config import TradingConfig, current_settings

router = APIRouter(prefix='/api/company')


def settings():
    return current_settings()


@router.get('')
def overview():
    return research.overview(settings())


@router.get('/fundamentals-history')
def fundamentals_history():
    cached = store.read('company/fundamentals_coverage')
    return cached if cached else fundamentals.coverage(store.read('universes/niftytotalmarket',{}).get('instruments',[]))


@router.get('/fundamentals/{isin}')
def stored_fundamentals(isin: str):
    return fundamentals.check(isin)


@router.get('/buy-screen/{strategy}')
def buy_screen(strategy: str):
    return fundamentals.buy_screen(strategy).model_dump()


@router.put('/buy-screen/{strategy}')
def save_buy_screen(strategy: str, value: fundamentals.BuyScreen):
    fundamentals.buy_screen(strategy)
    store.write('company/buy_screens/'+strategy,value.model_dump())
    return value.model_dump()


@router.get('/buy-check/{strategy}/{isin}')
def buy_check(strategy: str, isin: str):
    return fundamentals.buy_check(isin,strategy)


@router.post('/fundamentals-pull')
def pull_fundamentals():
    items = store.read('universes/niftytotalmarket',{}).get('instruments',[])
    if not items:
        raise ValueError('Refresh the total-market universe first.')
    return jobs.submit('Quarterly fundamentals pull',lambda log,job_id: fundamentals.pull(items,log,job_id),
                       {'universe':'niftytotalmarket','symbols':len(items)})


@router.post('/evidence')
def import_evidence(value: research.ImportInput):
    return research.import_evidence(settings(), value)


@router.get('/evidence/{isin}')
def evidence(isin: str):
    return research.company_evidence(settings(), isin)


@router.post('/scan')
def scan(value: TradingConfig):
    if 'candidate_rank' not in value.model_fields_set:
        value = value.model_copy(update={'candidate_rank':'fundamental_score'})
    return research.technical_scan(settings(), value)


@router.post('/reviews')
def create_review(value: research.ReviewRequest):
    return research.create_review(settings(), value)


@router.post('/research')
def automatic_research(value: research.AutoResearchRequest):
    if not research.llm_status()['enabled']:
        raise ValueError(research.llm_status()['reason'])
    cfg = settings()
    if not any(item['isin'] == value.isin for item in research.instruments(cfg)):
        raise ValueError('Select a company in the current universe.')
    def run(log, job_id):
        result = research.automatic_review(cfg, value, log=log)
        return dict(review_id=result['id'], symbol=result['company']['symbol'])
    return jobs.submit('Company web research', run, value.model_dump(mode='json'))


@router.get('/reviews/{review_id}')
def review(review_id: str):
    import re
    if not re.fullmatch(r'[0-9a-f]{32}', review_id):
        raise HTTPException(404, 'Review not found')
    result = store.read('company/reviews/' + review_id)
    if result is None:
        raise HTTPException(404, 'Review not found')
    return result

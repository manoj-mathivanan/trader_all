"""Run enabled indicator paper portfolios after a completed shared data refresh."""
from core.research import store, jobs
from core.portfolio import manager

KEY = 'paper_refresh_schedule'


def enabled(strategy_id='four_indicator_swing'):
    settings = store.read(KEY, {})
    return bool(settings.get('enabled') and strategy_id in settings.get('strategy_ids', []))


def run(log, job_id, refresh):
    if not job_id or not enabled() or not refresh.get('completed_at'):
        return []
    if not refresh.get('daily_symbols') or jobs.completion_status(refresh) == 'failed':
        log('Paper cycles skipped: market refresh has no usable daily data.')
        return []
    from core.portfolio import four_indicator_paper
    results = []
    for p in manager.list_portfolios('four_indicator_swing'):
        if not p['config'].get('auto_run'):
            continue
        receipt = 'paper_refresh_cycles/'+p['id']+'/'+job_id
        if store.read(receipt, {}).get('status') == 'success':
            continue
        log(f"Market refresh completed; running paper portfolio {p['config']['name']}.")
        try:
            result = four_indicator_paper.cycle(log, job_id, ingest=False, portfolio_id=p['id'])
            outcome = dict(portfolio_id=p['id'], status='success', result=result)
        except Exception as exc:
            message = str(exc) if isinstance(exc, ValueError) else jobs.failure_detail(exc)
            log(f"Paper portfolio {p['id']} needs attention: {message}")
            outcome = dict(portfolio_id=p['id'], status='failed', message=message)
        store.write(receipt, dict(outcome, at=store.now(), refresh_job_id=job_id))
        results.append(outcome)
    return results

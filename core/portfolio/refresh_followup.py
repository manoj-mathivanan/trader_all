"""Run enabled indicator paper portfolios after a completed shared data refresh."""
from core.research import store, jobs
from core.portfolio import manager

KEY = 'paper_refresh_schedule'


def enabled(strategy_id='four_indicator_swing'):
    settings = store.read(KEY, {})
    return bool(settings.get('enabled') and strategy_id in settings.get('strategy_ids', []))


def run(log, job_id, refresh):
    from core.portfolio import registry
    strategies=[s for s,plugin in registry.PLUGINS.items() if plugin.trigger_mode=='batch' and enabled(s)]
    if not job_id or not strategies or not refresh.get('completed_at'):
        return []
    if not refresh.get('daily_symbols') or jobs.completion_status(refresh) == 'failed':
        log('Paper cycles skipped: market refresh has no usable daily data.')
        return []
    from core.portfolio import four_indicator_paper, five_indicator_paper, analyst_indicator_paper, paper
    results = []
    targets=[(s,p) for s in strategies for p in manager.list_portfolios(s)]
    for strategy_id,p in targets:
        if not p['config'].get('auto_run'):
            continue
        receipt = 'paper_refresh_cycles/'+p['id']+'/'+job_id
        if store.read(receipt, {}).get('status') == 'success':
            continue
        log(f"Market refresh completed; running paper portfolio {p['config']['name']}.")
        try:
            module = {'five_indicator_swing':five_indicator_paper,'four_indicator_swing':four_indicator_paper,
                      'four_indicator_analyst':analyst_indicator_paper,'swing_patterns':paper}[strategy_id]
            result = module.cycle(log, job_id, ingest=False, portfolio_id=p['id'])
            outcome = dict(portfolio_id=p['id'], status='success', result=result)
        except Exception as exc:
            message = str(exc) if isinstance(exc, ValueError) else jobs.failure_detail(exc)
            log(f"Paper portfolio {p['id']} needs attention: {message}")
            outcome = dict(portfolio_id=p['id'], status='failed', message=message)
        store.write(receipt, dict(outcome, at=store.now(), refresh_job_id=job_id))
        results.append(outcome)
    return results

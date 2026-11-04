"""Authenticated, asynchronous target backtests using saved market data only."""
import re
from fastapi import APIRouter, HTTPException
from core.research import intraday_runs, intraday_target, store

router = APIRouter(prefix='/api/intraday')


@router.get('/backtest-options')
def options():
    return dict(stocks=[dict(symbol=i['symbol'], name=i['name']) for i in
                       sorted(intraday_target.instruments().values(), key=lambda i:i['symbol'])],
                start='2024-11-04', end='2026-11-03', capital=500000, leverage=5,
                entry_min='09:15', entry_max='15:14', exit_time='15:15', stop_loss_supported=True)


@router.get('/backtests')
def saved_backtests():
    return {'reports': intraday_runs.summaries()}


@router.post('/backtests', status_code=202)
def create_backtest(value: intraday_runs.TargetRequest):
    return intraday_runs.submit(value)


@router.get('/backtests/custom-{run_id}')
def custom_report(run_id: str):
    if not re.fullmatch(r'[a-f0-9]{12}', run_id):
        raise HTTPException(404, 'Unknown backtest.')
    report = store.read(intraday_runs.report_key('custom-'+run_id))
    if report is None:
        raise HTTPException(404, 'Backtest not found or not yet complete.')
    return report

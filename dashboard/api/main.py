"""Loopback-only research and simulated paper trading. No live broker orders."""
import os
import secrets
from pathlib import Path
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from typing import Annotated, Literal
from fastapi import Depends, FastAPI, HTTPException, Request, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from core.research import store, jobs, upstox, backtest, data_quality, market_data, sector, price_backfill
from core.research.config import Settings, DataPreferences, BacktestConfig, BearishBacktestConfig, current_settings
from core.research import bearish, momentum, scalping, strategy_presets
from core.research.strategy_presets import ScreenInput
from core.portfolio import paper, scheduler, manager as portfolios, registry as paper_plugins
from core.portfolio import scalping_paper, scalping_control
from core.strategies.registry import all_strategies
from strategies.swing_patterns.patterns.registry import definitions as pattern_definitions
from dashboard.api.company_review import router as company_review_router

WEB = Path(__file__).resolve().parents[1] / 'web'
USER = os.environ.get('DASHBOARD_ADMIN_USER', '')
PASSWORD = os.environ.get('DASHBOARD_ADMIN_PASSWORD', '')
PUBLIC_ORIGIN = os.environ.get('TRADER_PUBLIC_ORIGIN', '').rstrip('/')
ENVIRONMENT = os.environ.get('TRADER_ENV', 'local')
if ENVIRONMENT not in ('local', 'production'):
    raise RuntimeError('TRADER_ENV must be local or production.')
PAPER_ENABLED = ENVIRONMENT == 'production'
if PUBLIC_ORIGIN:
    public_url = urlsplit(PUBLIC_ORIGIN)
    if public_url.scheme != 'https' or not public_url.hostname or public_url.path or public_url.query or public_url.fragment or public_url.username:
        raise RuntimeError('TRADER_PUBLIC_ORIGIN must be an HTTPS origin without a path or credentials.')
if bool(USER) != bool(PASSWORD):
    raise RuntimeError('Configure both DASHBOARD_ADMIN_USER and DASHBOARD_ADMIN_PASSWORD.')
security = HTTPBasic(auto_error=False)


def authenticate(credentials: Annotated[HTTPBasicCredentials | None, Depends(security)]):
    if not USER:
        return  # Development only; loopback, host and origin checks are mandatory below.
    if credentials:
        user_ok = secrets.compare_digest(credentials.username.encode(), USER.encode())
        password_ok = secrets.compare_digest(credentials.password.encode(), PASSWORD.encode())
        if user_ok and password_ok:
            return
    raise HTTPException(401, 'Authentication required', headers={'WWW-Authenticate': 'Basic'})


@asynccontextmanager
async def lifespan(app):
    jobs.recover()
    scalping_control.autostart()
    stop, thread = None, None
    if PAPER_ENABLED:
        scheduler.recover_interrupted()
        stop, thread = scheduler.start()
    try:
        yield
    finally:
        if stop is not None:
            stop.set()
            thread.join(timeout=2)


app = FastAPI(title='Trader research', docs_url=None, redoc_url=None, openapi_url=None,
              dependencies=[Depends(authenticate)], lifespan=lifespan)
app.include_router(company_review_router)


@app.middleware('http')
async def local_boundary(request: Request, call_next):
    path = request.url.path
    if not PAPER_ENABLED and (path.startswith('/api/paper/') or path == '/api/jobs/paper' or
                              (path.startswith('/api/strategies/') and '/paper/' in path)):
        return JSONResponse({'detail': 'Paper trading is available only in production.'}, status_code=403)
    hosts = ('localhost', '127.0.0.1', '::1', 'testserver')
    if PUBLIC_ORIGIN:
        hosts += (urlsplit(PUBLIC_ORIGIN).hostname,)
    if request.client.host not in ('127.0.0.1', '::1', 'testclient') or request.url.hostname not in hosts:
        return JSONResponse({'detail': 'This research build is local-only.'}, status_code=403)
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('origin')
        expected_origin = PUBLIC_ORIGIN if PUBLIC_ORIGIN and request.url.hostname == urlsplit(PUBLIC_ORIGIN).hostname else str(request.base_url).rstrip('/')
        if request.headers.get('x-trader-request') != 'local-ui' or (origin and origin != expected_origin):
            return JSONResponse({'detail': 'Use the local dashboard for this action.'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.exception_handler(ValueError)
async def value_error(request, exc):
    return JSONResponse({'detail': str(exc)}, status_code=400)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Default validation errors include submitted input; never echo credentials.
    return JSONResponse({'detail': [{'loc': e['loc'], 'msg': e['msg']} for e in exc.errors()]}, status_code=422)


@app.get('/')
def index():
    return FileResponse(WEB / 'index.html')


def settings(reference_id=None):
    return current_settings(reference_id)


@app.get('/api/bootstrap')
def bootstrap():
    cfg = settings()
    universe = store.read('universes/' + cfg.universe, {})
    catalog = store.read('bar_catalog', {})
    instruments = []
    for item in universe.get('instruments', []):
        summary = catalog.get(item['isin'], {'count': 0, 'first': None, 'last': None, 'close': None, 'change': None})
        instruments.append({**item, **summary})
    return {'settings': cfg.model_dump(mode='json'), 'settings_schema': DataPreferences.model_json_schema(),
            'market_fetch': store.read('market_fetch'),
            'sector_fetch': store.read('sector/fetch'), 'sector_comparisons': store.read('sector/comparisons', [])[:20],
            'backtest_schema': BacktestConfig.model_json_schema(), 'patterns': pattern_definitions(),
            'bearish_schema': bearish.BearishConfig.model_json_schema(), 'bearish_screens': bearish.SCREENS,
            'bearish_backtest_schema': BearishBacktestConfig.model_json_schema(),
            'momentum_schema': momentum.MomentumConfig.model_json_schema(), 'momentum_sources': momentum.SOURCES,
            'scalping_schema': scalping.ScalpingConfig.model_json_schema(),
            'scalping_paper_schema': scalping_paper.ScalpingPaperConfig.model_json_schema(),
            'scalping_paper': scalping_paper.public_portfolio(), 'scalping_runner': scalping_control.status(),
            'scalping_comparisons': store.read('scalping_comparisons_index', [])[:20],
            'momentum_comparisons': store.read('momentum_comparisons_index',[])[:20],
            'environment': ENVIRONMENT, 'paper_enabled': PAPER_ENABLED,
            'paper_schema': paper.PaperConfig.model_json_schema(), 'paper_portfolio': store.read(paper.KEY) if PAPER_ENABLED else None,
            'paper_portfolios': {s['id']: scalping_paper.public_portfolio() if s['id']=='scalping' else portfolios.get(s['id']) for s in all_strategies()} if PAPER_ENABLED else {},
            'paper_schemas': {strategy_id: plugin.config_model.model_json_schema()
                              for strategy_id, plugin in paper_plugins.PLUGINS.items()},
            'screens': strategy_presets.available(), 'token_saved': store.token_saved(), 'remote_enabled': bool(PUBLIC_ORIGIN),
            'instruments': instruments, 'universe_updated': universe.get('fetched_at'),
            'jobs': store.read('jobs', [])[:100], 'runs': store.read('runs_index', []),
            'strategies': all_strategies(), 'auth_enabled': bool(USER)}


@app.put('/api/settings')
def save_settings(value: DataPreferences):
    if any(j['status'] in ('queued', 'running') for j in store.read('jobs', [])):
        raise ValueError('Wait for the active job before changing the data settings.')
    saved = settings().model_dump(mode='json')
    saved['universe'] = value.universe
    store.write('settings', saved)
    return {'saved': True}


@app.post('/api/bearish/scan')
def scan_bearish(value: bearish.BearishConfig):
    return bearish.scan(settings(), value)


class TokenInput(BaseModel):
    access_token: SecretStr = Field(min_length=20, max_length=10000)


@app.put('/api/connection')
def save_connection(value: TokenInput):
    cleaned = value.access_token.get_secret_value().strip()
    if len(cleaned) < 20:
        raise ValueError('Enter a valid access token, not whitespace.')
    store.save_token(cleaned)
    return {'saved': True, 'message': 'Token saved on the server. It will be validated on the next data fetch.'}


@app.post('/api/screens')
def save_screen(value: ScreenInput):
    import hashlib
    screen = value.model_dump(mode='json')
    screen['id'] = 'custom_' + hashlib.sha1(value.name.encode('utf-8')).hexdigest()[:10]
    screen['created_at'] = store.now()
    with store.LOCK:
        screens = [x for x in store.read('screens', []) if x.get('id') != screen['id']]
        screens.insert(0, screen)
        store.write('screens', screens[:100])
    return screen


@app.post('/api/jobs/universe')
def universe_job():
    cfg = settings()
    return jobs.submit('Refresh universe', lambda log, _: {'symbols': len(upstox.refresh_universe(cfg, log)['instruments'])}, cfg.model_dump(mode='json'))


@app.get('/api/data-quality')
def audit_price_history():
    return data_quality.audit_cached_universe(settings())


@app.post('/api/jobs/ingest')
def ingest_job():
    store.token()
    return jobs.submit('Fetch market history', lambda log, job_id: market_data.fetch(log, job_id),
                       {'universe': 'niftytotalmarket', 'daily': 'rolling year', 'five_minute': '10 calendar days'})


@app.post('/api/jobs/universe-expansion')
def universe_expansion_job(value: Settings):
    if value.universe != 'niftytotalmarket':
        raise ValueError('Universe expansion requires Nifty Total Market.')
    store.token()
    return jobs.submit('Fetch additional Total Market candles',
                       lambda log, _: upstox.ingest_expansion(value, log),
                       value.model_dump(mode='json'))


@app.post('/api/jobs/backtest')
def backtest_job(value: BacktestConfig | BearishBacktestConfig):
    cfg = settings(value.comparison_run_id)
    backtest.prepare(cfg, value)  # Return actionable validation before creating a job.
    return jobs.submit('Backtest', lambda log, job_id: backtest.run(cfg, value, log, job_id), value.model_dump(mode='json'))


@app.post('/api/jobs/backtest-history')
def backtest_history_job(value: BacktestConfig | BearishBacktestConfig):
    if value.comparison_run_id:
        raise ValueError('Comparison inputs are frozen. Use a fresh backtest for backfilling.')
    store.token()
    cfg = settings()
    return jobs.submit('Backfill daily backtest history',
                       lambda log, job_id: price_backfill.backfill(cfg, value, log, job_id),
                       value.model_dump(mode='json'))


@app.get('/api/backtest/window')
def backtest_window(warmup: int = Query(50, ge=50, le=2500)):
    return backtest.available_window(settings(), warmup)


@app.get('/api/sectors')
def sector_audit():
    return sector.audit(store.read('universes/'+settings().universe, {'instruments':[]}))


@app.post('/api/jobs/sectors')
def sector_fetch_job():
    cfg = settings()
    return jobs.submit('Sector mappings and daily indices', lambda log, job_id: sector.fetch(cfg, log, job_id), {})


class SectorComparisonInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reference_id: str = Field(pattern=r'^[0-9a-f]{12}(?:_[a-z0-9]+)?$')


@app.post('/api/jobs/sector-comparison')
def sector_comparison_job(value: SectorComparisonInput):
    cfg = settings(value.reference_id)
    reference = store.read('runs/'+value.reference_id, {})
    config = reference.get('config', {})
    if not config or reference.get('strategy_id') or config.get('entry_mode') != 'next_open' or config.get('execution_horizon','swing') != 'swing' or config.get('pattern') in dict(bearish.SCREENS):
        raise ValueError('Choose a long swing next-open backtest for sector comparison.')
    return jobs.submit('Compare sector filters', lambda log, job_id: backtest.compare_sectors(cfg, value.reference_id, log, job_id), value.model_dump())


@app.post('/api/jobs/momentum')
def momentum_job(value: momentum.MomentumConfig):
    cfg = settings(value.comparison_run_id)
    momentum.prepare(cfg, value)
    return jobs.submit('Momentum backtest', lambda log, job_id: momentum.run(cfg, value, log, job_id), value.model_dump(mode='json'))


class MomentumComparisonInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reference_id: str = Field(pattern=r'^[0-9a-f]{12}$')
    suite: Literal['refinements','research','stronger','indicators','pullbacks','fundamentals'] = 'refinements'


@app.post('/api/jobs/momentum-comparison')
def momentum_comparison_job(value: MomentumComparisonInput):
    cfg = settings(value.reference_id)
    reference = store.read('runs/'+value.reference_id)
    if not reference or reference.get('strategy_id')!='intraday_momentum':
        raise ValueError('Choose a saved momentum experiment.')
    momentum.prepare(cfg,momentum.MomentumConfig(**{**reference['config'],'comparison_run_id':value.reference_id}))
    return jobs.submit('Momentum comparison',lambda log,job_id:momentum.compare(cfg,value.reference_id,log,job_id,value.suite),value.model_dump())


@app.post('/api/momentum/coverage')
def momentum_coverage(value: momentum.MomentumConfig):
    universe, datasets, _, excluded = momentum.prepare(settings(value.comparison_run_id), value)
    _, plan = momentum.entry_plan(datasets, value)
    instruments = {x['symbol']:x for x in universe['instruments']}
    requests = {(x['symbol'],d) for d, candidates in plan.items() for x in candidates}
    if value.comparison_run_id:
        frozen = store.read('run_intraday/'+value.comparison_run_id,{})
        ready = sum(bool(frozen.get(s,{}).get(d)) for s,d in requests)
    else:
        ready = sum((store.DATA/(intraday_data_key(instruments[s]['isin'],d)+'.json')).exists() for s,d in requests)
    return dict(stock_sessions=len(requests), cached=ready, missing=len(requests)-ready, excluded=excluded,
                source='frozen reference' if value.comparison_run_id else 'shared cache')


@app.post('/api/jobs/scalping')
def scalping_job(value: scalping.ScalpingConfig):
    cfg = settings(value.comparison_run_id)
    scalping.prepare(cfg, value)
    return jobs.submit('Scalping backtest', lambda log, job_id: scalping.run(cfg, value, log, job_id), value.model_dump(mode='json'))


@app.post('/api/scalping/coverage')
def scalping_coverage(value: scalping.ScalpingConfig):
    return scalping.coverage(settings(value.comparison_run_id), value)


class ScalpingComparisonInput(BaseModel):
    model_config = {'extra': 'forbid'}
    reference_id: str = Field(..., pattern=r'^[0-9a-f]{12}$')


@app.post('/api/jobs/scalping-comparison')
def scalping_comparison_job(value: ScalpingComparisonInput):
    cfg = settings(value.reference_id)
    reference = store.read('runs/'+value.reference_id)
    if not reference or reference.get('strategy_id') != 'scalping':
        raise ValueError('Choose a saved scalping experiment.')
    scalping.prepare(cfg, scalping.ScalpingConfig(**{**reference['config'], 'comparison_run_id': value.reference_id}))
    return jobs.submit('Scalping confirmation comparison', lambda log, job_id: scalping.compare(cfg, value.reference_id, log, job_id), value.model_dump())


@app.get('/api/scalping/paper/portfolio')
def get_scalping_paper():
    return scalping_paper.public_portfolio()


@app.get('/api/scalping/paper/export')
def export_scalping_paper():
    portfolio = portfolios.get('scalping')
    if not portfolio:
        raise HTTPException(404,'Create a scalping paper portfolio first.')
    return portfolio


@app.post('/api/scalping/paper/portfolio')
def create_scalping_paper(value: scalping_paper.ScalpingPaperConfig):
    scalping_paper.save(value,settings(),create=True)
    if value.auto_run:
        scalping_control.start()
    return scalping_paper.public_portfolio()


@app.put('/api/scalping/paper/portfolio')
def update_scalping_paper(value: scalping_paper.ScalpingPaperConfig):
    scalping_paper.save(value,settings())
    if value.auto_run:
        scalping_control.start()
    return scalping_paper.public_portfolio()


class ScalpingPaperStatus(BaseModel):
    status: Literal['active','paused']


@app.put('/api/scalping/paper/status')
def scalping_status(value: ScalpingPaperStatus):
    scalping_paper.set_status(value.status)
    return scalping_paper.public_portfolio()


@app.get('/api/scalping/paper/runner')
def scalping_runner_status():
    return scalping_control.status()


@app.post('/api/scalping/paper/start')
def start_scalping_runner():
    return scalping_control.start()


@app.post('/api/scalping/paper/stop')
def stop_scalping_runner():
    return scalping_control.stop()


def intraday_data_key(isin, day):
    from core.research.intraday_data import cache_key
    return cache_key(isin, day)


@app.post('/api/paper/portfolio')
def create_paper(value: paper.PaperConfig):
    return paper.save(value, settings(), create=True)


@app.put('/api/paper/portfolio')
def update_paper(value: paper.PaperConfig):
    return paper.save(value, settings())


class PaperStatus(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['active', 'paused']


@app.put('/api/paper/status')
def paper_status(value: PaperStatus):
    return paper.set_status(value.status)


@app.post('/api/jobs/paper')
def paper_job():
    if not store.read(paper.KEY):
        raise ValueError('Create a paper portfolio first.')
    store.token()
    return jobs.submit('Paper daily cycle', paper.cycle, {'portfolio_id': 'swing_patterns', 'trigger': 'manual'})


def paper_config(strategy_id, value):
    portfolios.key(strategy_id)
    plugin = paper_plugins.get_plugin(strategy_id)
    try:
        return plugin.config_model.model_validate(value)
    except ValueError:
        raise HTTPException(422, 'Invalid paper settings. Check the fields and acknowledge the limitations.') from None


@app.get('/api/strategies/{strategy_id}/paper/portfolio')
def get_strategy_portfolio(strategy_id: str):
    return portfolios.get(strategy_id)


@app.post('/api/strategies/{strategy_id}/paper/portfolio')
def create_strategy_portfolio(strategy_id: str, value: dict):
    config = paper_config(strategy_id, value)
    if strategy_id=='scalping':
        return create_scalping_paper(config)
    return portfolios.save(strategy_id, config, settings(), create=True, clock=paper.local_now())


@app.put('/api/strategies/{strategy_id}/paper/portfolio')
def update_strategy_portfolio(strategy_id: str, value: dict):
    config = paper_config(strategy_id, value)
    if strategy_id=='scalping':
        return update_scalping_paper(config)
    return portfolios.save(strategy_id, config, settings(), clock=paper.local_now())


@app.put('/api/strategies/{strategy_id}/paper/status')
def update_strategy_status(strategy_id: str, value: PaperStatus):
    paper_plugins.get_plugin(strategy_id)
    if strategy_id=='scalping':
        return scalping_status(ScalpingPaperStatus(status=value.status))
    return portfolios.set_status(strategy_id, value.status)


@app.post('/api/strategies/{strategy_id}/paper/cycle')
def strategy_paper_job(strategy_id: str):
    plugin = paper_plugins.get_plugin(strategy_id)
    if not portfolios.get(strategy_id):
        raise ValueError('Create a paper portfolio for this strategy first.')
    store.token()
    return jobs.submit('Paper daily cycle', plugin.run_cycle,
                       {'portfolio_id': strategy_id, 'strategy_id': strategy_id, 'trigger': 'manual'})


@app.get('/api/bars/{isin}')
def bars(isin: str):
    if not isin.isalnum() or len(isin) != 12:
        raise HTTPException(404)
    record = store.read('bars/' + isin)
    if not record:
        raise HTTPException(404, 'Fetch daily data for this instrument first.')
    return record


@app.get('/api/runs/{run_id}')
def run_result(run_id: str):
    if len(run_id) != 12 or not all(c in '0123456789abcdef' for c in run_id):
        raise HTTPException(404)
    result = store.read('runs/' + run_id)
    if not result:
        raise HTTPException(404)
    return result


@app.get('/api/jobs/{job_id}')
def job_detail(job_id: str):
    if len(job_id) != 12 or not all(c in '0123456789abcdef' for c in job_id):
        raise HTTPException(404)
    job = next((j for j in store.read('jobs', []) if j['id'] == job_id), None)
    if not job:
        raise HTTPException(404, 'Job record unavailable.')
    return job


@app.get('/api/runs/{run_id}/trades/{trade_index}/chart')
def trade_chart(run_id: str, trade_index: int):
    """Use the run's frozen candles and original ledger index, never today's cache."""
    result = run_result(run_id)
    trades = result.get('trades', [])
    if trade_index < 0 or trade_index >= len(trades):
        raise HTTPException(404, 'Trade not found in this backtest.')
    trade = trades[trade_index]
    if result.get('strategy_id') == 'scalping':
        sessions = store.read('run_intraday/'+run_id)
        if not sessions or scalping.digest(sessions) != result['intraday_source']['sha256']:
            raise HTTPException(404, 'Frozen scalping candles are unavailable or changed.')
        return {'run_id':run_id, 'trade_index':trade_index, 'symbol':trade['symbol'], 'trade':trade,
                'trades':[dict(t, trade_index=i) for i, t in enumerate(trades) if t['symbol'] == trade['symbol'] and t['entry_date'] == trade['entry_date']],
                'interval_minutes':1, 'source':'frozen_intraday_snapshot', **scalping.trade_chart(result, trade, sessions)}
    if result.get('strategy_id') == 'intraday_momentum':
        minutes = store.read('run_intraday/' + run_id, {}).get(trade['symbol'], {}).get(trade['entry_date'], [])
        if not minutes:
            raise HTTPException(404, 'Frozen momentum candles are unavailable.')
        return {'run_id':run_id, 'trade_index':trade_index, 'symbol':trade['symbol'], 'trade':trade,
                'trades':[dict(trade, trade_index=trade_index)], 'interval_minutes':5,
                'source':'frozen_intraday_snapshot', **momentum.trade_chart(result, trade, minutes)}
    stock_trades = [dict(t, trade_index=i) for i, t in enumerate(trades)
                    if t['symbol'] == trade['symbol']]
    datasets = store.read('run_data/' + run_id, {})
    bars = [b for b in datasets.get(trade['symbol'], [])
            if b['date'] <= result['config']['end']]
    dates = {b['date']: i for i, b in enumerate(bars)}
    if any(t['entry_date'] not in dates or t['exit_date'] not in dates for t in stock_trades):
        raise HTTPException(404, 'The saved candles for this trade are unavailable. No current-data substitute was used.')
    first, last = dates[trade['entry_date']], dates[trade['exit_date']]
    from core.research.trade_chart import explain_trade
    explanation = explain_trade(result, datasets, trade, bars, first, last)
    if trade.get('execution_horizon') == 'intraday':
        minute_inputs = store.read('run_intraday/' + run_id, {})
        minutes = minute_inputs.get(trade['symbol'], {}).get(trade['entry_date'], [])
        if not minutes:
            raise HTTPException(404, 'Frozen five-minute candles are unavailable; daily candles cannot substitute.')
        allowed = {'trigger','initial_stop','activation','target','protective_stop'}
        explanation['series'] = [s for s in explanation['series'] if s['id'] in allowed]
        for series in explanation['series']:
            if series['id'] == 'protective_stop':
                series['label'] = 'Recorded active stop'
        explanation['notices'] = [n for n in explanation['notices'] if 'reconstructed stop' not in n.lower() and 'active stop is reconstructed' not in n.lower()]
        levels = explanation.pop('bars')[first]['chart_values']
        trace = {x['timestamp']:x['stop'] for x in trade.get('stop_trace', [])}
        enriched = []
        for b in minutes:
            values = {k:v for k,v in levels.items() if k in allowed and k!='protective_stop'} if trade['entry_timestamp']<=b['timestamp']<=trade['exit_timestamp'] else {}
            if b['timestamp'] in trace:
                values['protective_stop'] = trace[b['timestamp']]
            enriched.append(dict(b, chart_values=values))
        explanation['notices'].append('Five-minute chart. Signal checks use the previous completed daily session; stop/target fills identify a candle interval. The cutoff exit uses its bar open.')
        return {'run_id': run_id, 'trade_index': trade_index, 'symbol': trade['symbol'], 'trade': trade,
                'bars': enriched, 'explanation': explanation, 'interval_minutes': 5,
                'source': 'frozen_intraday_snapshot'}
    enriched = explanation.pop('bars')
    earliest = min(dates[t['entry_date']] for t in stock_trades)
    latest = max(dates[t['exit_date']] for t in stock_trades)
    return {'run_id': run_id, 'trade_index': trade_index, 'symbol': trade['symbol'],
            'trade': trade, 'trades': stock_trades,
            'bars': enriched[max(0, earliest - 60):latest + 21],
            'explanation': explanation,
            'source': 'frozen_backtest_snapshot'}


app.mount('/static', StaticFiles(directory=WEB), name='static')

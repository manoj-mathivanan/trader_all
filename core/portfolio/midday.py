"""Swing shadow execution at observed midday quotes, never past opening prices.

Signals use completed daily sessions. Exits are sampled at cycle time, rather
than assumed intraday stop fills; quote times and that limitation are persisted.
"""
import math
from copy import deepcopy
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from urllib.parse import urlencode
import httpx
from core.execution.paper import PaperBrokerAdapter
from core.portfolio import manager, paper
from core.research import backtest, corporate_actions, data_quality, fundamentals, market_history, store, upstox
from core.research.fundamental_history import rank_key
from core.research.relative_strength import StrengthHistory
from core.research.sector_breadth import SectorBreadth
from core.risk.position_sizer import percent_risk_size

NOTICE = 'Midday entries and exits use observed bid/ask quotes with modeled slippage and fees. Stops are checked at cycle time, not continuously; missed sessions are not replayed as fills.'


def quotes(items):
    if not items:
        return {}
    token = store.token()
    result = {}
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        for offset in range(0, len(items), 400):
            batch = items[offset:offset + 400]
            url = 'https://api.upstox.com/v2/market-quote/quotes?' + urlencode({'instrument_key': ','.join(i['key'] for i in batch)})
            payload = upstox.get(client, url, headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}).json()
            if payload.get('status') != 'success':
                raise ValueError('Provider did not return successful midday quotes.')
            by_key = {q.get('instrument_token'): q for q in payload.get('data', {}).values()}
            for item in batch:
                q = by_key.get(item['key'])
                if q is not None:
                    result[item['symbol']] = q
    return result


def usable_quote(q, clock):
    try:
        stamp = str(q['timestamp'])
        observed = datetime.fromtimestamp(float(stamp) / 1000, paper.IST) if stamp.replace('.', '', 1).isdigit() else datetime.fromisoformat(stamp)
        if observed.tzinfo is None:
            return False
        observed = observed.astimezone(paper.IST)
        traded = datetime.fromtimestamp(int(q['last_trade_time']) / 1000, paper.IST)
        bid, ask = q['depth']['buy'][0], q['depth']['sell'][0]
        prices = [float(q['last_price']), float(bid['price']), float(ask['price'])]
        return (all(math.isfinite(p) and p > 0 for p in prices)
                and prices[1] <= prices[2] and int(bid['quantity']) > 0 and int(ask['quantity']) > 0
                and observed.date() == clock.date() and traded.date() == clock.date()
                and 0 <= (clock - observed).total_seconds() <= 60
                and 0 <= (clock - traded).total_seconds() <= 60)
    except (KeyError, ValueError, TypeError, IndexError, OverflowError):
        return False


def execute(portfolio, cfg, data, checks, quote_map, clock, job_id):
    """Pure ledger transition. Only fresh observed quotes can create fills."""
    portfolio = deepcopy(portfolio)
    day = clock.date().isoformat()
    if portfolio.get('last_midday_session') == day:
        return portfolio, {'sessions': 0, 'orders': 0, 'reason': 'Midday session already committed'}
    ledger = portfolio.setdefault('ledger', {})
    for key, default in [('cash', cfg.capital), ('positions', {}), ('marks', {}), ('orders', []), ('trades', []), ('curve', []), ('peak', cfg.capital), ('max_dd', 0), ('total_fees', 0), ('total_slippage', 0)]:
        ledger.setdefault(key, default)
    positions, marks = ledger['positions'], ledger['marks']
    instruments = {i['symbol']: i for i in portfolio['universe_snapshot']['instruments']}
    broker = PaperBrokerAdapter(cfg)
    audit, exited = [], set()
    fresh = {s: q for s, q in quote_map.items() if usable_quote(q, clock)}
    stale_held = sorted(set(positions) - set(fresh))
    if stale_held:
        raise ValueError('Fresh quotes missing for held stocks; portfolio unchanged: ' + ', '.join(stale_held))
    def order(s, side, qty, raw, reason):
        fill = broker.fill(raw, qty, side, day=day)
        ledger['total_fees'] += fill['fees']
        ledger['total_slippage'] += fill['slippage']
        ledger['orders'].append(dict(id=f'{portfolio["id"]}:{day}:{s}:{side}', symbol=s, side=side, quantity=qty,
                                     price=fill['price'], fees=fill['fees'], date=day, at=clock.isoformat(),
                                     mode='paper', status='simulated', portfolio_id=portfolio['id'], job_id=job_id,
                                     reason=reason, quote=quote_map[s], **({'charges': fill['charges']} if 'charges' in fill else {})))
        return fill
    before = len(ledger['orders'])
    for s in sorted(list(positions)):
        p, q = positions[s], fresh[s]
        rows = corporate_actions.adjusted_bars(data[s], data[s][-1]['date'])
        exit_cfg = SimpleNamespace(**{**cfg.model_dump(), **p.get('exit_config', {})})
        after_entry = [b for b in rows if b['date'] >= p['entry_date'] and b['date'] > p.get('last_close_update', '')]
        reason = None
        # Completed close-based rules update protection before this quote; no
        # full-day low or morning open is used to pretend a prior execution.
        for b in after_entry:
            p['age'] += 1
            p['best_close'] = max(p['best_close'], b['close'])
            target = {'take_8': 8, 'take_15': 15, 'take_25': 25}.get(exit_cfg.winner_exit)
            if b['close'] >= p['entry'] * (1 + exit_cfg.stop_pct / 100 * exit_cfg.breakeven_r):
                if cfg.fee_model == 'zerodha_equity':
                    from core.execution.zerodha import breakeven_price
                    be = breakeven_price(p['entry_cost'], p['quantity'], day, cfg.slippage_bps)
                else:
                    be = p['entry_cost'] / p['quantity'] / ((1 - cfg.sell_cost_bps / 10000) * (1 - cfg.slippage_bps / 10000))
                if target and b['close'] >= p['entry'] * (1 + target / 100):
                    reason = f'Completed close target +{target}% (observed midday exit)'
                elif exit_cfg.winner_exit in ('trail_50d', 'trail_30w'):
                    length = 150 if exit_cfg.winner_exit == 'trail_30w' else 50
                    prefix = [r for r in rows if r['date'] <= b['date']]
                    if len(prefix) >= length:
                        p['stop'] = max(p['stop'], be, sum(r['close'] for r in prefix[-length:]) / length)
                else:
                    p['stop'] = max(p['stop'], be, p['best_close'] * (1 - exit_cfg.trail_pct / 100))
            p['last_close_update'] = b['date']
        bid = float(q['depth']['buy'][0]['price'])
        marks[s] = bid
        if bid <= p['stop']:
            reason = 'Stop observed at midday quote'
        elif p['age'] >= exit_cfg.max_hold_days:
            reason = 'Holding limit (observed midday exit)'
        if reason:
            if int(q['depth']['buy'][0]['quantity']) < p['quantity']:
                audit.append(dict(symbol=s, reason='Insufficient displayed bid quantity; exit deferred'))
                continue
            fill = order(s, 'sell', p['quantity'], bid, reason)
            proceeds = fill['price'] * p['quantity'] - fill['fees']
            ledger['cash'] += proceeds
            ledger['trades'].append(dict(symbol=s, entry_date=p['entry_date'], entry_at=p['entry_at'], exit_date=day,
                                         exit_at=clock.isoformat(), entry=p['entry'], exit=fill['price'], quantity=p['quantity'],
                                         pnl=proceeds - p['entry_cost'], r=(proceeds - p['entry_cost']) / p['initial_risk'],
                                         fees=p['entry_fee'] + fill['fees'], reason=reason))
            del positions[s]
            exited.add(s)
    signal_day = min(rows[-1]['date'] for rows in data.values())
    strength = StrengthHistory(data)
    breadth = SectorBreadth(data, list(instruments.values()), cfg.market_breadth_pct, cfg.market_min_coverage_pct)
    candidates = []
    for s, rows in data.items():
        i = len(rows) - 1
        if s not in positions and s not in exited and rows[-1]['date'] == signal_day and i >= backtest.required_warmup(cfg) and backtest.signal(corporate_actions.adjusted_bars(rows, signal_day), i, cfg):
            candidates.append(s)
    if cfg.candidate_rank == 'fundamental_score':
        candidates.sort(key=lambda s: rank_key(checks[s], s))
    elif cfg.candidate_rank == 'rs_126':
        rating = strength.ratings(signal_day, 126)
        candidates.sort(key=lambda s: (-rating.get(s, -1), s))
    else:
        candidates.sort()
    for s in candidates:
        q = fresh.get(s)
        denial = None
        if portfolio['status'] != 'active':
            denial = 'Entries paused'
        elif not checks[s]['buy_allowed']:
            denial = '; '.join(checks[s]['block_reasons'])
        elif cfg.skip_weak_markets and not breadth.decision(s, signal_day)['allowed']:
            denial = breadth.decision(s, signal_day)['reason']
        elif cfg.min_rs_rating and strength.ratings(signal_day, 126).get(s, -1) < cfg.min_rs_rating:
            denial = '126-session RS below threshold'
        elif not strength.passes(s, signal_day, cfg):
            denial = 'Emerging RS below threshold'
        elif q is None:
            denial = 'Missing or stale bid/ask quote'
        elif len(positions) >= cfg.max_positions:
            denial = 'Portfolio full'
        elif cfg.max_sector_positions and sum(instruments[h]['sector'] == instruments[s]['sector'] for h in positions) >= cfg.max_sector_positions:
            denial = 'Sector position limit'
        if denial:
            audit.append(dict(symbol=s, signal_date=signal_day, reason=denial))
            continue
        raw = float(q['depth']['sell'][0]['price'])
        fill_price = raw * (1 + cfg.slippage_bps / 10000)
        stop = fill_price * (1 - cfg.stop_pct / 100)
        equity = ledger['cash'] + sum(p['quantity'] * marks[h] for h, p in positions.items())
        qty = min(percent_risk_size(equity, ledger['cash'], fill_price, stop, cfg, day=day), int(q['depth']['sell'][0]['quantity']))
        if qty < 1:
            audit.append(dict(symbol=s, signal_date=signal_day, reason='Insufficient sizing capacity'))
            continue
        fill = order(s, 'buy', qty, raw, 'Previous completed session signal, observed midday ask')
        cost = fill['price'] * qty + fill['fees']
        ledger['cash'] -= cost
        positions[s] = dict(entry=fill['price'], entry_date=day, entry_at=clock.isoformat(), entry_cost=cost,
                            entry_fee=fill['fees'], quantity=qty, stop=stop, best_close=fill['price'], age=0,
                            initial_risk=qty * (fill['price'] - stop), exit_config=cfg.model_dump(mode='json'))
        marks[s] = float(q['depth']['buy'][0]['price'])
    equity = ledger['cash'] + sum(p['quantity'] * marks[s] for s, p in positions.items())
    ledger['peak'] = max(ledger['peak'], equity)
    ledger['max_dd'] = max(ledger['max_dd'], (ledger['peak'] - equity) / ledger['peak'] * 100)
    ledger['curve'].append(dict(date=day, at=clock.isoformat(), equity=round(equity, 2)))
    ledger['last_session'] = day
    portfolio.update(last_midday_session=day, updated_at=store.now(), metrics=dict(final_equity=equity,
                     return_pct=(equity / cfg.capital - 1) * 100, max_drawdown_pct=ledger['max_dd'], trade_count=len(ledger['trades'])))
    portfolio['cycles'].append(dict(job_id=job_id, at=clock.isoformat(), start=day, end=day, sessions=1,
                                    order_count=len(ledger['orders']) - before, config=cfg.model_dump(mode='json'),
                                    signal_date=signal_day, candidate_checks=audit, notice=NOTICE))
    return portfolio, dict(portfolio_id=portfolio['id'], sessions=1, orders=len(ledger['orders']) - before)


def cycle(log, job_id, *, portfolio_id=None, ingest=True):
    portfolio = manager.get('swing_patterns', portfolio_id)
    if not portfolio:
        raise ValueError('Create a paper scenario first.')
    cfg = paper.PaperConfig(**portfolio['config'])
    clock = paper.local_now()
    scheduled = time(cfg.run_hour, cfg.run_minute)
    if clock.weekday() >= 5 or not scheduled <= clock.time() < time(15, 15):
        log('No midday execution outside the configured regular-session window.')
        return {'sessions': 0, 'orders': 0}
    day = clock.date().isoformat()
    if day < portfolio['start_session'] or portfolio.get('last_midday_session') == day:
        return {'sessions': 0, 'orders': 0}
    through = clock.date() - timedelta(days=1)
    while through.weekday() >= 5:
        through -= timedelta(days=1)
    if ingest:
        upstox.ingest(paper.PaperIngestionRange(universe=portfolio['universe'], start=date.fromisoformat(portfolio['history_start']), end=through), log,
                      universe=portfolio['universe_snapshot'], extend_history=False)
    items = portfolio['universe_snapshot']['instruments']
    data, fingerprints = {}, {}
    reference = market_history.evidence(snapshot=True)
    previous = portfolio.get('history_reference')
    if previous and previous != reference:
        raise ValueError('Midday history evidence changed; review before resuming.')
    for item in items:
        record = store.read('bars/' + item['isin'], {})
        if not record.get('bars') or record.get('requested_end', '') < through.isoformat():
            raise ValueError('Incomplete completed daily history: ' + item['symbol'])
        old_through = portfolio.get('history_through')
        if old_through and paper.digest(record['bars'], old_through) != portfolio['fingerprints'].get(item['symbol']):
            raise ValueError('Observed history revised: ' + item['symbol'])
        rows, _ = market_history.prepare(item, record, reference=reference, fingerprint=False)
        rows = [b for b in rows if b['date'] <= through.isoformat()]
        if not rows:
            raise ValueError('No eligible history: ' + item['symbol'])
        data[item['symbol']] = rows
    latest = max(rows[-1]['date'] for rows in data.values())
    if any(rows[-1]['date'] != latest for rows in data.values()):
        raise ValueError('Universe has mismatched completed sessions; portfolio unchanged.')
    quality = data_quality.audit(data, end=through.isoformat())
    if quality['excluded_symbols']:
        raise ValueError('Unresolved daily price anomalies; portfolio unchanged.')
    held = set(portfolio['ledger'].get('positions', {}))
    candidates = {s for s, rows in data.items() if len(rows) > backtest.required_warmup(cfg) and backtest.signal(corporate_actions.adjusted_bars(rows, latest), len(rows) - 1, cfg)}
    selected = candidates | held
    if not selected:
        log('No qualifying completed-session signals or open positions; no quote fills required.')
        return {'sessions': 0, 'orders': 0}
    # Financial evidence is evaluated at today's decision time, never a future close.
    screen = fundamentals.BuyScreen(**portfolio['fundamental_screen']) if portfolio.get('fundamental_screen') else fundamentals.buy_screen('swing_patterns')
    checks = {i['symbol']: fundamentals.buy_check(i['isin'], 'swing_patterns', at=clock, screen=screen) for i in items if i['symbol'] in candidates}
    quote_map = quotes([i for i in items if i['symbol'] in selected])
    clock = paper.local_now()
    if clock.time() >= time(15, 15):
        raise ValueError('Data preparation exceeded the execution window; no fills committed.')
    if selected and not any(usable_quote(q, clock) for q in quote_map.values()):
        raise ValueError('No fresh regular-session quotes; no fills or session committed.')
    updated, result = execute(portfolio, cfg, data, checks, quote_map, clock, job_id)
    updated.update(history_reference=reference, history_through=latest,
                   fingerprints={i['symbol']: paper.digest(store.read('bars/' + i['isin'])['bars'], latest) for i in items})
    store.write(manager.key('swing_patterns', portfolio_id), updated)
    log(f"Committed midday scenario {portfolio['id']}: {result['orders']} simulated fills. {NOTICE}")
    return result

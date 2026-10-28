"""Explicitly armed, forward-only long swing execution with durable broker reconciliation."""
import math
import threading
from contextvars import copy_context
from core.research import identity
from datetime import date, datetime, timedelta, timezone, time
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, create_model
from core.execution.upstox_live import Broker, BrokerError, positive, quote_price, limit_price
from core.portfolio.locking import mutex
from core.research import store, backtest, market_history, data_quality, corporate_actions, fundamentals
from core.research.config import TradingConfig, current_settings

IST = timezone(timedelta(hours=5, minutes=30))
FILTER_KEYS = ('pattern', 'base_days', 'max_depth_pct', 'volume_multiple', 'sma_days', 'require_long_trend',
               'require_rising_long_trend', 'min_turnover', 'vcp_window_days', 'vcp_volume_multiple',
               'blue_sky_lookback_days', 'multiyear_base_days', 'multiyear_max_depth_pct', 'ipo_max_age_days')
LiveFilters = create_model('LiveFilters', __config__=ConfigDict(extra='forbid', allow_inf_nan=False),
                          **{key: (TradingConfig.model_fields[key].annotation, TradingConfig.model_fields[key])
                             for key in FILTER_KEYS})


class LiveConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    filters: LiveFilters = Field(default_factory=lambda: LiveFilters(pattern='vcp'))
    capital: float = Field(100000, ge=1000, le=1e9, title='Allocated capital (₹)')
    risk_pct: float = Field(.5, gt=0, le=5, title='Risk per trade (%)')
    stop_pct: float = Field(8, gt=0, le=30, title='Stop below average fill (%)')
    max_positions: int = Field(5, ge=1, le=30, title='Maximum managed positions')
    max_order_value: float = Field(20000, ge=100, le=1e8, title='Maximum buy order value (₹)')
    max_daily_buy_value: float = Field(50000, ge=100, le=1e9, title='Maximum daily buy commitments (₹)')
    max_daily_loss: float = Field(2000, gt=0, le=1e8, title='Daily managed loss: pause new buys (₹)')
    max_entry_gap_pct: float = Field(3, ge=0, le=20, title='Maximum deviation from signal close (%)')
    winner_exit: Literal['take_8', 'take_15', 'take_25', 'trail_pct', 'trail_50d', 'trail_30w'] = Field('trail_50d', title='Winner exit')
    trail_pct: float = Field(8, gt=0, le=30, title='Trail below observed best price (%)')
    breakeven_r: float = Field(1, ge=.1, le=10, title='Breakeven trigger (R)')
    max_hold_days: int = Field(120, ge=1, le=1000, title='Maximum holding sessions')
    protection_bps: int = Field(50, ge=1, le=200, title='Limit price protection (bps)')
    order_ttl_seconds: int = Field(60, ge=15, le=300, title='Cancel unfilled order after seconds')


class Connection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_user_id: str = Field('', max_length=80, pattern=r'^[A-Za-z0-9_-]*$', title='Expected Upstox user ID')
    algo_name: str = Field('', max_length=100, pattern=r'^[A-Za-z0-9 _.-]*$', title='Upstox registered algo name (if applicable)')
    static_ip_confirmed: bool = Field(False, title='This server uses an IP registered with Upstox')
    delivery_sell_authorized: bool = Field(False, title='Delivery sells are authorized in Upstox (DDPI / applicable authorization)')


_thread = None
_stop = threading.Event()
_guard = threading.RLock()
_runners = {}

def stop_event():
    if not identity.username():
        return _stop
    with _guard:
        return _runners.setdefault(identity.username(), {'stop': threading.Event(), 'thread': None})['stop']

TERMINAL = {'complete', 'cancelled', 'rejected', 'not_placed'}


def clock():
    return datetime.now(IST)


def ledger():
    return store.read('live/ledger', {'account_id': None, 'orders': [], 'positions': {}, 'realized_pnl': 0, 'daily_baselines': {}})


def running():
    try:
        with mutex('live_runner', timeout=0):
            return False
    except ValueError:
        return True


def public_state():
    account = store.read('live/account')
    state = ledger()
    if account:
        marks = {r['instrument_token']: r for r in account['holdings'] + account['positions'] if r.get('instrument_token')}
        for key, position in state['positions'].items():
            mark = marks.get(key, {})
            position.update(current_price=mark.get('current_price'), quote_at=mark.get('quote_at'), quote_fresh=mark.get('quote_fresh', False))
        state['unrealized_pnl'] = (sum((p['current_price'] - p['average_price']) * p['quantity'] for p in state['positions'].values())
                                   if all(p['current_price'] is not None for p in state['positions'].values()) else None)
    return {'config': store.read('live/config', LiveConfig().model_dump(mode='json')),
            'connection': store.read('live/connection', Connection().model_dump()),
            'schema': LiveConfig.model_json_schema(), 'filters_schema': LiveFilters.model_json_schema(),
            'connection_schema': Connection.model_json_schema(), 'running': running(),
            'paused': store.read('live/control', {}).get('paused', False),
            'runner': store.read('live/runner', {}), 'ledger': state, 'account': account}


def save_config(value):
    with mutex('live_control', timeout=30):
        state = ledger()
        committed = sum(p['quantity'] * p['average_price'] for p in state['positions'].values())
        committed += sum((o['quantity'] - o.get('filled_quantity', 0)) * o['price'] for o in state['orders']
                         if o['side'] == 'BUY' and o['status'] not in TERMINAL)
        if value.capital < committed:
            raise ValueError('Allocated capital cannot be less than managed holdings and pending buy commitments.')
        store.write('live/config', value.model_dump(mode='json'))
    return public_state()


def save_connection(value):
    with mutex('live_control', timeout=30):
        if running():
            raise ValueError('Stop the live runner before changing its broker connection.')
        if ledger()['account_id'] and value.expected_user_id != ledger()['account_id']:
            raise ValueError('The live ledger is bound to its original Upstox account.')
        store.write('live/connection', value.model_dump())
        store.write('live/account', None)
    return public_state()


def connection_change():
    if running():
        raise ValueError('Stop the live runner before replacing your trading token.')
    store.write('live/account', None)


def verify_account(broker, *, require_setup=False):
    profile = broker.profile()
    user_id = profile.get('user_id')
    connection = Connection(**store.read('live/connection', {}))
    if not user_id:
        raise ValueError('Upstox did not return an account identity.')
    bound = ledger()['account_id']
    if (bound and bound != user_id) or (connection.expected_user_id and connection.expected_user_id != user_id):
        raise ValueError('Upstox account differs from the configured account or managed ledger. Orders blocked.')
    if require_setup:
        if not connection.expected_user_id or not connection.static_ip_confirmed or not connection.delivery_sell_authorized:
            raise ValueError('Configure the expected account, registered static IP and delivery sell authorization in Settings.')
        if profile.get('is_active') is False:
            raise ValueError('The Upstox account is inactive.')
    return {'user_id': user_id, 'user_name': profile.get('user_name', '')}


def mark_rows(rows, quotes, now, *, holdings=False):
    result = []
    for row in rows:
        key = row.get('instrument_token', '')
        quote = quotes.get(key, {})
        price = quote_price(quote, now, fresh=False)
        quantity = float(row.get('quantity') or 0)
        average = float(row.get('average_price') or 0)
        # Holdings and today's positions have overlapping quantities; display separately.
        pnl = ((price - average) * quantity * (1 if holdings else float(row.get('multiplier') or 1))
               if price is not None else None)
        result.append({**row, 'current_price': price, 'quote_at': quote.get('timestamp'),
                       'quote_fresh': quote_price(quote, now) is not None, 'current_unrealized_pnl': pnl})
    return result


def refresh_account(broker=None, *, now=None):
    if broker is None:
        with Broker() as client:
            return refresh_account(client, now=now)
    now = now or clock()
    profile = verify_account(broker)
    holdings = broker.get('/v2/portfolio/long-term-holdings')
    positions = broker.get('/v2/portfolio/short-term-positions')
    orders = broker.orders()
    trades = broker.get('/v2/order/trades/get-trades-for-day')
    funds = broker.get('/v2/user/get-funds-and-margin', segment='SEC')
    quotes = broker.quotes([r['instrument_token'] for r in holdings + positions if r.get('instrument_token')])
    record = {'profile': profile, 'holdings': mark_rows(holdings, quotes, now, holdings=True),
              'positions': mark_rows(positions, quotes, now), 'orders': orders, 'trades': trades,
              'funds': funds, 'fetched_at': now.isoformat()}
    store.write('live/account', record)
    return record


def history(start, end, page=1, *, broker=None):
    if start > end or (end - start).days > 366:
        raise ValueError('Choose an ordered history range of at most 366 days.')
    if broker is None:
        with Broker() as client:
            return history(start, end, page, broker=client)
    verify_account(broker)
    result = broker.request('GET', '/v2/charges/historical-trades', params={
        'segment': 'EQ', 'start_date': start.isoformat(), 'end_date': end.isoformat(),
        'page_number': page, 'page_size': 100})
    return {'trades': result['data'], 'page': page, 'has_more': len(result['data']) == 100,
            'start': start.isoformat(), 'end': end.isoformat()}


def pending(order):
    return order['status'] not in TERMINAL


def apply_fill(state, order, row):
    filled = int(row.get('filled_quantity') or 0)
    previous = order.get('filled_quantity', 0)
    average = positive(row.get('average_price'))
    if filled < previous or filled > order['quantity'] or (filled and average is None):
        raise ValueError('Broker fill quantities or prices changed unexpectedly. Review the live ledger.')
    delta = filled - previous
    if delta:
        value = filled * average - order.get('filled_value', 0)
        if value <= 0:
            raise ValueError('Broker cumulative fill value is inconsistent.')
        key = order['instrument_key']
        position = state['positions'].get(key)
        if order['side'] == 'BUY':
            if not position:
                position = {'instrument_key': key, 'symbol': order['symbol'], 'isin': order['isin'],
                            'quantity': 0, 'average_price': 0, 'best_price': average,
                            'opened_at': order['created_at'], 'stop_price': 0}
            cost = position['quantity'] * position['average_price'] + value
            position['quantity'] += delta
            position['average_price'] = cost / position['quantity']
            state['positions'][key] = position
        else:
            if not position or position['quantity'] < delta:
                raise ValueError('Broker sells exceed strategy-owned quantity. Review live account activity.')
            realized = value - position['average_price'] * delta
            state['realized_pnl'] += realized
            order['realized_pnl'] = order.get('realized_pnl', 0) + realized
            position['quantity'] -= delta
            if not position['quantity']:
                del state['positions'][key]
        order.update(filled_quantity=filled, filled_value=filled * average, average_price=average)
    order.update(status=str(row['status']).lower(), broker_updated_at=store.now(),
                 status_message=row.get('status_message'), order_ids=[str(row['order_id'])])


def reconcile(broker, state, book):
    by_id = {str(row['order_id']): row for row in book}
    for order in state['orders']:
        if not pending(order):
            continue
        rows = [r for r in book if r.get('tag') == order['tag']]
        if len(rows) > 1:
            raise ValueError('More than one broker order matches a unique strategy tag. Review before continuing.')
        if not rows and order.get('order_ids'):
            row = by_id.get(order['order_ids'][0])
            if row is None:
                try:
                    row = broker.order(order['order_ids'][0])
                except BrokerError:
                    order.update(status='unknown', error='Saved order is unavailable from the broker detail API. Reconcile against Upstox history.')
                    store.write('live/ledger', state)
                    raise ValueError(order['error']) from None
            rows = [row]
        if rows:
            row = rows[0]
            if (row.get('instrument_token') != order['instrument_key'] or row.get('transaction_type') != order['side']
                    or int(row.get('quantity', 0)) != order['quantity'] or row.get('product') != 'D'):
                raise ValueError('Broker order does not match its saved intent.')
            apply_fill(state, order, row)
        else:
            order['status'] = 'unknown'
        # Commit each observed cumulative fill once, before any further broker writes.
        store.write('live/ledger', state)
    if any(o['status'] in ('unknown', 'submitting') for o in state['orders']):
        raise ValueError('An order outcome is unknown. Automatic orders are blocked until it is reconciled in this tab.')


def submit(broker, state, item, side, quantity, price, signal_day, connection, reason, quote):
    if stop_event().is_set():
        raise ValueError('Runner stop requested. No further order will be submitted.')
    current = clock()
    current_time = current.time().replace(tzinfo=None)
    if not time(9, 16) <= current_time < time(15, 30) or side == 'BUY' and current_time >= time(10):
        raise ValueError('Order window closed before submission. No order was sent.')
    if quote_price(quote, current) is None:
        raise ValueError('Quote became stale before submission. No order was sent.')
    intent = {'id': uuid4().hex, 'tag': 'trader' + uuid4().hex[:26], 'instrument_key': item['key'],
              'isin': item['isin'], 'symbol': item['symbol'], 'side': side, 'quantity': quantity,
              'price': price, 'signal_day': signal_day, 'created_at': clock().isoformat(),
              'status': 'submitting', 'filled_quantity': 0, 'filled_value': 0, 'order_ids': [], 'reason': reason,
              'config_digest': market_history.digest(store.read('live/config', LiveConfig().model_dump(mode='json')))}
    state['orders'].append(intent)
    state['account_id'] = connection.expected_user_id
    store.write('live/ledger', state)  # Crash/timeout must never cause a blind resubmission.
    payload = {'quantity': quantity, 'product': 'D', 'validity': 'DAY', 'price': price, 'tag': intent['tag'],
               'instrument_token': item['key'], 'order_type': 'LIMIT', 'transaction_type': side,
               'disclosed_quantity': 0, 'trigger_price': 0, 'is_amo': False, 'slice': False}
    try:
        ids = broker.place(payload, connection.algo_name)
        if len(ids) != 1:
            raise BrokerError('Unexpected number of order IDs. Review Upstox.', uncertain=True)
        intent.update(order_ids=[str(ids[0])], status='submitted')
    except BrokerError as exc:
        intent.update(status='unknown' if exc.uncertain else 'rejected', error=str(exc))
        store.write('live/ledger', state)
        raise
    except (KeyError, TypeError, ValueError):
        intent.update(status='unknown', error='Unreadable placement result. Reconcile before retrying.')
        store.write('live/ledger', state)
        raise ValueError(intent['error']) from None
    store.write('live/ledger', state)
    return intent


def candidates(broker, cfg, now):
    # Ask the broker for completed Nifty sessions; a weekday alone cannot identify holidays.
    sessions = broker.get('/v3/historical-candle/NSE_INDEX%7CNifty%2050/days/1/' +
                          str(now.date() - timedelta(days=1)) + '/' + str(now.date() - timedelta(days=15)))['candles']
    days = sorted({r[0][:10] for r in sessions if r[0][:10] < now.date().isoformat()})
    if not days:
        raise ValueError('No recent completed exchange session is available.')
    day = days[-1]
    universe = store.read('universes/' + current_settings().universe, {}).get('instruments', [])
    if not universe:
        raise ValueError('Refresh the market-data universe before live execution.')
    reference = market_history.evidence(snapshot=True)
    matches, excluded = [], []
    for item in universe:
        if not item['key'].startswith('NSE_EQ|'):
            continue
        bars, _ = market_history.prepare(item, store.read('bars/' + item['isin'], {'bars': []}), reference=reference, fingerprint=False)
        bars = [b for b in bars if b['date'] <= day]
        if not bars or bars[-1]['date'] != day or len(bars) <= backtest.required_warmup(cfg.filters):
            excluded.append({'symbol': item['symbol'], 'reason': 'Missing latest completed session or warmup'})
            continue
        if data_quality.audit({item['symbol']: bars})['findings']:
            excluded.append({'symbol': item['symbol'], 'reason': 'Unresolved price discontinuity'})
            continue
        bars = corporate_actions.adjusted_bars(bars, day)
        if backtest.signal(bars, len(bars) - 1, cfg.filters):
            check = fundamentals.buy_check(item['isin'], 'swing_patterns', at=now)
            if check['buy_allowed']:
                matches.append({**item, 'signal_day': day, 'close': bars[-1]['close'], 'score': check['score']})
            else:
                excluded.append({'symbol': item['symbol'], 'reason': '; '.join(check['block_reasons'])})
    return {'signal_day': day, 'matches': sorted(matches, key=lambda x: (-x['score'], x['symbol'])),
            'excluded': excluded, 'checked_at': now.isoformat()}


def exit_reason(position, price, cfg, now):
    average = position['average_price']
    position['best_price'] = max(position['best_price'], price)
    stop = average * (1 - cfg.stop_pct / 100)
    if position['best_price'] >= average * (1 + cfg.stop_pct / 100 * cfg.breakeven_r):
        stop = max(stop, average)
    if cfg.winner_exit == 'trail_pct':
        stop = max(stop, position['best_price'] * (1 - cfg.trail_pct / 100))
    position['stop_price'] = stop  # New settings are applied to owned holdings on every cycle.
    if price <= stop:
        return 'Stop / trailing protection'
    if cfg.winner_exit.startswith('take_') and price >= average * (1 + int(cfg.winner_exit[5:]) / 100):
        return 'Profit target'
    item = {'isin': position['isin'], 'symbol': position['symbol']}
    bars, _ = market_history.prepare(item, store.read('bars/' + position['isin'], {'bars': []}), fingerprint=False)
    bars = [b for b in bars if b['date'] < now.date().isoformat()]
    bars = corporate_actions.adjusted_bars(bars, bars[-1]['date']) if bars else []
    if bars:
        if sum(b['date'] >= position['opened_at'][:10] for b in bars) >= cfg.max_hold_days:
            return 'Holding limit'
        length = 50 if cfg.winner_exit == 'trail_50d' else 150 if cfg.winner_exit == 'trail_30w' else 0
        if length and len(bars) >= length and bars[-1]['close'] < sum(b['close'] for b in bars[-length:]) / length:
            return 'Completed-session moving average exit'
    return None


def account_quantity(account, key):
    # Overnight holdings overlap overnight positions. Add only net today's delivery activity.
    held = sum(int(r.get('quantity', 0)) for r in account['holdings']
               if r.get('instrument_token') == key)
    change = sum(int(r.get('day_buy_quantity', 0)) - int(r.get('day_sell_quantity', 0))
                 for r in account['positions'] if r.get('instrument_token') == key and r.get('product') == 'D')
    return max(0, held + change)


def cycle(broker, *, execute=False, now=None):
    now = now or clock()
    cfg = LiveConfig(**store.read('live/config', {}))
    connection = Connection(**store.read('live/connection', {}))
    verify_account(broker, require_setup=execute)
    account = refresh_account(broker, now=now)
    state = ledger()
    reconcile(broker, state, account['orders'])
    if not execute:
        plan = candidates(broker, cfg, now)
        store.write('live/plan', plan)
        return plan
    order_window = time(9, 16) <= now.time().replace(tzinfo=None) < time(15, 30)
    # Cancel old requests before considering new exposure; reconcile again on the next cycle.
    for order in state['orders']:
        stale_config = order.get('config_digest') != market_history.digest(cfg.model_dump(mode='json'))
        if pending(order) and (not order_window or stale_config or (now - datetime.fromisoformat(order['created_at'])).total_seconds() >= cfg.order_ttl_seconds):
            broker.cancel(order['order_ids'][0], connection.algo_name)
            return {'message': 'Requested cancellation of an unfilled order after a settings change or timeout; waiting for broker confirmation.'}
    if not order_window:
        return {'message': 'Outside the live order window (09:16–15:30 IST). Account refreshed.'}
    if broker.get('/v2/market/status/NSE').get('status') != 'NORMAL_OPEN':
        return {'message': 'NSE is outside normal trading. Account refreshed.'}
    managed_keys = list(state['positions'])
    quotes = broker.quotes(managed_keys)
    active_keys = {o['instrument_key'] for o in state['orders'] if pending(o)}
    master = None
    unrealized = 0
    for key, position in list(state['positions'].items()):
        price = quote_price(quotes.get(key, {}), clock())
        if price is None:
            raise ValueError('A managed holding has no fresh quote. Orders are blocked; review exposure in Upstox.')
        if account_quantity(account, key) < position['quantity']:
            raise ValueError('Broker quantity is below the managed ledger. Review external trades or corporate actions.')
        known_ids = {order_id for o in state['orders'] for order_id in o.get('order_ids', [])}
        if any(r.get('instrument_token') == key and str(r.get('order_id')) not in known_ids and
               str(r.get('status')).lower() not in TERMINAL for r in account['orders']):
            raise ValueError('A manual broker order overlaps a managed holding. Resolve it in Upstox before automatic exits.')
        unrealized += (price - position['average_price']) * position['quantity']
        position.update(current_price=price, quote_at=quotes[key]['timestamp'])
        reason = exit_reason(position, price, cfg, now)
        store.write('live/ledger', state)
        if reason and key not in active_keys:
            master = master or broker.instruments()
            instrument = master.get(key)
            if not instrument:
                raise ValueError('A managed equity is missing from the current broker instrument master.')
            limit = limit_price(price, instrument['tick_size'], 'SELL', cfg.protection_bps)
            submit(broker, state, {'key': key, **position}, 'SELL', position['quantity'], limit,
                   now.date().isoformat(), connection, reason, quotes[key])
            return {'message': f'Submitted managed exit for {position["symbol"]}; awaiting fills.'}
    equity_pnl = state['realized_pnl'] + unrealized
    today = now.date().isoformat()
    if today not in state['daily_baselines']:
        # Overnight cost-to-market movement counts against today's risk budget.
        previous_unrealized = 0
        for position in state['positions'].values():
            if position['opened_at'][:10] >= today:
                continue
            close = positive(quotes[position['instrument_key']].get('ohlc', {}).get('close'))
            if close is None:
                raise ValueError('Previous close unavailable for daily managed loss calculation.')
            previous_unrealized += (close - position['average_price']) * position['quantity']
        state['daily_baselines'][today] = state['realized_pnl'] + previous_unrealized
    state.update(unrealized_pnl=unrealized, daily_pnl=equity_pnl - state['daily_baselines'][today], updated_at=now.isoformat())
    store.write('live/ledger', state)
    if store.read('live/control', {}).get('paused') or state['daily_pnl'] <= -cfg.max_daily_loss:
        return {'message': 'New entries paused; managed exits remain active.'}
    # Entries are completed-session signals, checked against fresh prices in a short opening window.
    if now.time().replace(tzinfo=None) >= time(10, 0):
        return {'message': 'Entry window closed (10:00 IST); managed exits remain active.'}
    plan = candidates(broker, cfg, now)
    store.write('live/plan', plan)
    entry_quotes = broker.quotes([item['key'] for item in plan['matches']])
    occupied = set(state['positions']) | active_keys
    committed = sum(p['quantity'] * p['average_price'] for p in state['positions'].values())
    committed += sum(max(0, o['quantity'] - o.get('filled_quantity', 0)) * o['price']
                     for o in state['orders'] if pending(o) and o['side'] == 'BUY')
    daily_buys = sum(o['quantity'] * o['price'] for o in state['orders']
                     if o['side'] == 'BUY' and o['created_at'][:10] == today and o['status'] != 'not_placed')
    funds = positive(account['funds'].get('equity', {}).get('available_margin')) or 0
    # Reserve all open account buy orders, including manual ones, in addition to strategy capital limits.
    reserved = sum(float(o.get('price') or 0) * int(o.get('pending_quantity') or 0)
                   for o in account['orders'] if o.get('transaction_type') == 'BUY' and str(o.get('status')).lower() not in TERMINAL)
    for item in plan['matches']:
        if len(occupied) >= cfg.max_positions:
            break
        key = item['key']
        if key in occupied or any(o['instrument_key'] == key and
                                 (o['signal_day'] == plan['signal_day'] or o['created_at'][:10] == today)
                                 for o in state['orders']):
            continue
        # Do not mix fresh strategy entries with pre-existing/manual exposure or orders.
        if account_quantity(account, key) or any(o.get('instrument_token') == key and
                str(o.get('status')).lower() not in TERMINAL for o in account['orders']):
            continue
        price = quote_price(entry_quotes.get(key, {}), clock())
        if price is None or abs(price / item['close'] - 1) * 100 > cfg.max_entry_gap_pct:
            continue
        master = master or broker.instruments()
        instrument = master.get(key)
        if not instrument:
            continue
        limit = limit_price(price, instrument['tick_size'], 'BUY', cfg.protection_bps)
        budget = min(cfg.capital - committed, cfg.max_order_value, cfg.max_daily_buy_value - daily_buys,
                     max(0, funds - reserved) * .98, cfg.capital * cfg.risk_pct / cfg.stop_pct)
        quantity = math.floor(max(0, budget) / limit)
        lot = int(instrument.get('lot_size', 1))
        quantity = quantity // lot * lot
        if quantity:
            submit(broker, state, item, 'BUY', quantity, limit, plan['signal_day'], connection, 'Completed-session swing signal', entry_quotes[key])
            # One request per cycle, always reconcile before another request.
            return {'message': f'Submitted {item["symbol"]} buy; awaiting broker fills.'}
    return {'message': f'Watching managed exits; {len(plan["matches"])} qualified swing signals.'}


def preview():
    with mutex('live_control', timeout=30), Broker() as broker:
        return cycle(broker)


def _run():
    try:
        with mutex('live_runner', timeout=0):
            while not stop_event().is_set():
                try:
                    with mutex('live_control', timeout=30), Broker() as broker:
                        result = cycle(broker, execute=True)
                    status = {'status': 'watching', **result}
                except Exception as exc:
                    # Raw network errors are never exposed; BrokerError and application errors are sanitized.
                    status = {'status': 'attention', 'message': str(exc) if isinstance(exc, ValueError)
                              else 'Live cycle failed. Automatic orders are blocked until the next successful reconciliation.'}
                store.write('live/runner', {**status, 'heartbeat_at': store.now()})
                stop_event().wait(15)
    except ValueError:
        pass  # Another process already owns live execution.
    finally:
        if stop_event().is_set():
            store.write('live/runner', {'status': 'stopped', 'message': 'Runner stopped. Open broker orders and exposure remain.', 'heartbeat_at': store.now()})


def start():
    global _thread
    with _guard:
        existing = _runners.get(identity.username(), {}).get('thread') if identity.username() else _thread
        if running() or (existing and existing.is_alive()):
            return public_state()
        with mutex('live_control', timeout=30), Broker() as broker:
            verify_account(broker, require_setup=True)
            account = refresh_account(broker)
            state = ledger()
            reconcile(broker, state, account['orders'])
        stop_event().clear()
        context = copy_context()
        thread = threading.Thread(target=lambda: context.run(_run), name='upstox-live', daemon=True)
        if identity.username():
            _runners[identity.username()]['thread'] = thread
        else:
            _thread = thread
        thread.start()
    return public_state()


def stop():
    stop_event().set()
    return {'stopping': True, 'message': 'Stopping after the current cycle. Pending broker orders and holdings remain; monitoring will stop.'}


def shutdown():
    _stop.set()
    with _guard:
        runners = list(_runners.values())
    for runner in runners:
        runner['stop'].set()
    for thread in [_thread, *[r['thread'] for r in runners]]:
        if thread:
            thread.join(timeout=2)


def pause(paused):
    with mutex('live_control', timeout=30):
        store.write('live/control', {'paused': paused})
    return public_state()


def resolve_unknown(identity, order_id, confirmed_not_placed, final_report=None):
    with mutex('live_control', timeout=30), Broker() as broker:
        if running():
            raise ValueError('Stop the runner before resolving an unknown order.')
        verify_account(broker)
        state = ledger()
        order = next((o for o in state['orders'] if o['id'] == identity), None)
        if not order or order['status'] not in ('unknown', 'submitting'):
            raise ValueError('Select an unresolved order intent.')
        if final_report:
            if not order_id or (order.get('order_ids') and order_id not in order['order_ids']):
                raise ValueError('Use the original broker order ID for this historical reconciliation.')
            if any(order_id in o.get('order_ids', []) for o in state['orders'] if o['id'] != identity):
                raise ValueError('This broker order ID is already linked to a different intent.')
            filled = final_report['filled_quantity']
            status = final_report['status']
            if (status == 'complete' and filled != order['quantity']) or (status == 'rejected' and filled):
                raise ValueError('The final fill quantity is inconsistent with the selected broker status.')
            apply_fill(state, order, {**final_report, 'order_id': order_id})
            order.update(resolved_at=store.now(), resolution='User verified terminal order and fills against Upstox history')
        elif order_id:
            row = broker.order(order_id)
            if (row.get('tag') != order['tag'] or row.get('instrument_token') != order['instrument_key']
                    or row.get('transaction_type') != order['side'] or int(row.get('quantity', 0)) != order['quantity']):
                raise ValueError('Broker order does not match this saved intent.')
            apply_fill(state, order, row)
        elif confirmed_not_placed:
            if order.get('order_ids'):
                raise ValueError('Upstox accepted this order and returned an ID. Reconcile its actual final fills instead.')
            if any(r.get('tag') == order['tag'] for r in broker.orders()):
                raise ValueError('Upstox has an order for this tag. Link its order ID instead.')
            order.update(status='not_placed', resolved_at=store.now(), resolution='User verified no order was placed in Upstox')
        else:
            raise ValueError('Supply the matching order ID or confirm that Upstox has no matching order.')
        store.write('live/ledger', state)
    return public_state()

"""Forward-only scalping paper ledger. Candles signal; observed quotes fill."""
import math
from datetime import datetime
from uuid import uuid4

from pydantic import Field
from core.execution.paper import PaperBrokerAdapter
from core.portfolio import manager, paper
from core.portfolio.locking import mutex
from core.research import data_quality, intraday_data, market_history, scalping, store

KEY = 'portfolios/scalping'


class ScalpingPaperConfig(scalping.ScalpingParameters):
    name: str = Field('Scalping paper portfolio', min_length=1, max_length=80, title='Portfolio name')
    capital: float = Field(..., ge=1000, le=1e10, title='Allocated capital (₹)')
    slippage_bps: float = Field(10, gt=0, le=500, title='Slippage per side (bps)')
    buy_cost_bps: float = Field(10, gt=0, le=500, title='All-in buy charges (bps)')
    sell_cost_bps: float = Field(10, gt=0, le=500, title='All-in sell charges (bps)')
    max_spread_bps: float = Field(15, gt=0, le=500, title='Maximum entry spread (bps)')
    quote_max_age_seconds: int = Field(3, ge=1, le=15, title='Maximum quote age (seconds)')
    max_entry_delay_seconds: int = Field(8, ge=2, le=30, title='Entry deadline after signal close (seconds)')
    auto_run: bool = Field(False, title='Automatically start the streaming runner with this app')
    acknowledge_limitations: bool = Field(False, title='I understand simulated quote fills, costs and short eligibility remain unverified')


def save(config, settings, *, create=False):
    with mutex('scalping_portfolio'):
        return manager.save('scalping', config, settings, create=create, clock=paper.local_now())


def set_status(status):
    if status not in ('active','paused'):
        raise ValueError('Choose active or paused.')
    with mutex('scalping_portfolio'):
        portfolio = store.read(KEY)
        if not portfolio:
            raise ValueError('Create a scalping paper portfolio first.')
        portfolio['status'] = status
        portfolio['updated_at'] = store.now()
        store.write(KEY,portfolio)
        return portfolio


def public_portfolio():
    portfolio = store.read(KEY)
    if not portfolio:
        return None
    session = portfolio.get('stream_session',{})
    portfolio['stream_session'] = {k:v for k,v in session.items() if k not in ('bars','pending','last_fills')}
    ledger = portfolio.get('ledger',{})
    if ledger:
        portfolio['ledger'] = {**ledger,'trades':ledger['trades'][-100:],'orders':ledger['orders'][-200:]}
        portfolio['ledger']['full_trade_count'] = len(ledger['trades'])
        portfolio['ledger']['full_order_count'] = len(ledger['orders'])
    return portfolio


def context_key(day):
    return 'scalping_stream/context/'+day


def prepare_session(day, log):
    """Freeze prior-session selection and history once per forward session."""
    existing = store.read(context_key(day))
    if existing:
        expected = existing.pop('sha256')
        if scalping.digest(existing) != expected:
            raise ValueError('Frozen scalping session context changed; investigate before resuming.')
        existing['sha256'] = expected
        return existing
    portfolio = store.read(KEY)
    if not portfolio:
        raise ValueError('Create a scalping paper portfolio first.')
    cfg = ScalpingPaperConfig(**portfolio['config'])
    datasets, instruments = {}, portfolio['universe_snapshot']['instruments']
    evidence = market_history.evidence(snapshot=True)
    for item in instruments:
        record = store.read('bars/'+item['isin'], {})
        if not record.get('bars'):
            continue
        derived, _ = market_history.prepare(item, record, reference=evidence)
        prior = [b for b in derived if b['date'] < day]
        if prior:
            datasets[item['symbol']] = prior
    if not datasets:
        raise ValueError('No verified prior daily history; refresh Market data before starting paper.')
    latest = max(rows[-1]['date'] for rows in datasets.values())
    if not 0 < (datetime.fromisoformat(day)-datetime.fromisoformat(latest)).days <= 7:
        raise ValueError('Prior daily history is stale; refresh Market data before starting paper.')
    datasets = {s: rows for s, rows in datasets.items() if rows[-1]['date'] == latest}
    quality = data_quality.audit(datasets, end=latest)
    datasets = data_quality.exclude_anomalies(datasets, quality, log)
    if not datasets:
        raise ValueError('No eligible stocks remain after excluding unresolved price gaps.')
    plan, requests = scalping.entry_plan(datasets, cfg, days=[day], require_day_bar=False)
    candidates = plan.get(day, [])
    if not candidates:
        raise ValueError('No liquid stocks have the required scalping warmup for this session.')
    # No current-day history is used for selection or prior-session warmup.
    requests.pop(day, None)
    warmup = intraday_data.load_ranges(requests, portfolio['universe_snapshot'], log, 1)
    for c in candidates:
        for d in c['history']:
            intraday_data.trading_bars(warmup[c['symbol']][d], '15:29', 1)
    selected = {c['symbol'] for c in candidates}
    context = dict(day=day, created_at=store.now(), config=cfg.model_dump(mode='json'), candidates=candidates,
                   instruments=[i for i in instruments if i['symbol'] in selected], warmup=warmup,
                   daily_source_sha256=scalping.digest(datasets), latest_daily_session=latest,
                   data_quality=quality)
    context['sha256'] = scalping.digest(context)
    store.write(context_key(day), context)
    log(f'Scalping context frozen: {len(candidates)} stocks; prior daily boundary {latest}.')
    return context


def equity(ledger):
    return ledger['cash']+sum(p['reserved']+p['sign']*p['quantity']*(ledger['marks'].get(s,p['entry'])-p['entry'])-p['entry_fee']
                              for s,p in ledger['positions'].items())


def update_metrics(portfolio):
    ledger = portfolio['ledger']
    value = equity(ledger)
    ledger['peak'] = max(ledger.get('peak', portfolio['config']['capital']), value)
    drawdown = (ledger['peak']-value)/ledger['peak']*100
    ledger['max_drawdown_pct'] = max(ledger.get('max_drawdown_pct', 0), drawdown)
    trades = ledger['trades']
    portfolio['metrics'] = dict(final_equity=value, return_pct=(value/portfolio['config']['capital']-1)*100,
                               max_drawdown_pct=ledger['max_drawdown_pct'], trade_count=len(trades),
                               realized_pnl=sum(t['pnl'] for t in trades),
                               unrealized_pnl=value-ledger['cash']-sum(p['reserved'] for p in ledger['positions'].values()))


class QuoteEngine:
    def __init__(self, context, clock):
        self.context = context
        self.cfg = ScalpingPaperConfig(**context['config'])
        self.broker = PaperBrokerAdapter(self.cfg)
        self.candidates = {c['symbol']:c for c in context['candidates']}
        self.last_seen = {}
        self.fresh_quotes = {}
        self.marks = {}
        self.stopping = False
        self.market_open = False
        with mutex('scalping_portfolio'):
            portfolio = store.read(KEY)
            if not portfolio:
                raise ValueError('Create a scalping paper portfolio first.')
            if not portfolio['ledger']:
                portfolio['ledger'] = dict(cash=self.cfg.capital, positions={}, marks={}, trades=[], orders=[], curve=[],
                                           total_fees=0, total_slippage=0, peak=self.cfg.capital, max_drawdown_pct=0)
            previous = portfolio.get('stream_session', {})
            if previous.get('day') != context['day']:
                if previous:
                    store.write('scalping_stream/sessions/'+previous['day'], previous)
                previous = dict(day=context['day'], bars={}, pending={}, counts={}, cooldown={},
                                baseline=equity(portfolio['ledger']), loss_halt=False, last_fills={}, data_issues={},
                                recovery_flatten=bool(portfolio['ledger']['positions']))
            # Old signals are never replayed after reconnect/restart.
            previous['pending'] = {}
            previous['restarted_at'] = clock.isoformat()
            portfolio['stream_session'] = previous
            portfolio['data_quality'] = context.get('data_quality', {})
            update_metrics(portfolio)
            self.marks = dict(portfolio['ledger']['marks'])
            store.write(KEY, portfolio)

    def record_bars(self, symbol, bars, clock):
        if symbol not in self.candidates:
            return
        bars = [b for b in bars if b['timestamp']+60000 <= int(clock.timestamp()*1000)-2000]
        if not bars:
            return
        # Normalize even injected/recovered rows before any indicator or signal calculation.
        record = intraday_data.cached_bars({'bars':bars}, self.context['day'], 1)
        with mutex('scalping_portfolio'):
            portfolio = store.read(KEY)
            session = portfolio['stream_session']
            previous = session['bars'].get(symbol, [])
            overlap = min(len(previous), len(record))
            try:
                intraday_data.trading_bars(record, record[-1]['time'], 1)
                if previous[:overlap] != record[:overlap]:
                    raise ValueError('Previously processed completed candles changed.')
            except ValueError as exc:
                session['data_issues'][symbol] = str(exc)
                session['pending'].pop(symbol, None)
                store.write(KEY, portfolio)
                return
            if len(record) <= len(previous) or symbol in session['data_issues']:
                return
            session['bars'][symbol] = record
            session['pending'].pop(symbol, None)
            final = record[-1]
            expiry = final['timestamp']+60000+self.cfg.max_entry_delay_seconds*1000
            now = int(clock.timestamp()*1000)
            if portfolio['status']=='active' and self.context['day'] >= portfolio['start_session'] and not session['loss_halt'] and now <= expiry:
                _, values = scalping.features(self.context['warmup'][symbol], self.candidates[symbol], self.context['day'], self.cfg, completed_bars=record)
                setup = scalping.signal(record, values, len(record)-1, self.cfg)
                if setup:
                    session['pending'][symbol] = dict(**setup, signal=final, ready_at=now, expires_at=expiry)
            session['last_completed_candle'] = max(session.get('last_completed_candle',0), final['timestamp'])
            portfolio['updated_at'] = store.now()
            store.write(KEY, portfolio)

    def disconnect(self):
        self.market_open = False
        with mutex('scalping_portfolio'):
            portfolio = store.read(KEY)
            portfolio['stream_session']['pending'] = {}
            store.write(KEY, portfolio)

    def quote(self, symbol, quote, clock):
        timestamp, now = quote['timestamp'], int(clock.timestamp()*1000)
        values = (quote['bid'], quote['ask'], quote['price'])
        if not all(math.isfinite(v) and v>0 for v in values) or quote['bid']>quote['ask'] or min(quote['bid_quantity'],quote['ask_quantity'])<=0:
            return False
        if not self.market_open or not 0 <= now-timestamp <= self.cfg.quote_max_age_seconds*1000:
            return False
        instant = datetime.fromtimestamp(timestamp/1000, intraday_data.IST)
        if instant.date().isoformat()!=self.context['day'] or not '09:15' <= instant.strftime('%H:%M') <= '15:29':
            return False
        if timestamp <= self.last_seen.get(symbol,0):
            return False
        self.last_seen[symbol] = timestamp
        self.fresh_quotes[symbol] = timestamp
        with mutex('scalping_portfolio'):
            portfolio = store.read(KEY)
            ledger, session = portfolio['ledger'], portfolio['stream_session']
            if timestamp <= session['last_fills'].get(symbol,0):
                return False
            position = ledger['positions'].get(symbol)
            # Marks use realizable sides of the book. Fresh quotes never imply a past fill.
            self.marks[symbol] = quote['bid'] if not position or position['sign']==1 else quote['ask']
            ledger['marks'].update(self.marks)
            current_equity = equity(ledger)
            if current_equity <= session['baseline']*(1-self.cfg.daily_loss_pct/100):
                session['loss_halt'] = True
            changed, reason = False, None
            if position:
                price = quote['bid'] if position['sign']==1 else quote['ask']
                rules = position['rules']
                if position.get('pending_exit'):
                    reason = position['pending_exit']
                elif self.stopping or session['recovery_flatten']:
                    reason = 'Runner stop / recovery liquidation'
                elif instant.strftime('%H:%M') >= rules['square_off_time']:
                    reason = 'Mandatory intraday square-off'
                elif timestamp-position['entry_timestamp'] >= rules['max_holding_minutes']*60000:
                    reason = 'Maximum holding time'
                elif position['sign']*(price-position['stop']) <= 0:
                    reason = 'Quote crossed pullback stop'
                elif position['sign']*(price-position['target']) >= 0:
                    reason = 'Profit target'
                if reason:
                    self._exit(portfolio,symbol,quote,instant,reason)
                    changed = True
            elif symbol in self.candidates:
                pending = session['pending'].get(symbol)
                eligible = (pending and pending['ready_at'] <= timestamp <= pending['expires_at'] and
                            self.cfg.first_entry_time <= instant.strftime('%H:%M') <= self.cfg.last_entry_time and
                            self.context['day'] >= portfolio['start_session'] and portfolio['status']=='active' and
                            not self.stopping and not session['recovery_flatten'] and not session['loss_halt'] and
                            symbol not in session['data_issues'] and len(ledger['positions']) < self.cfg.max_positions and
                            timestamp >= session['cooldown'].get(symbol,0) and session['counts'].get(symbol,0)<self.cfg.max_trades_per_symbol)
                spread = (quote['ask']-quote['bid'])/((quote['ask']+quote['bid'])/2)*10000
                if eligible and spread <= self.cfg.max_spread_bps:
                    changed = self._enter(portfolio,symbol,quote,instant,pending)
            if session['recovery_flatten'] and not ledger['positions']:
                session['recovery_flatten'] = False
                changed = True
            if session['loss_halt'] != store.read(KEY)['stream_session']['loss_halt']:
                changed = True
            if changed:
                if equity(ledger) <= session['baseline']*(1-self.cfg.daily_loss_pct/100):
                    session['loss_halt'] = True
                session['last_fills'][symbol] = timestamp
                update_metrics(portfolio)
                portfolio['updated_at'] = store.now()
                store.write(KEY, portfolio)
            return changed

    def _enter(self, portfolio, symbol, quote, instant, setup):
        ledger, session = portfolio['ledger'], portfolio['stream_session']
        sign = setup['sign']
        raw = quote['ask'] if sign==1 else quote['bid']
        side = 'buy' if sign==1 else 'sell'
        one = self.broker.fill(raw,1,side)
        distance = sign*(one['price']-setup['stop'])
        if setup['stop']<=0 or not self.cfg.min_stop_pct <= distance/one['price']*100 <= self.cfg.max_stop_pct:
            session['pending'].pop(symbol,None)
            return True
        stop_fill = self.broker.fill(setup['stop'],1,'sell' if sign==1 else 'buy')
        risk = sign*(one['price']-stop_fill['price'])+one['fees']+stop_fill['fees']
        account_equity = max(0,equity(ledger))
        qty = max(0,min(math.floor(account_equity*self.cfg.risk_pct/100/risk),
                        math.floor(min(ledger['cash'],account_equity/self.cfg.max_positions)/(one['price']+one['fees'])),
                        math.floor(setup['signal']['volume']*self.cfg.participation_pct/100),
                        quote['ask_quantity'] if sign==1 else quote['bid_quantity']))
        target = one['price']+sign*distance*self.cfg.target_r
        if not qty or target<=0:
            session['pending'].pop(symbol,None)
            return True
        fill = self.broker.fill(raw,qty,side)
        reserved = fill['price']*qty+fill['fees']
        ledger['cash'] -= reserved
        ledger['positions'][symbol] = dict(id=uuid4().hex[:12], direction=setup['direction'], sign=sign, quantity=qty,
                entry=fill['price'], reserved=reserved, entry_cost=reserved, entry_fee=fill['fees'], entry_slippage=fill['slippage'],
                entry_date=instant.date().isoformat(), entry_time=instant.strftime('%H:%M:%S'), entry_timestamp=quote['timestamp'],
                stop=setup['stop'], target=target, distance=distance, trigger=setup['trigger'],
                signal=setup['signal'], signal_indicators=setup['indicators'], rules=self.cfg.model_dump(mode='json'))
        ledger['marks'][symbol] = quote['bid'] if sign==1 else quote['ask']
        self.marks[symbol] = ledger['marks'][symbol]
        session['pending'].pop(symbol,None)
        session['counts'][symbol] = session['counts'].get(symbol,0)+1
        self._order(ledger,symbol,side,qty,fill,quote,instant,'Pullback entry')
        return True

    def _exit(self, portfolio, symbol, quote, instant, reason):
        ledger, session = portfolio['ledger'], portfolio['stream_session']
        p = ledger['positions'][symbol]
        p['pending_exit'] = reason
        qty = min(p['quantity'], quote['bid_quantity'] if p['sign']==1 else quote['ask_quantity'])
        ratio = qty/p['quantity']
        entry_fee, reserved, entry_slip = p['entry_fee']*ratio,p['reserved']*ratio,p['entry_slippage']*ratio
        side = 'sell' if p['sign']==1 else 'buy'
        fill = self.broker.fill(quote['bid'] if p['sign']==1 else quote['ask'],qty,side)
        pnl = p['sign']*qty*(fill['price']-p['entry'])-entry_fee-fill['fees']
        ledger['cash'] += reserved+pnl
        ledger['trades'].append(dict(position_id=p['id'],symbol=symbol,direction=p['direction'],quantity=qty,
                entry_date=p['entry_date'],entry_time=p['entry_time'],entry_timestamp=p['entry_timestamp'],entry=p['entry'],
                exit_date=instant.date().isoformat(),exit_time=instant.strftime('%H:%M:%S'),exit_timestamp=quote['timestamp'],exit=fill['price'],
                pnl=pnl,fees=entry_fee+fill['fees'],r=pnl/(qty*p['distance']),reason=reason,
                initial_stop=p['stop'],target=p['target'],trigger=p['trigger'],signal=p['signal'],signal_indicators=p['signal_indicators'],
                holding_minutes=(quote['timestamp']-p['entry_timestamp'])/60000,partial_exit=qty<p['quantity']))
        self._order(ledger,symbol,side,qty,fill,quote,instant,reason)
        p['quantity'] -= qty
        p['entry_fee'] -= entry_fee
        p['entry_slippage'] -= entry_slip
        p['reserved'] -= reserved
        p['entry_cost'] = p['reserved']
        if not p['quantity']:
            ledger['positions'].pop(symbol)
            session['cooldown'][symbol] = quote['timestamp']+self.cfg.cooldown_minutes*60000

    def _order(self, ledger, symbol, side, quantity, fill, quote, instant, reason):
        ledger['total_fees'] += fill['fees']
        ledger['total_slippage'] += fill['slippage']
        ledger['orders'].append(dict(id=uuid4().hex[:12],date=instant.date().isoformat(),time=instant.strftime('%H:%M:%S'),
                symbol=symbol,side=side,quantity=quantity,price=fill['price'],fees=fill['fees'],slippage=fill['slippage'],
                status='simulated',reason=reason,quote=quote,source='Upstox V3 observed best bid/ask',
                session_context_sha256=self.context['sha256']))

    def checkpoint(self, clock, *, feed_connected=False):
        with mutex('scalping_portfolio'):
            portfolio = store.read(KEY)
            ledger = portfolio['ledger']
            ledger['marks'].update(self.marks)
            update_metrics(portfolio)
            day = self.context['day']
            row = dict(date=day,equity=portfolio['metrics']['final_equity'],drawdown_pct=ledger['max_drawdown_pct'])
            if ledger['curve'] and ledger['curve'][-1]['date']==day:
                ledger['curve'][-1] = row
            else:
                ledger['curve'].append(row)
            portfolio['stream_session']['feed_connected'] = feed_connected
            portfolio['stream_session']['checkpoint_at'] = clock.isoformat()
            portfolio['ledger']['last_session'] = day
            portfolio['updated_at'] = store.now()
            store.write(KEY,portfolio)


def cycle(log, job_id):
    from core.portfolio.scalping_control import start
    state = start()
    log('Standalone scalping quote runner requested; no historical paper fills will be replayed.')
    return {'portfolio_id':'scalping','runner':state}

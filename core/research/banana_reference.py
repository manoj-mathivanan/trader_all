"""Independent fixed-window screen proxies with observed Banana execution rules.

The licensed source prices, historical market-wide ranks, market caps and
proprietary nested-base lifecycle are unavailable. No detector parity claim.
"""
from core.execution.upstox import equity_charges, size_order, breakeven_price
import math
from copy import deepcopy
from bisect import bisect_left, bisect_right
from collections import Counter
from datetime import date
from statistics import median
from core.research import backtest, corporate_actions
from strategies.swing_patterns.patterns.signals import matches, vcp_setup

NOTICES = [
    'Independent fixed-window proxies, not Banana detector parity: VCP/IPO use 30 sessions; multi-year uses 252; Blue sky uses the highest loaded historical close. Nested structure levels and base lifecycle are unavailable.',
    'Historical market cap is unavailable: the observed â‚¹300 crore source filter is recorded but NOT enforced. Results are a partial-rule sensitivity.',
    'Weighted RS uses 63/126/189/252-session month proxies and ranks only eligible local stocks, not the source market-wide NSE/BSE population.',
    'Median turnover uses the preceding 20 sessions; source lookback and ATR smoothing are unverified. ATR tightening uses average daily true range / close in each base half.',
    'Reference execution: fixed entry-relative stop; armed SMA50 close breach exits next open; sale cash available next session; position and turnover caps; locked one-price sessions defer fills; period end marks open holdings.',
]


def setup_proxy(rows, i, cfg, historical_pivot=None):
    """Completed setup only; never inspect candles after i."""
    length = 252 if cfg.pattern == 'multiyear' else 30
    if i < (50 if cfg.pattern == 'ipo' else 252):
        return False, None
    window = rows[max(0, i-length+1):i+1]
    pivot = historical_pivot if cfg.pattern == 'blue_sky' and historical_pivot is not None else max(b['close'] for b in (rows[:i+1] if cfg.pattern == 'blue_sky' else window))
    price = rows[i]['close']
    if price > pivot or price <= 0:
        return False, pivot
    if cfg.pattern == 'vcp':
        halves = len(window)//2
        first, second = window[:halves], window[halves:]
        def atr_part(begin, count):
            values = []
            for j in range(begin, begin+count):
                b = rows[j]
                previous = rows[j-1]['close']
                values.append(max(b['high']-b['low'], abs(b['high']-previous), abs(b['low']-previous))/b['close'])
            return sum(values)/count
        a1 = atr_part(i-length+1, halves)
        a2 = atr_part(i-length+1+halves, len(second))
        v1 = sum(b['volume'] for b in first)/len(first)
        v2 = sum(b['volume'] for b in second)/len(second)
        high = max(b['high'] for b in rows[i-251:i+1])
        low = min(b['low'] for b in rows[i-251:i+1])
        depth = (max(b['high'] for b in window)-min(b['low'] for b in window))/max(b['high'] for b in window)*100
        qualified = (a1 > 0 and a2/a1 <= .9 and v1 > 0 and v2/v1 <= .9
                     and depth <= 35 and price >= high*.7 and price >= low*1.15
                     and price >= sum(b['close'] for b in rows[i-49:i+1])/50
                     and price >= sum(b['close'] for b in rows[i-199:i+1])/200)
    elif cfg.pattern == 'multiyear':
        qualified = price >= pivot*.8 and price >= sum(b['close'] for b in rows[i-199:i+1])/200
    elif cfg.pattern == 'blue_sky':
        qualified = price >= pivot*.8
    elif cfg.pattern == 'ipo':
        metadata = rows[0].get('listing_metadata', {})
        listing = metadata.get('ipo_date', metadata.get('listing_date'))
        if not listing or metadata.get('verified') is not True or not metadata.get('source') or metadata.get('ipo_verified') is not True:
            return False, pivot
        age = (date.fromisoformat(rows[i]['date'])-date.fromisoformat(listing)).days
        depth = (max(b['high'] for b in window)-min(b['low'] for b in window))/max(b['high'] for b in window)*100
        qualified = (0 <= age <= 350 and depth <= 35 and price >= pivot*.8
                     and price >= sum(b['close'] for b in rows[i-49:i+1])/50)
    else:
        raise ValueError('Reference proxies support VCP, Blue sky, multi-year and IPO only.')
    return qualified, pivot


def _simulate(data, cfg, *, exits='reference', setup='confirmed', entry='next_open',
             ranking='rs', min_rs=0, turnover_floor=0, cost_bps=25,
             same_day='conservative', cap_pct=30, turnover_pct=10, rs_method='126', mark_end=True,
             state=None, allow_entries=True, entry_check=None, entry_warmup=0, rs_data=None):
    """Cash portfolio with yesterday's decisions and next-day sale settlement.

    confirmed: original local completed-close signals, bought next open.
    setup: local three-window VCP setup, prior-window high/close pivot crossed
    today. No claim of reproducing the proprietary base/lifecycle algorithm.
    """
    state = deepcopy(state or {})
    if rs_data is not None and state:
        raise ValueError('Separate RS inputs are supported only for isolated research, not resumed paper.')
    rs_data = data if rs_data is None else rs_data
    if any(s not in rs_data or (rs_data[s] is not bs and rs_data[s] != bs) for s,bs in data.items()):
        raise ValueError('RS population must retain the exact traded-stock price histories.')
    if state and state.get('simulation_model') != 'banana_proxy_v1':
        raise ValueError('Reference paper requires a separate portfolio; legacy ledgers cannot be converted.')
    days = {}
    indices = {s: {b['date']: i for i, b in enumerate(rows)} for s, rows in data.items()}
    rs_indices = indices if rs_data is data else {s:{b['date']:i for i,b in enumerate(rows)} for s,rows in rs_data.items()}
    for s, rows in data.items():
        for i, b in enumerate(rows):
            if str(cfg.start) <= b['date'] <= str(cfg.end) and b['date'] > state.get('last_session', ''):
                days.setdefault(b['date'], {})[s] = (i, b)
    cash, unsettled = state.get('cash', cfg.capital), state.get('unsettled', 0.0)
    positions, marks = state.get('positions', {}), state.get('marks', {})
    trades, curve, orders = state.get('trades', []), state.get('curve', []), state.get('orders', [])
    rejected = Counter(state.get('entry_filter_rejections', {}))
    peak, drawdown, fees = state.get('peak', cfg.capital), state.get('max_dd', 0.0), state.get('total_fees', 0.0)
    exposure = state.get('exposure', [])
    action_log = state.get('corporate_actions', [])
    audit = state.get('candidate_audit', [])
    slip = getattr(cfg,'slippage_bps',0) / 10000
    total_slippage = state.get('total_slippage',0)
    rs_cache = {}
    context_cache = {}
    prefix_cache = {}

    def context(s, day, book=None):
        book = data if book is None else book
        key = (s, id(book[s]), tuple(a['id'] for a in corporate_actions.actions(book[s]) if a['ex_date'] <= day))
        if key not in context_cache:
            context_cache[key] = corporate_actions.adjusted_bars(book[s], day)
        return context_cache[key]

    def rs(day):
        if day not in rs_cache:
            returns = {}
            for s in rs_data:
                j = rs_indices[s].get(day)
                lookback = 252 if rs_method=='weighted' else 126
                if j is not None and j >= lookback:
                    rows = context(s, day, rs_data)
                    returns[s] = (sum(w*(rows[j]['close']/rows[j-n]['close']-1)
                                  for w,n in [(0.4,63),(0.2,126),(0.2,189),(0.2,252)])
                                  if rs_method=='weighted' else rows[j]['close']/rows[j-126]['close']-1)
            values = sorted(returns.values())
            ranks = {s: (bisect_left(values, r)+bisect_right(values, r)-1)/2
                         /max(len(values)-1, 1) for s,r in returns.items()}
            rs_cache[day] = {s: 1+98*r if rs_method=='weighted' else 100*r for s,r in ranks.items()}
        return rs_cache[day]

    def close(s, price, day, reason):
        nonlocal unsettled, fees, total_slippage
        p = positions.pop(s)
        total_slippage += p['quantity'] * price * slip
        price *= 1-slip
        if p['entry_date'] == day:
            actual = equity_charges(p['entry'],p['quantity'],'buy',day,intraday=True)['total']
            correction = actual-p['entry_fee']
            unsettled -= correction
            fees += correction
            p['entry_fee'] = actual
            p['entry_cost'] += correction
            next(o for o in reversed(orders) if o['symbol']==s and o['side']=='buy' and o['date']==day)['fees'] = actual
        charge = equity_charges(price, p['quantity'], 'sell', day, intraday=p['entry_date'] == day)['total']
        proceeds = p['quantity'] * price - charge
        unsettled += proceeds
        fees += charge
        orders.append(dict(id=f'{s}:{day}:sell',symbol=s,date=day,side='sell',quantity=p['quantity'],
                           price=price,fees=charge,status='FILLED',reason=reason))
        trades.append(dict(symbol=s, entry_date=p['entry_date'], exit_date=day,
                           entry=p.get('entry_fill', p['entry']), exit=price,
                           quantity=p.get('entry_quantity', p['quantity']),
                           pnl=proceeds-p['entry_cost'], reason=reason,
                           fees=p['entry_fee']+charge, initial_risk=p['initial_risk']))

    for day, session in sorted(days.items()):
        cash += unsettled
        unsettled = 0
        exited = set()
        for s, p in list(positions.items()):
            for action in corporate_actions.actions(data.get(s, [])):
                if action['ex_date'] == day and action['price_basis'] == 'raw':
                    positions[s], marks[s] = corporate_actions.rebase_position(p, marks[s], action)
                    p = positions[s]
                    action_log.append(dict(action, symbol=s))
            if s not in session:
                continue
            i, b = session[s]
            if b['high'] == b['low']:
                if b['low'] <= p['stop'] or p.get('pending'):
                    p['pending'] = 'Deferred locked-circuit exit'
                continue
            if p.get('pending') or b['open'] <= p['stop']:
                close(s, b['open'], day, p.get('pending', 'Gap through stop'))
                exited.add(s)
        equity_open = cash + unsettled + sum(p['quantity']*session[s][1]['open']
                      if s in session else p['quantity']*marks[s] for s,p in positions.items())
        candidates = []
        for s, (i, b) in session.items():
            if i < max(getattr(cfg,'minimum_warmup_sessions',0), backtest.required_warmup(cfg), entry_warmup)+1:
                continue
            prior_day = data[s][i-1]['date']
            rows = context(s, day)
            prior_rows = context(s, prior_day)
            pivot = None
            if setup == 'screen_proxy':
                signal_index = i-1 if entry == 'pivot' else i-2
                historical_pivot = None
                if cfg.pattern == 'blue_sky':
                    key = id(prior_rows)
                    if key not in prefix_cache:
                        values, highest = [], 0
                        for row in prior_rows:
                            highest = max(highest, row['close'])
                            values.append(highest)
                        prefix_cache[key] = values
                    historical_pivot = prefix_cache[key][signal_index]
                qualified, pivot = setup_proxy(prior_rows, signal_index, cfg, historical_pivot)
                if qualified:
                    # Orders use prior completed setup data. Translate only verified
                    # ex-date actions into today's price units.
                    for action in corporate_actions.actions(data[s]):
                        if action['ex_date'] == day and action['price_basis'] == 'raw':
                            pivot /= action['share_factor']
                    qualified = b['high'] > pivot if entry == 'pivot' else rows[i-1]['close'] > pivot
            elif setup == 'confirmed':
                qualified = matches(prior_rows, i-1, cfg)
            else:
                field = 'close' if setup in ('setup_close','atr30_close') else 'high'
                length = 30 if setup=='atr30_close' else cfg.vcp_window_days
                window=prior_rows[i-1-length:i-1]
                pivot = max(x[field] for x in window)
                if setup=='atr30_close':
                    # Declared fixed-window approximation, not detected bases.
                    first,second=window[:15],window[15:]
                    def tr_pct(j):
                        row=prior_rows[j]
                        return max(row['high']-row['low'],abs(row['high']-prior_rows[j-1]['close']),
                                   abs(row['low']-prior_rows[j-1]['close']))/row['close']
                    atr1=sum(tr_pct(j) for j in range(i-31,i-16))/15
                    atr2=sum(tr_pct(j) for j in range(i-16,i-1))/15
                    volume1=sum(x['volume'] for x in first)
                    high=max(x['high'] for x in prior_rows[max(0,i-253):i])
                    low=min(x['low'] for x in prior_rows[max(0,i-253):i])
                    price=prior_rows[i-1]['close']
                    qualified=(atr1>0 and atr2/atr1<=.9 and volume1>0
                        and sum(x['volume'] for x in second)/volume1<=.9
                        and (max(x['high'] for x in window)-min(x['low'] for x in window))
                            /max(x['high'] for x in window)*100<=35
                        and price>=sum(x['close'] for x in prior_rows[i-50:i])/50
                        and price>=sum(x['close'] for x in prior_rows[i-200:i])/200
                        and price>=high*.7 and price>=low*1.15)
                else:
                    qualified = vcp_setup(prior_rows, i-1, cfg)
                # Setup is fixed yesterday; current high only triggers the order.
                if entry == 'pivot':
                    qualified = qualified and prior_rows[i-1]['close'] <= pivot
                    pivot = max(x[field] for x in rows[i-1-length:i-1])
                    qualified = qualified and b['high'] > pivot
                else:
                    # A completed breakout yesterday, then today's open.
                    qualified = qualified and prior_rows[i-1]['close'] > pivot
            if not qualified:
                continue
            decision_idx = i-1 if entry == 'pivot' else i-2
            strength = rs(data[s][decision_idx]['date']).get(s, 0 if cfg.pattern == 'ipo' else -1)
            liquidity = median(x['close']*x['volume'] for x in prior_rows[max(0,decision_idx-19):decision_idx+1])
            decision_day = data[s][decision_idx]['date']
            item = dict(symbol=s,date=day,pattern=cfg.pattern,decision_date=decision_day,
                        pivot=pivot,rs=strength,rs_population=len(rs_cache[decision_day]),
                        median_turnover=liquidity,technical_eligible=False,quantity=0,
                        eligibility_checked=False,reason='pending')
            audit.append(item)
            if strength < min_rs or liquidity < turnover_floor:
                item['reason'] = 'RS below floor' if strength < min_rs else 'Liquidity below floor'
                rejected['RS / liquidity'] += 1
                continue
            item['technical_eligible'] = True
            candidates.append((s, strength, liquidity, pivot, item))
        candidates.sort(key=lambda x: (-x[1],-x[2],x[0]) if ranking=='rs' else (x[0],))
        entered = set()
        for priority, (s, strength, liquidity, pivot, item) in enumerate(candidates,1):
            item.update(priority=priority,cash_before=cash,unsettled_before=unsettled,
                        equity_open=equity_open,positions_before=len(positions))
            if not allow_entries:
                item['reason'] = 'Entries paused'
                continue
            if s in positions or s in exited:
                item['reason'] = 'Already held' if s in positions else 'Exited today'
                rejected['Already held / exited today'] += 1
                continue
            if len(positions) >= cfg.max_positions:
                item['reason'] = 'Book full'
                rejected['Book full'] += 1
                continue
            i,b = session[s]
            if b['high'] == b['low']:
                item['reason'] = 'Locked circuit'
                rejected['Locked circuit'] += 1
                continue
            if entry_check is not None:
                item['eligibility_checked'] = True
                item['eligibility_passed'] = bool(entry_check(s,day))
                if not item['eligibility_passed']:
                    item['reason'] = 'Entry eligibility filter'
                    rejected['Entry eligibility filter'] += 1
                    continue
            raw_price = max(b['open'], pivot) if entry=='pivot' else b['open']
            price = raw_price*(1+slip)
            stop = price*(1-cfg.stop_pct/100)
            limits = dict(risk=equity_open*cfg.risk_pct/100/(price-stop),
                          position_cap=equity_open*cap_pct/100/price,
                          turnover=liquidity*turnover_pct/100/price,cash=cash/price)
            qty = min(max(0, math.floor(min(limits.values()))), size_order(equity_open, cash, price, stop*(1-slip), cfg.risk_pct, day))
            item.update(entry_price=price,stop=stop,size_limits=limits,
                        sizing_constraint=min(limits,key=limits.get))
            if not qty:
                item['reason'] = 'Cash / size'
                rejected['Cash / size'] += 1
                continue
            charge = equity_charges(price, qty, 'buy', day)['total']
            item.update(reason='Filled',quantity=qty,fees=charge)
            cash -= qty*price+charge
            fees += charge
            total_slippage += qty*raw_price*slip
            positions[s] = dict(entry=price, quantity=qty, stop=stop, best_close=price,
                entry_date=day, entry_cost=qty*price+charge, entry_fee=charge, line_armed=False,
                initial_risk=qty*(price-stop))
            orders.append(dict(id=f'{s}:{day}:buy',symbol=s,date=day,side='buy',quantity=qty,
                               price=price,fees=charge,status='FILLED',reason='Reference breakout'))
            marks[s] = price
            entered.add(s)
        for s,p in list(positions.items()):
            if s not in session:
                continue
            i,b = session[s]
            locked = b['high'] == b['low']
            # Daily OHLC does not prove ordering. Reference convention is an
            # explicit sensitivity, never silently selected as conservative.
            exempt = (s in entered and entry=='pivot' and same_day=='reference'
                      and b['open'] < p['entry'] and b['close'] > b['open']
                      and b['close'] > p['stop'])
            if not locked and not exempt and b['low'] <= p['stop']:
                close(s,p['stop'],day,'Stop / intraday trail')
                continue
            rows = context(s,day)
            average = sum(x['close'] for x in rows[i-49:i+1])/50
            p['best_close'] = max(p['best_close'],b['close'])
            if exits=='reference':
                if b['close'] > average:
                    p['line_armed'] = True
                elif p['line_armed'] and b['close'] < average:
                    p['pending'] = 'Close below SMA50; next open'
            else:
                if b['close'] >= p['entry']*(1+cfg.stop_pct/100*cfg.breakeven_r):
                    breakeven = breakeven_price(p['entry_cost'], p['quantity'], day, cfg.slippage_bps)
                    p['stop'] = max(p['stop'],breakeven,average)
            marks[s] = b['close']
            if not mark_end and not locked and (i==len(data[s])-1 or data[s][i+1]['date']>str(cfg.end)):
                close(s,b['close'],day,'Period-end liquidation (local cost convention)')
        equity = cash+unsettled+sum(p['quantity']*marks[s] for s,p in positions.items())
        peak = max(peak,equity)
        drawdown = max(drawdown,(peak-equity)/peak*100)
        exposure.append(sum(p['quantity']*marks[s] for s,p in positions.items())/equity*100)
        curve.append(dict(date=day,equity=round(equity,2)))
    if not curve:
        raise ValueError('No candles in the chosen test interval.')
    equity = cash+unsettled+sum(p['quantity']*marks[s] for s,p in positions.items())
    state.update(simulation_model='banana_proxy_v1',cash=cash,unsettled=unsettled,positions=positions,
                 marks=marks,trades=trades,curve=curve,orders=orders,last_session=curve[-1]['date'],
                 peak=peak,max_dd=drawdown,total_fees=fees,total_slippage=total_slippage,
                 entry_filter_rejections=dict(rejected),skipped=sum(rejected.values()),
                 exposure=exposure,corporate_actions=action_log)
    state['candidate_audit'] = audit
    wins=[t for t in trades if t['pnl']>0]
    losses=[t for t in trades if t['pnl']<0]
    return dict(metrics=dict(initial_capital=cfg.capital, return_pct=(equity/cfg.capital-1)*100,final_equity=equity,
        max_drawdown_pct=drawdown,trade_count=len(trades),win_rate=len(wins)/len(trades)*100 if trades else 0,
        profit_factor=sum(t['pnl'] for t in wins)/-sum(t['pnl'] for t in losses) if losses else None,
        fees=fees,modeled_fees=fees,modeled_slippage=total_slippage,expectancy_r=None,skipped_entries=sum(rejected.values()),average_deployed_pct=sum(exposure)/len(exposure)),
        state=state,candidate_audit=audit,audit_summary=dict(Counter(a['reason'] for a in audit)),
        corporate_actions=action_log,rejections=dict(rejected),trades=trades,curve=curve,open_positions=positions,
        open_pnl=sum(p['quantity']*marks[s]-p['entry_cost'] for s,p in positions.items()))


def simulate(data, cfg, *, state=None, allow_entries=True, entry_check=None, entry_warmup=0, rs_data=None):
    if cfg.pattern == 'ipo' and not any(rows and rows[0].get('listing_metadata', {}).get('ipo_verified') is True for rows in data.values()):
        raise ValueError('IPO backtest unavailable: frozen inputs contain no verified IPO listing evidence. A first candle is not an IPO date.')
    result = _simulate(data, cfg, setup='screen_proxy', entry=cfg.entry_mode,
                       min_rs={'vcp':70, 'blue_sky':70, 'multiyear':60, 'ipo':0}[cfg.pattern],
                       turnover_floor=10000000, cost_bps=cfg.buy_cost_bps,
                       cap_pct=cfg.reference_cap_pct, turnover_pct=cfg.reference_turnover_pct,
                       same_day=cfg.reference_same_day, rs_method='weighted',state=state,
                       allow_entries=allow_entries,entry_check=entry_check,entry_warmup=entry_warmup,rs_data=rs_data)
    for trade in result['trades']:
        trade['r'] = trade['pnl']/trade['initial_risk']
        trade['hold_days'] = (date.fromisoformat(trade['exit_date'])-date.fromisoformat(trade['entry_date'])).days
    result['metrics']['expectancy_r'] = sum(t['r'] for t in result['trades'])/len(result['trades']) if result['trades'] else None
    result['metrics']['trade_count'] = len(result['trades']) + len(result['open_positions'])
    result['metrics']['closed_trade_count'] = len(result['trades'])
    result['metrics']['open_trade_count'] = len(result['open_positions'])
    result['sector_checks'] = []
    result['entry_filter_rejections'] = result.pop('rejections')
    result['execution_notices'] = NOTICES + [
        'Entry-day OHLC stop ordering: '+cfg.reference_same_day+'. Daily bars do not establish the actual intraday path.',
        'Trade count includes open holdings; win rate and profit factor use closed trades only.'
        ,f'Modeled slippage: {getattr(cfg,"slippage_bps",0):g} bps per side.'
    ]
    return result

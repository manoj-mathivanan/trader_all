"""Isolated video-inspired research; no live orders or saved result artifacts.

Craig: jVs9BMIWyn4, 9:17–10:15. Numerical pivot confirmation, order
expiry, session hours and holding cap below are declared NSE adaptations.
Ray: oQdkFPhqaGk, daily 20/50 SMA cross, executed at next session open.
Neither strategy is a faithful reconstruction of discretionary chart judgement.
"""
from collections import Counter
from math import floor
from statistics import mean, median

from core.execution.zerodha import equity_charges


def aggregate_minutes(bars, size):
    """Only complete, contiguous groups aligned to the regular session open."""
    if size < 1 or not isinstance(size, int):
        raise ValueError('Positive integer interval required.')
    result = []
    for j in range(0, len(bars), size):
        chunk = bars[j:j+size]
        if len(chunk) != size:
            break
        if len({b['date'] for b in chunk}) != 1 or any(
                b['timestamp'] != chunk[0]['timestamp'] + k*60000 for k,b in enumerate(chunk)):
            raise ValueError('Aggregation cannot bridge a missing minute or session.')
        result.append(dict(date=chunk[0]['date'], timestamp=chunk[0]['timestamp'],
                           available_at=chunk[-1]['timestamp']+60000,
                           open=chunk[0]['open'], close=chunk[-1]['close'],
                           high=max(b['high'] for b in chunk), low=min(b['low'] for b in chunk),
                           volume=sum(b['volume'] for b in chunk)))
    return result


def confirmed_pivots(bars, width=2):
    """Map confirmation index to pivots; no pivot exists before its right wing."""
    events = {}
    for k in range(width, len(bars)-width):
        others = bars[k-width:k] + bars[k+1:k+width+1]
        event = {}
        if all(bars[k]['high'] > b['high'] for b in others):
            event['high'] = bars[k]['high']
        if all(bars[k]['low'] < b['low'] for b in others):
            event['low'] = bars[k]['low']
        if event:
            events[k+width] = event
    return events


def structure_trend(bars):
    events = confirmed_pivots(bars)
    highs, lows, result = [], [], []
    for j in range(len(bars)):
        event = events.get(j, {})
        if 'high' in event:
            highs.append(event['high'])
        if 'low' in event:
            lows.append(event['low'])
        result.append(len(highs)>=2 and len(lows)>=2 and highs[-1]>highs[-2] and lows[-1]>lows[-2])
    return result


def mirror_bars(bars):
    """Exact sign reflection: bearish structure becomes bullish structure."""
    return [dict(b,open=-b['open'],close=-b['close'],high=-b['low'],low=-b['high']) for b in bars]


def fvg_setups(current, previous_sessions=(), direction=1):
    """Completed 15m HH/HL context + 1m lower swings broken + bullish FVG.

    Two bars either side confirm pivots. CHoCH is a completed close breaking
    the last lower high while the last two highs AND lows were declining.
    A bullish FVG must form within five bars. Stop below the middle impulse
    candle; midpoint buy limit expires after five minutes. No formation-bar fill.
    """
    if direction not in (1,-1):
        raise ValueError('Direction must be1 or-1.')
    if direction==-1:
        reflected=fvg_setups(mirror_bars(current),[mirror_bars(s) for s in previous_sessions])
        return [dict(s,entry=-s['entry'],stop=-s['stop'],direction=-1) for s in reflected]
    context = []
    for session in previous_sessions:
        context.extend(aggregate_minutes(session, 15))
    context.extend(aggregate_minutes(current, 15))
    trend = structure_trend(context)
    pivots = confirmed_pivots(current)
    highs, lows, setups = [], [], []
    pointer, changed, broken_high = -1, None, None
    for j,bar in enumerate(current):
        completed_at = bar['timestamp']+60000
        while pointer+1<len(context) and context[pointer+1]['available_at']<=completed_at:
            pointer += 1
        event = pivots.get(j, {})
        if 'high' in event:
            highs.append(event['high'])
        if 'low' in event:
            lows.append(event['low'])
        falling = len(highs)>=2 and len(lows)>=2 and highs[-1]<highs[-2] and lows[-1]<lows[-2]
        if falling and bar['close']>highs[-1] and broken_high!=highs[-1]:
            changed, broken_high = j, highs[-1]
        if j<2 or changed is None or j-changed>5 or pointer<0 or not trend[pointer]:
            continue
        if not '09:45'<=bar['time']<='14:29':
            continue
        first, middle = current[j-2:j]
        if first['high']>=bar['low'] or middle['close']<=middle['open'] or bar['close']<=bar['open']:
            continue
        limit = (first['high']+bar['low'])/2
        stop = middle['low']-abs(middle['low'])*.0001
        if not .0005<=(limit-stop)/abs(limit)<=.005:
            continue
        setups.append(dict(signal_index=j, available_at=completed_at, entry=limit, stop=stop,
                           volume=bar['volume'], expires=j+5))
        changed = None  # One order per structural break.
    return setups


def replay_limit(setup, bars, target_r=3, penetration_bps=2, hold_minutes=45,
                 gap_policy='resting_fill'):
    """Pessimistic OHLC replay: penetration, no improvement, stop first.

    Entry candle target is ignored because its extreme can precede the fill.
    Stop on that candle is always honoured. Stops gap at the next open; targets
    require penetration and fill at their limit. All positions exit by 15:15.
    Market exit slippage belongs to settlement; buy/target limits never worsen.
    A gap through the stop fills and stops out immediately. Retaining the limit
    price without improvement is a conservative bound, not an opening-auction
    fill estimate. 'legacy_cancel' exists only to reproduce the earlier control.
    """
    if setup.get('direction',1)==-1:
        reflected=dict(setup,entry=-setup['entry'],stop=-setup['stop'],direction=1)
        trade=replay_limit(reflected,mirror_bars(bars),target_r,penetration_bps,hold_minutes,gap_policy)
        return dict(trade,entry=-trade['entry'],stop=-trade['stop'],exit_raw=-trade['exit_raw'],direction=-1) if trade else None
    entry, stop = setup['entry'], setup['stop']
    if setup.get('direction',1)!=1 or entry<=stop or min(target_r,hold_minutes)<=0 or penetration_bps<0:
        raise ValueError('Invalid direction, stop, target, expiry or penetration.')
    if gap_policy not in ('resting_fill','legacy_cancel'):
        raise ValueError('Unknown limit gap policy.')
    target = entry + target_r*(entry-stop)
    entered = None
    for j in range(setup['signal_index']+1, min(len(bars),setup['expires']+1)):
        bar = bars[j]
        if bar['time']>='14:35':
            return None
        if bar['open']<=stop:
            if gap_policy=='legacy_cancel':
                return None
            entered=j
            break
        if bar['low']<=entry-abs(entry)*penetration_bps/10000:
            entered = j
            break
    if entered is None:
        return None
    for j in range(entered, len(bars)):
        bar = bars[j]
        market = True
        # Scheduled liquidation happens at this bar's open, before its later OHLC.
        if j-entered>=hold_minutes or bar['time']>='15:15' or j==len(bars)-1:
            raw, reason = min(stop,bar['open']) if bar['open']<=stop else bar['open'], 'time'
        elif bar['low']<=stop:
            raw, reason = min(stop,bar['open']), 'stop'
        elif j>entered and bar['high']>=target+abs(target)*penetration_bps/10000:
            raw, reason, market = target, 'target', False
        else:
            continue
        return dict(date=bar['date'], entry_at=bars[entered]['timestamp'],
                    exit_at=bar['timestamp']+60000, entry=entry, exit_raw=raw,
                    market_exit=market, stop=stop, volume=setup['volume'], reason=reason,
                    ambiguity=bar['high']>=target and bar['low']<=stop,
                    gap_entry=bars[entered]['open']<=stop,
                    entry_index=entered, exit_index=j)
    return None


def settlement(trade, quantity, exit_slippage_bps=2, fee_multiplier=1):
    direction=trade.get('direction',1)
    exit_price = trade['exit_raw']*(1-direction*exit_slippage_bps/10000) if trade['market_exit'] else trade['exit_raw']
    entry_side,exit_side=('buy','sell') if direction==1 else ('sell','buy')
    fees = fee_multiplier*sum(equity_charges(price,quantity,side,trade['date'],intraday=True)['total']
                              for price,side in ((trade['entry'],entry_side),(exit_price,exit_side)))
    net = direction*quantity*(exit_price-trade['entry'])-fees
    return dict(trade, quantity=quantity, exit=exit_price, fees=fees, net_pnl=net,
                net_r=net/(quantity*abs(trade['entry']-trade['stop'])))


def portfolio_replay(candidates, cash=100000, exit_slippage_bps=2, fee_multiplier=1,
                     max_friction_r=None, settle=settlement, planned_exit_parts=1):
    """Chronological, unlevered cash ledger, 0.1% equity risk, max three positions.

    Shorts reserve 100% of entry notional as collateral; proceeds cannot fund
    another entry. This is a conservative cash convention, not broker margin.
    Admission uses only entry information. Same-minute exits release cash at
    minute CLOSE. Max three entries per stock/day; daily 1% realised loss halt.
    Prior completed signal volume caps quantity at1%. Fee/risk sizing considers
    planned stop loss including costs. No mark-to-market drawdown claim.
    Optional settlement callback supports partial exits, with all collateral and
    proceeds reserved until final exit. planned_exit_parts budgets stop fees for
    each exit order. Optional entry_raw counts market-entry friction in the guard.
    """
    if planned_exit_parts not in (1,2):raise ValueError('Only one or two planned exit orders supported.')
    initial, active, ledger, counts = cash, [], [], Counter()
    day, opening_equity, daily_pnl = None, cash, 0
    for trade in sorted(candidates,key=lambda t:(t['entry_at'],t['symbol'])):
        remaining = []
        for position in sorted(active,key=lambda t:t['exit_at']):
            if position['exit_at']<=trade['entry_at']:
                cash += position['quantity']*(position['entry']+position.get('direction',1)*(position['exit']-position['entry'])) - position['sell_fees']
                daily_pnl += position['net_pnl']
                ledger.append(position)
            else:
                remaining.append(position)
        active = remaining
        if day != trade['date']:
            day = trade['date']
            if active:
                raise ValueError('Intraday ledger retained an overnight position.')
            opening_equity, daily_pnl = cash, 0
        key = (day,trade['symbol'])
        if len(active)>=3 or counts[key]>=3 or daily_pnl<=-.01*opening_equity:
            continue
        if any(t['symbol']==trade['symbol'] for t in active):
            continue
        # Equity estimate uses cost basis for active positions, not future exit values.
        equity = cash+sum(t['quantity']*t['entry'] for t in active)
        risk = .001*equity
        direction=trade.get('direction',1)
        entry_side,exit_side=('buy','sell') if direction==1 else ('sell','buy')
        width=abs(trade['entry']-trade['stop'])
        quantity = floor(min(cash/trade['entry'],risk/width,.01*trade['volume']))
        while quantity>0:
            buy_fee = fee_multiplier*equity_charges(trade['entry'],quantity,entry_side,day,intraday=True)['total']
            stop_fill = trade['stop']*(1-direction*exit_slippage_bps/10000)
            parts=(quantity,) if planned_exit_parts==1 else (quantity//2,quantity-quantity//2)
            stop_fees=sum(equity_charges(stop_fill,q,exit_side,day,intraday=True)['total'] for q in parts if q)
            loss = direction*quantity*(trade['entry']-stop_fill)+buy_fee+fee_multiplier*stop_fees
            if quantity*trade['entry']+buy_fee<=cash and loss<=risk:
                break
            quantity -= 1
        if quantity<1:
            continue
        if max_friction_r is not None:
            entry_friction=abs(trade['entry']-trade.get('entry_raw',trade['entry']))
            friction = loss-quantity*width+quantity*entry_friction
            raw_width=width-entry_friction
            if raw_width<=0 or friction>max_friction_r*quantity*raw_width:
                continue
        position = settle(trade,quantity,exit_slippage_bps,fee_multiplier)
        position['sell_fees'] = position['fees']-buy_fee
        cash -= quantity*trade['entry']+buy_fee
        active.append(position)
        counts[key] += 1
    for position in sorted(active,key=lambda t:t['exit_at']):
        cash += position['quantity']*(position['entry']+position.get('direction',1)*(position['exit']-position['entry']))-position['sell_fees']
        ledger.append(position)
    ledger.sort(key=lambda t:(t['exit_at'],t['symbol']))
    if abs(cash-initial-sum(t['net_pnl'] for t in ledger))>.00001:
        raise AssertionError('Cash ledger does not reconcile.')
    return ledger


def metrics(ledger):
    gains = sum(max(0,t['net_pnl']) for t in ledger)
    losses = -sum(min(0,t['net_pnl']) for t in ledger)
    pnl, peak, drawdown = 0,0,0
    for t in sorted(ledger,key=lambda t:t['exit_at']):
        pnl += t['net_pnl']; peak=max(peak,pnl); drawdown=max(drawdown,peak-pnl)
    by_symbol = Counter()
    by_day = Counter()
    for t in ledger:
        by_symbol[t['symbol']] += t['net_pnl']
        by_day[t['date']] += t['net_pnl']
    return dict(trades=len(ledger), net_pnl=round(pnl,2),
                raw_price_pnl=round(sum(t.get('direction',1)*t['quantity']*(t['exit_raw']-t['entry']) for t in ledger),2),
                fees=round(sum(t['fees'] for t in ledger),2),
                profit_factor=round(gains/losses,3) if losses else None,
                mean_net_r=round(mean(t['net_r'] for t in ledger),4) if ledger else None,
                median_net_r=round(median(t['net_r'] for t in ledger),4) if ledger else None,
                mean_raw_r=round(mean(t.get('direction',1)*(t['exit_raw']-t['entry'])/abs(t['entry']-t['stop']) for t in ledger),4) if ledger else None,
                win_pct=round(100*sum(t['net_pnl']>0 for t in ledger)/len(ledger),2) if ledger else None,
                directions=dict(Counter('long' if t.get('direction',1)==1 else 'short' for t in ledger)),
                gap_entries=sum(t.get('gap_entry',False) for t in ledger),
                net_without_best_stock=round(pnl-max(by_symbol.values()),2) if by_symbol else None,
                net_without_best_day=round(pnl-max(by_day.values()),2) if by_day else None,
                realised_drawdown=round(drawdown,2), ambiguities=sum(t['ambiguity'] for t in ledger),
                best_stock=by_symbol.most_common(1), worst_stock=by_symbol.most_common()[-1:],
                best_day=by_day.most_common(1), worst_day=by_day.most_common()[-1:])


def sma_cross_orders(rows, fast=20, slow=50):
    """Map completed-close crosses to NEXT session index; no initial trend entry."""
    if not 1<=fast<slow:
        raise ValueError('Fast SMA must be shorter than slow SMA.')
    orders = {}
    previous = None
    for j in range(slow-1,len(rows)-1):
        spread = mean(b['close'] for b in rows[j-fast+1:j+1])-mean(b['close'] for b in rows[j-slow+1:j+1])
        if previous is not None:
            if previous<=0<spread:
                orders[j+1] = 'buy'
            elif previous>=0>spread:
                orders[j+1] = 'sell'
        previous = spread
    return orders


def daily_sma_account(rows, start, end, cash=100000, slippage_bps=2, buy_hold=False):
    """Unlevered per-stock sleeve, cash when flat, next-open crossover executions.

    End-date close liquidates remaining shares solely for comparison. Caller must
    exclude raw split/bonus holdings until share accounting is supported here.
    Price returns exclude dividends/interest. Delivery charges include sell DP.
    """
    orders = {} if buy_hold else sma_cross_orders(rows)
    selected = [j for j,b in enumerate(rows) if start<=b['date']<=end]
    if not selected:
        return None
    initial, quantity, entry_cost, trades = cash, 0,0,[]
    path = []
    for j in selected:
        b = rows[j]
        order = 'buy' if buy_hold and j==selected[0] else None if buy_hold else orders.get(j)
        if order=='buy' and not quantity:
            fill = b['open']*(1+slippage_bps/10000)
            q = floor(cash/(fill*1.002))
            if q>0:
                fee = equity_charges(fill,q,'buy',b['date'])['total']
                entry_cost = fill*q+fee
                cash -= entry_cost
                quantity = q
        if quantity and (order=='sell' or j==selected[-1]):
            raw = b['close'] if j==selected[-1] else b['open']
            fill = raw*(1-slippage_bps/10000)
            fee = equity_charges(fill,quantity,'sell',b['date'])['total']
            proceeds = quantity*fill-fee
            cash += proceeds
            trades.append(dict(date=b['date'],net_pnl=proceeds-entry_cost))
            quantity = 0
        path.append((b['date'],cash+quantity*b['close']))
    peak, dd = initial,0
    for _,equity in path:
        peak=max(peak,equity);dd=max(dd,(peak-equity)/peak)
    return dict(return_pct=100*(cash/initial-1),max_drawdown_pct=100*dd,trades=trades,path=path)

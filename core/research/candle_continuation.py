"""Fixed video-inspired continuation/retest experiments, without broker access.

Reuse the first candle study's sizing and protective-exit contracts. Limit orders
reserve capital before execution and cannot receive an inferred same-bar target.
"""
from collections import Counter
from math import isfinite
from statistics import mean

from core.research.candle_rejection import Rules, exit_trigger, size
from core.research.intraday_costs import upstox_cash_fees


VARIANTS = ('impulse_control', 'weak_pullback', 'gap_market_control', 'gap_retest')
BASELINES = {'weak_pullback': 'impulse_control', 'gap_retest': 'gap_market_control'}


def strong(bar, sign, atr):
    width = bar['high'] - bar['low']
    body = sign * (bar['close'] - bar['open'])
    return width > 0 and body >= .1 * atr and body / width >= .7


def weak(bar, impulse, sign):
    body = abs(bar['close'] - bar['open'])
    original = sign * (impulse['close'] - impulse['open'])
    midpoint = (impulse['open'] + impulse['close']) / 2
    extreme = bar['low'] if sign == 1 else bar['high']
    return (sign * (bar['close'] - bar['open']) <= 0 and body <= original / 3
            and sign * (extreme - midpoint) >= 0)


def orders(bars, context, variant, sign, rules=Rules()):
    """Return decisions indexed by submission open, using only available prices.

    Gap decisions may use that open, never the eventual gap candle high/low/close.
    A retest order activates one bar after submission and expires after three.
    """
    if variant not in VARIANTS or sign not in (-1, 1):
        raise ValueError('Invalid continuation variant/direction.')
    output = {}
    for i in range(2, len(bars) - 1):
        impulse = bars[i]
        if not strong(impulse, sign, context['atr']):
            continue
        base = dict(impulse_index=i, signal_index=i, extreme=impulse['low' if sign == 1 else 'high'],
                    atr=context['atr'], kind='market', reference=impulse['close'])
        if variant == 'impulse_control':
            output.setdefault(i+1, base)
        elif variant == 'weak_pullback':
            pullbacks = []
            for k in range(i+1, min(i+4, len(bars)-1)):
                bar = bars[k]
                if weak(bar, impulse, sign) and len(pullbacks) < 2:
                    pullbacks.append(bar)
                    continue
                if not pullbacks:
                    break
                level = (max([impulse['close']]+[b['high'] for b in pullbacks]) if sign == 1
                         else min([impulse['close']]+[b['low'] for b in pullbacks]))
                midpoint = (impulse['open']+impulse['close'])/2
                extreme = bar['low' if sign == 1 else 'high']
                width = bar['high']-bar['low']
                if (sign*(bar['close']-level) > 0 and width > 0
                        and sign*(bar['close']-bar['open']) / width >= .5
                        and sign*(extreme-midpoint) >= 0):
                    output.setdefault(k+1, dict(base, signal_index=k, reference=level, pullback_bars=len(pullbacks)))
                break
        else:
            j = i+1
            opening = bars[j]['open']
            if sign*(opening-impulse['close']) < max(.02*context['atr'], .0005*impulse['close']):
                continue
            setup = dict(base, decision_index=j)
            if variant == 'gap_retest':
                setup.update(kind='limit', limit=impulse['close'], active_index=j+1, expires_index=j+3)
            output.setdefault(j, setup)
    return {j: order for j, order in output.items()
            if rules.first_entry <= bars[j]['time'] <= rules.last_entry}


def limit_fill(order, bar, index, sign, slip, rules):
    """Opening crossings fill; intrabar touches need penetration, not just touch.

    Always charge the limit (no favorable improvement), even on gap-through-stop
    fills. Protective gap exits then account for the loss; no retroactive cancel.
    """
    if index < order['active_index'] or index > order['expires_index'] or bar['time'] > rules.last_entry:
        return None
    limit = order['limit']
    at_open = sign * (bar['open']-limit) <= 0
    extreme = bar['low' if sign == 1 else 'high']
    penetrated = sign * (extreme-limit) <= -limit*slip
    if at_open or penetrated:
        return limit, at_open
    return None


def simulate(sessions, plan, variant, sign, slippage_bps, rules=Rules()):
    if variant not in VARIANTS or sign not in (-1, 1) or not 0 <= slippage_bps < 10000:
        raise ValueError('Invalid research arguments.')
    slip = slippage_bps/10000
    equity = peak = rules.capital
    max_dd = 0
    trades, curve, diagnostics, order_ledger = [], [], Counter(), []
    entry_side, exit_side = ('buy','sell') if sign == 1 else ('sell','buy')
    for day, selected in sorted(plan.items()):
        capital, used_budget = equity, 0
        positions, pending, counts = {}, {}, Counter()
        bars_by_symbol = {c['symbol']: sessions[c['symbol']][day] for c in selected}
        opportunities = {c['symbol']: orders(bars_by_symbol[c['symbol']], c, variant, sign, rules) for c in selected}
        diagnostics['raw_signals'] += sum(map(len, opportunities.values()))
        for j in range(75):
            for symbol in list(pending):
                order = pending[symbol]
                if j > order['expires_index'] or bars_by_symbol[symbol][j]['time'] > rules.last_entry:
                    diagnostics['unfilled_expired'] += 1
                    order_ledger.append(dict(order, status='expired', completed_index=j))
                    del pending[symbol]
            # Preserve prior-turnover rank at the open. Pending orders reserve
            # both a slot and cash; intrabar exits cannot free either in advance.
            for symbol, bars in bars_by_symbol.items():
                setup = opportunities[symbol].get(j)
                if setup is None:
                    continue
                if symbol in positions or symbol in pending or counts[symbol] >= rules.max_trades_per_stock or len(positions)+len(pending) >= rules.max_positions:
                    diagnostics['position_or_trade_cap'] += 1
                    continue
                raw = setup.get('limit', bars[j]['open'])
                entry = raw if setup['kind']=='limit' else raw*(1+sign*slip)
                stop = setup['extreme']-sign*rules.stop_buffer_atr*setup['atr']
                reserved = sum(o['reserved_budget'] for o in pending.values())
                qty = size(entry, stop, capital, capital-used_budget-reserved, sign, day, slip, rules, 1)
                if not qty:
                    diagnostics['risk_or_capital_rejected'] += 1
                    continue
                fee = upstox_cash_fees(entry, qty, entry_side, day)
                order = dict(symbol=symbol, date=day, quantity=qty, entry=entry, raw_entry=raw,
                             stop=stop, target=entry+rules.target_r*(entry-stop),
                             entry_fee=fee, initial_risk=sign*(entry-stop)*qty,
                             submitted_index=j, submitted_timestamp=bars[j]['timestamp'],
                             signal_timestamp=bars[setup['signal_index']]['timestamp'],
                             reserved_budget=entry*qty+fee, **setup)
                if setup['kind']=='limit':
                    pending[symbol] = order
                    diagnostics['limit_orders_submitted'] += 1
                else:
                    positions[symbol] = dict(order, entry_index=j, entry_time=bars[j]['time'],
                                             entry_timestamp=bars[j]['timestamp'], fill_at_open=True)
                    used_budget += order['reserved_budget']
                    counts[symbol] += 1
            for symbol in list(pending):
                order, bar = pending[symbol], bars_by_symbol[symbol][j]
                filled = limit_fill(order, bar, j, sign, slip, rules)
                if filled is None:
                    continue
                _, at_open = filled
                positions[symbol] = dict(order, entry_index=j, entry_time=bar['time'],
                                         entry_timestamp=bar['timestamp'], fill_at_open=at_open)
                counts[symbol] += 1
                used_budget += order['reserved_budget']
                order_ledger.append(dict(order, status='filled', completed_index=j, fill_at_open=at_open))
                diagnostics['limit_orders_filled'] += 1
                del pending[symbol]
            for symbol in list(positions):
                position, bar = positions[symbol], bars_by_symbol[symbol][j]
                # Entry at an unknown point in the candle: target high/low may
                # precede the fill. Still honor every protective stop touch.
                intrabar_limit = position['kind']=='limit' and j==position['entry_index'] and not position['fill_at_open']
                if intrabar_limit:
                    protective = bar['low'] <= position['stop'] if sign==1 else bar['high'] >= position['stop']
                    target_hit = bar['high'] >= position['target'] if sign==1 else bar['low'] <= position['target']
                    if protective:
                        trigger = (position['stop'], 'stop', target_hit)
                    else:
                        diagnostics['entry_bar_targets_not_credited'] += target_hit
                        trigger = None
                else:
                    trigger = exit_trigger(position, bar, j, sign, rules)
                if trigger is None:
                    continue
                raw_exit, reason, ambiguous = trigger
                fill = raw_exit*(1-sign*slip)
                exit_fee = upstox_cash_fees(fill, position['quantity'], exit_side, day)
                fees = position['entry_fee']+exit_fee
                pnl = sign*(fill-position['entry'])*position['quantity']-fees
                equity += pnl
                trades.append(dict(position, direction='long' if sign==1 else 'short',
                                   exit=fill, raw_exit=raw_exit, exit_time=bar['time'], exit_timestamp=bar['timestamp'],
                                   pnl=pnl, fees=fees, r=pnl/position['initial_risk'], reason=reason,
                                   ambiguous=ambiguous,
                                   slippage=(abs(position['entry']-position['raw_entry'])+abs(fill-raw_exit))*position['quantity']))
                diagnostics['ambiguous_stop_target'] += ambiguous
                del positions[symbol]
            marked = equity+sum(sign*(bars_by_symbol[s][j]['close']-p['entry'])*p['quantity']-p['entry_fee']
                                for s,p in positions.items())
            peak = max(peak, marked)
            max_dd = max(max_dd, (peak-marked)/peak*100)
            if used_budget+sum(o['reserved_budget'] for o in pending.values()) > capital+1e-6:
                raise ValueError('Daily collateral/reservation exceeded.')
        if positions or pending:
            raise ValueError('Orders/positions survived session end.')
        curve.append(dict(date=day, equity=equity))
        if equity <= 0 or not isfinite(equity):
            raise ValueError('Research capital exhausted.')
    wins, losses = [t for t in trades if t['pnl']>0], [t for t in trades if t['pnl']<0]
    months, stocks = {}, {}
    for t in trades:
        month=t['date'][:7]
        months[month]=months.get(month,0)+t['pnl']
        stocks[t['symbol']]=stocks.get(t['symbol'],0)+t['pnl']
    metrics = dict(initial_capital=rules.capital, final_equity=equity,
                   return_pct=(equity/rules.capital-1)*100, trade_count=len(trades),
                   profit_factor=sum(t['pnl'] for t in wins)/-sum(t['pnl'] for t in losses) if losses else None,
                   expectancy_r=mean(t['r'] for t in trades) if trades else None,
                   max_observed_close_drawdown_pct=max_dd,
                   win_rate_pct=len(wins)/len(trades)*100 if trades else None,
                   fees=sum(t['fees'] for t in trades), slippage=sum(t['slippage'] for t in trades))
    return dict(metrics=metrics, trades=trades, curve=curve, diagnostics=dict(diagnostics),
                monthly_pnl=months, stock_pnl=stocks, order_ledger=order_ledger)

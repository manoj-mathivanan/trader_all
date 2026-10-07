"""Hypothetical short-only research with fully reserved entry-notional collateral."""
import math
from datetime import date
from core.execution.paper import PaperBrokerAdapter
from core.research import bearish, corporate_actions


def simulate(datasets, cfg, *, entry_warmup=0):
    events, indices = {}, {}
    for symbol, bars in datasets.items():
        indices[symbol] = {b['date']: i for i, b in enumerate(bars)}
        for i, b in enumerate(bars):
            if str(cfg.start) <= b['date'] <= str(cfg.end):
                events.setdefault(b['date'], {})[symbol] = (i, b)
    if not events:
        raise ValueError('No candles in the chosen test interval.')
    cash, peak, max_dd = cfg.capital, cfg.capital, 0
    positions, marks, trades, orders, curve = {}, {}, [], [], []
    actions, applied = [], set()
    total_fees = total_slippage = total_borrow = skipped = 0
    broker = PaperBrokerAdapter(cfg)
    slip, buy_fee, sell_fee = cfg.slippage_bps/10000, cfg.buy_cost_bps/10000, cfg.sell_cost_bps/10000
    context_cache, statistics_cache = {}, {}

    def context(symbol, day):
        key = (symbol, day)
        if key not in context_cache:
            context_cache[key] = corporate_actions.adjusted_bars(datasets[symbol], day)
        return context_cache[key]

    def statistics(day):
        if day not in statistics_cache:
            from bisect import bisect_left, bisect_right
            returns, eligible, above = {}, 0, 0
            for symbol in datasets:
                idx = indices[symbol].get(day)
                if idx is None:
                    continue
                bars = context(symbol, day)
                if idx >= 126:
                    returns[symbol] = bars[idx]['close']/bars[idx-126]['close']-1
                if idx >= 199:
                    eligible += 1
                    above += bars[idx]['close'] > sum(x['close'] for x in bars[idx-199:idx+1])/200
            values = sorted(returns.values())
            ranks = {s: ((bisect_left(values, r)+bisect_right(values, r)-1)/2/max(len(values)-1, 1)*100, r)
                     for s, r in returns.items()}
            breadth = above/eligible*100 if eligible else None
            coverage = eligible/len(datasets)*100
            gate = not cfg.require_weak_market or (breadth is not None and coverage >= cfg.market_min_coverage_pct
                                                  and breadth <= cfg.max_market_breadth_pct)
            statistics_cache[day] = ranks, gate
        return statistics_cache[day]

    def value(p, mark):
        return p['collateral'] + p['entry_notional'] - p['quantity']*mark

    def close(symbol, raw_price, day, reason):
        nonlocal cash, total_fees, total_slippage
        p = positions.pop(symbol)
        execution = broker.fill(raw_price, p['quantity'], 'buy')
        fill, fee = execution['price'], execution['fees']
        cash += p['collateral'] + p['entry_notional'] - p['quantity']*fill - fee
        total_fees += fee
        total_slippage += execution['slippage']
        pnl = p['entry_notional'] - p['entry_fee'] - p['quantity']*fill - fee - p['borrow_cost']
        orders.append(dict(id=f'{symbol}:{day}:buy', symbol=symbol, date=day, side='buy',
                           quantity=p['quantity'], price=fill, fees=fee, status='FILLED', reason=reason))
        trades.append(dict(symbol=symbol, direction='short', entry_date=p['entry_date'], exit_date=day,
                           signal_date=p['signal_date'], entry=p.get('entry_fill', p['entry']), exit=fill,
                           quantity=p.get('entry_quantity', p['quantity']), exit_quantity=p['quantity'],
                           pnl=pnl, r=pnl/p['initial_risk'], reason=reason, fees=p['entry_fee']+fee,
                           borrow_cost=p['borrow_cost'], stop_trace=p['stop_trace']))

    for day, session in sorted(events.items()):
        context_cache.clear()
        for symbol, p in list(positions.items()):
            elapsed = (date.fromisoformat(day)-date.fromisoformat(p['borrow_day'])).days
            cost = p['quantity']*marks[symbol]*cfg.borrow_cost_bps_year/10000*elapsed/365
            cash -= cost
            p['borrow_cost'] += cost
            p['borrow_day'] = day
            total_borrow += cost
            for action in corporate_actions.actions(datasets[symbol]):
                action_id = symbol+':'+action['id']
                if action_id in applied or action['price_basis'] != 'raw' or not p['entry_date'] < action['ex_date'] <= day:
                    continue
                p, marks[symbol] = corporate_actions.rebase_position(p, marks[symbol], action)
                positions[symbol] = p
                actions.append(dict(id=action_id, symbol=symbol, date=action['ex_date'], kind=action['kind'],
                                    share_factor=action['share_factor'], source=action['source']))
                applied.add(action_id)
        exited, entered = set(), set()
        for symbol, p in list(positions.items()):
            if symbol not in session:
                continue
            p['stop_trace'].append(dict(date=day, stop=p['stop']))
            b = session[symbol][1]
            if b['open'] >= p['stop'] or p['age'] >= cfg.max_hold_days:
                close(symbol, b['open'], day, 'Gap through stop' if b['open'] >= p['stop'] else 'Time exit')
                exited.add(symbol)
        equity_at_open = cash + sum(value(p, session[s][1]['open'] if s in session else marks[s]) for s, p in positions.items())
        candidates = []
        for symbol, (i, b) in session.items():
            idx = i if cfg.entry_mode == 'close' else i-1
            if symbol in positions or symbol in exited or idx < max(entry_warmup, 0):
                continue
            signal_day = datasets[symbol][idx]['date']
            setup = bearish.evaluate(context(symbol, signal_day), cfg, idx)
            if not setup:
                continue
            ranks, gate = statistics(signal_day)
            rank = ranks.get(symbol)
            if not rank or rank[0] > cfg.max_rs_rating or not gate:
                skipped += 1
                continue
            candidates.append((symbol, i, idx, setup, rank))
        candidates.sort(key=lambda x: (x[4][0], x[4][1], x[0]) if cfg.candidate_rank == 'rs_126' else (x[0],))
        for symbol, i, idx, setup, _ in candidates:
            if len(positions) >= cfg.max_positions or equity_at_open <= 0 or cash <= 0:
                skipped += 1
                continue
            b = session[symbol][1]
            if cfg.entry_mode == 'close':
                raw_fill = b['close']
            elif cfg.entry_mode == 'pivot':
                bars = context(symbol, day)
                floor = min(x['low'] for x in bars[idx-bearish.lookback_sessions(cfg):idx])
                raw_fill = min(b['open'], floor)
                if b['low'] > raw_fill:
                    skipped += 1
                    continue
            else:
                raw_fill = b['open']
            fill = raw_fill*(1-slip)
            distance = fill*cfg.stop_pct/100
            stop = fill+distance
            unit_risk = distance + fill*sell_fee + stop*(buy_fee+slip)
            qty = max(0, min(math.floor(equity_at_open*cfg.risk_pct/100/unit_risk), math.floor(cash/(fill*(1+sell_fee)))))
            if not qty:
                skipped += 1
                continue
            execution = broker.fill(raw_fill, qty, 'sell')
            fee = execution['fees']
            notional = qty*fill
            cash -= notional+fee
            total_fees += fee
            total_slippage += execution['slippage']
            positions[symbol] = dict(entry=fill, entry_date=day, signal_date=datasets[symbol][idx]['date'],
                                     entry_notional=notional, collateral=notional, entry_fee=fee, quantity=qty,
                                     stop=stop, best_close=fill, initial_risk=qty*distance, age=0,
                                     borrow_cost=0, borrow_day=day,
                                     stop_trace=[dict(date=day, stop=stop)] if cfg.entry_mode=='next_open' else [])
            marks[symbol] = b['open']
            orders.append(dict(id=f'{symbol}:{day}:sell', symbol=symbol, date=day, side='sell', quantity=qty,
                               price=fill, fees=fee, status='FILLED', reason='Completed-bar bearish signal'))
            entered.add(symbol)
        for symbol, p in list(positions.items()):
            if symbol not in session:
                continue
            idx, b = session[symbol]
            ambiguous_entry = symbol in entered and cfg.entry_mode in ('close', 'pivot')
            if not ambiguous_entry:
                if b['high'] >= p['stop']:
                    close(symbol, p['stop'], day, 'Stop loss / trailing stop')
                    continue
                p['age'] += 1
                p['best_close'] = min(p['best_close'], b['close'])
                if b['close'] <= p['entry']*(1-cfg.stop_pct/100*cfg.breakeven_r):
                    target_pct = {'take_8': 8, 'take_15': 15, 'take_25': 25}.get(cfg.winner_exit)
                    if target_pct is not None and b['close'] <= p['entry']*(1-target_pct/100):
                        close(symbol, b['close'], day, f'Take profit {target_pct}% on short')
                        continue
                    breakeven = (p['entry_notional']-p['entry_fee']-p['borrow_cost'])/p['quantity']/(1+buy_fee)/(1+slip)
                    length = 150 if cfg.winner_exit == 'trail_30w' else 50
                    bars = context(symbol, day)
                    trail = sum(x['close'] for x in bars[idx-length+1:idx+1])/length if target_pct is None and idx+1 >= length else None
                    p['stop'] = min(p['stop'], breakeven, trail if trail is not None else p['best_close']*(1+cfg.trail_pct/100))
            marks[symbol] = b['close']
            future = datasets[symbol]
            if idx == len(future)-1 or future[idx+1]['date'] > str(cfg.end):
                close(symbol, b['close'], day, 'End of available test data')
        equity = cash + sum(value(p, marks[s]) for s, p in positions.items())
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak-equity)/peak*100)
        curve.append(dict(date=day, equity=round(equity, 2), drawdown_pct=round((peak-equity)/peak*100, 4)))
    wins, losses = [t for t in trades if t['pnl'] > 0], [t for t in trades if t['pnl'] < 0]
    return dict(trades=trades, curve=curve, corporate_actions=actions,
                state=dict(cash=cash, positions=positions, orders=orders),
                metrics=dict(initial_capital=cfg.capital, final_equity=curve[-1]['equity'],
                             return_pct=(curve[-1]['equity']/cfg.capital-1)*100, max_drawdown_pct=max_dd,
                             trade_count=len(trades), win_rate=len(wins)/len(trades)*100 if trades else None,
                             expectancy_r=sum(t['r'] for t in trades)/len(trades) if trades else None,
                             profit_factor=sum(t['pnl'] for t in wins)/-sum(t['pnl'] for t in losses) if losses else None,
                             modeled_fees=total_fees, modeled_slippage=total_slippage,
                             modeled_borrow_costs=total_borrow, skipped_entries=skipped))

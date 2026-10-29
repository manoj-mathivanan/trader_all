"""Isolated, causal five-minute level/rejection research. No broker or store writes."""
from collections import Counter
from dataclasses import asdict, dataclass
from math import floor, isfinite
from statistics import mean

from core.research.intraday_costs import upstox_cash_fees


@dataclass(frozen=True)
class Rules:
    capital: float = 1_000_000
    risk_fraction: float = .0025
    max_positions: int = 5
    max_trades_per_stock: int = 2
    target_r: float = 2
    max_holding_bars: int = 12
    tolerance_atr: float = .05
    stop_buffer_atr: float = .05
    min_wick_fraction: float = .5
    close_location: float = .7
    min_stop_fraction: float = .001
    max_stop_fraction: float = .02
    first_entry: str = '09:30'
    last_entry: str = '14:00'
    square_off: str = '15:00'


def rejection(bar, sign, rules):
    width = bar['high'] - bar['low']
    if width <= 0:
        return False
    wick = (min(bar['open'], bar['close']) - bar['low'] if sign == 1
            else bar['high'] - max(bar['open'], bar['close']))
    location = ((bar['close'] - bar['low']) / width if sign == 1
                else (bar['high'] - bar['close']) / width)
    return wick / width >= rules.min_wick_fraction and location >= rules.close_location


def signals(bars, context, variant, sign, rules=Rules()):
    """Levels use prior daily bars or the first three completed session candles.

    First eligible signal is 09:25--09:30; entry is never on the signal bar.
    Confirmation must close beyond the rejection extreme in the next 1--2 bars.
    """
    if variant not in ('level', 'rejection', 'confirmation') or sign not in (-1, 1):
        raise ValueError('Unknown trial or direction.')
    atr = context['atr']
    opening = bars[:3]
    levels = ([('previous_low', context['previous_low']), ('opening_low', min(b['low'] for b in opening))]
              if sign == 1 else
              [('previous_high', context['previous_high']), ('opening_high', max(b['high'] for b in opening))])
    output, pending = {}, []
    for j in range(2, len(bars) - 1):
        bar, next_bar = bars[j], bars[j+1]
        if next_bar['time'] > rules.last_entry:
            break
        if variant == 'confirmation':
            retained = []
            for setup in pending:
                # The protective extreme may not be broken before confirmation.
                if sign * (bar['low' if sign == 1 else 'high'] - setup['extreme']) < 0:
                    continue
                if sign * (bar['close'] - setup['confirmation_level']) > 0:
                    output.setdefault(j+1, dict(setup, signal_index=j))
                elif j - setup['rejection_index'] < 2:
                    retained.append(setup)
            pending = retained
        for label, level in levels:
            tolerance = rules.tolerance_atr * atr
            touched = bar['low'] <= level + tolerance and bar['high'] >= level - tolerance
            reclaimed = sign * (bar['close'] - level) > 0
            if not touched or not reclaimed:
                continue
            if variant != 'level' and not rejection(bar, sign, rules):
                continue
            setup = dict(level_name=label, level=level, rejection_index=j,
                         extreme=bar['low' if sign == 1 else 'high'],
                         confirmation_level=bar['high' if sign == 1 else 'low'],
                         atr=atr, signal_index=j)
            if variant == 'confirmation':
                pending.append(setup)
            else:
                output.setdefault(j+1, setup)
    return {j: setup for j, setup in output.items()
            if rules.first_entry <= bars[j]['time'] <= rules.last_entry}


def exit_trigger(position, bar, index, sign, rules):
    """Gap stops fill at open; targets get no favorable gap improvement."""
    stop, target = position['stop'], position['target']
    stop_hit = bar['low'] <= stop if sign == 1 else bar['high'] >= stop
    target_hit = bar['high'] >= target if sign == 1 else bar['low'] <= target
    if sign * (bar['open'] - stop) <= 0:
        return bar['open'], 'gap_stop', False
    if sign * (bar['open'] - target) >= 0:
        return target, 'target', False
    # Timed exits execute at open, before any use of that candle's high/low.
    if bar['time'] >= rules.square_off or index - position['entry_index'] >= rules.max_holding_bars:
        return bar['open'], 'time_exit', False
    if stop_hit:
        return stop, 'stop', target_hit
    if target_hit:
        return target, 'target', False
    return None


def size(entry, stop, equity, available, sign, day, slip, rules, fee_multiplier):
    distance = sign * (entry - stop)
    if distance <= 0 or not rules.min_stop_fraction <= distance / entry <= rules.max_stop_fraction:
        return 0
    stop_fill = stop * (1 - sign * slip)
    risk = equity * rules.risk_fraction
    budget = min(equity / rules.max_positions, available)
    qty = floor(min(risk / (sign * (entry - stop_fill)), budget / entry))
    buy_side, sell_side = ('buy', 'sell') if sign == 1 else ('sell', 'buy')
    while qty > 0:
        fees_in = upstox_cash_fees(entry, qty, buy_side, day, fee_multiplier)
        fees_out = upstox_cash_fees(stop_fill, qty, sell_side, day, fee_multiplier)
        if entry * qty + fees_in <= budget and sign * (entry - stop_fill) * qty + fees_in + fees_out <= risk:
            return qty
        qty -= 1
    return 0


def simulate(sessions, plan, variant, sign, slippage_bps, rules=Rules(), fee_multiplier=1):
    """Standalone portfolios; cash-collateralized shorts, no daily capital recycling.

    Inputs must have passed the runner's exact regular-session coverage audit.
    """
    if sign not in (-1, 1) or not 0 <= slippage_bps < 10000 or fee_multiplier < 0:
        raise ValueError('Invalid direction or execution assumptions.')
    equity, peak, max_dd = rules.capital, rules.capital, 0
    trades, curve, diagnostics = [], [], Counter()
    slip = slippage_bps / 10000
    for day, selected in sorted(plan.items()):
        starting_equity, used_budget = equity, 0
        positions, counts = {}, Counter()
        by_symbol = {c['symbol']: sessions[c['symbol']][day] for c in selected}
        contexts = {c['symbol']: c for c in selected}
        opportunities = {symbol: signals(bars, contexts[symbol], variant, sign, rules)
                         for symbol, bars in by_symbol.items()}
        diagnostics['raw_signals'] += sum(map(len, opportunities.values()))
        for j in range(75):
            # Entries precede intrabar exits: a later high/low cannot free a slot
            # retrospectively at this open. Daily capital is never recycled.
            for symbol, bars in by_symbol.items():
                setup = opportunities[symbol].get(j)
                if setup is None:
                    continue
                if symbol in positions or counts[symbol] >= rules.max_trades_per_stock or len(positions) >= rules.max_positions:
                    diagnostics['position_or_trade_cap'] += 1
                    continue
                raw = bars[j]['open']
                entry = raw * (1 + sign * slip)
                stop = setup['extreme'] - sign * rules.stop_buffer_atr * setup['atr']
                # Gap entries must still be on the reclaimed side of the known level.
                if sign * (raw - setup['level']) <= 0:
                    diagnostics['entry_gap_invalidated'] += 1
                    continue
                qty = size(entry, stop, starting_equity, starting_equity - used_budget, sign, day, slip, rules, fee_multiplier)
                if qty < 1:
                    diagnostics['risk_or_capital_rejected'] += 1
                    continue
                fee = upstox_cash_fees(entry, qty, 'buy' if sign == 1 else 'sell', day, fee_multiplier)
                used_budget += entry * qty + fee
                position = dict(entry=entry, raw_entry=raw, stop=stop,
                                target=entry + sign * rules.target_r * sign * (entry - stop),
                                quantity=qty, entry_fee=fee, entry_index=j,
                                entry_time=bars[j]['time'], entry_timestamp=bars[j]['timestamp'],
                                signal_timestamp=bars[setup['signal_index']]['timestamp'],
                                initial_risk=sign * (entry - stop) * qty,
                                level_name=setup['level_name'], level=setup['level'])
                positions[symbol] = position
                counts[symbol] += 1
            # Include protective exits on the entry candle, with stop first.
            for symbol in list(positions):
                p = positions[symbol]
                trigger = exit_trigger(p, by_symbol[symbol][j], j, sign, rules)
                if trigger is not None:
                    raw, reason, ambiguous = trigger
                    fill = raw * (1 - sign * slip)
                    fee = upstox_cash_fees(fill, p['quantity'], 'sell' if sign == 1 else 'buy', day, fee_multiplier)
                    pnl = sign * (fill - p['entry']) * p['quantity'] - p['entry_fee'] - fee
                    equity += pnl
                    trades.append({**p, 'symbol': symbol, 'date': day,
                                   'direction': 'long' if sign == 1 else 'short',
                                   'exit': fill, 'raw_exit': raw, 'exit_time': by_symbol[symbol][j]['time'],
                                   'exit_timestamp': by_symbol[symbol][j]['timestamp'], 'reason': reason,
                                   'fees': p['entry_fee'] + fee, 'pnl': pnl, 'r': pnl / p['initial_risk'],
                                   'slippage': (abs(p['entry'] - p['raw_entry']) + abs(fill - raw)) * p['quantity'],
                                   'ambiguous': ambiguous})
                    diagnostics['ambiguous_stop_target'] += ambiguous
                    del positions[symbol]
            # Mark every bar; drawdown is at observed closes, not a tick-level bound.
            marked = equity + sum(sign * (by_symbol[s][j]['close'] - p['entry']) * p['quantity'] - p['entry_fee']
                                  for s, p in positions.items())
            peak = max(peak, marked)
            max_dd = max(max_dd, (peak - marked) / peak * 100)
        if positions:
            raise ValueError('Unclosed research positions at session end.')
        curve.append(dict(date=day, equity=equity))
        if equity <= 0 or not isfinite(equity):
            raise ValueError('Research capital exhausted or nonfinite.')
    wins, losses = [t for t in trades if t['pnl'] > 0], [t for t in trades if t['pnl'] < 0]
    months = {}
    stocks = {}
    for t in trades:
        months[t['date'][:7]] = months.get(t['date'][:7], 0) + t['pnl']
        stocks[t['symbol']] = stocks.get(t['symbol'], 0) + t['pnl']
    return dict(metrics=dict(initial_capital=rules.capital, final_equity=equity,
                            return_pct=(equity / rules.capital - 1) * 100,
                            max_observed_close_drawdown_pct=max_dd, trade_count=len(trades),
                            win_rate_pct=len(wins) / len(trades) * 100 if trades else None,
                            expectancy_r=mean(t['r'] for t in trades) if trades else None,
                            profit_factor=sum(t['pnl'] for t in wins) / -sum(t['pnl'] for t in losses) if losses else None,
                            fees=sum(t['fees'] for t in trades), slippage=sum(t['slippage'] for t in trades)),
                diagnostics=dict(diagnostics), monthly_pnl=months, stock_pnl=stocks,
                trades=trades, curve=curve, rules=asdict(rules))

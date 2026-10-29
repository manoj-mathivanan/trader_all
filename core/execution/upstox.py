"""Shared NSE Upstox Plus trade estimates, reviewed 2026-10-29.

Plus brokerage is applied to every replay date; this is not historical account
plan reconstruction. Pre-October-2024 exchange rates are an approximation.
Excludes AMC, income tax, financing, exercise/assignment and forced square-off.
Amounts remain unrounded until reporting (contract notes aggregate taxes).
"""
import math
from datetime import date

MODEL = 'upstox_plus'
SOURCES = ['https://upstox.com/files/terms-and-condition/plus-pack.pdf',
           'https://upstox.com/brokerage-charges/']


def charges(price, quantity, side, day, *, segment='delivery', dp=True):
    if side not in ('buy', 'sell') or segment not in ('delivery', 'intraday', 'options', 'futures'):
        raise ValueError('Invalid Upstox Plus side or segment.')
    if not all(math.isfinite(x) for x in (price, quantity)) or price <= 0 or quantity < 1:
        raise ValueError('Invalid Upstox Plus fee inputs.')
    session = date.fromisoformat(str(day))
    value = price * quantity
    if not math.isfinite(value):
        raise ValueError('Invalid Upstox Plus notional.')
    modern = session >= date(2026, 3, 1)
    cap = {'delivery': .025, 'intraday': .001, 'futures': .0005}
    brokerage = 30 if segment == 'options' else min(30, value * cap[segment])
    if segment == 'options':
        exchange_rate = .0003553 if modern else .0003503
        stt_rate = (.0015 if session >= date(2026, 4, 1) else .001) if side == 'sell' else 0
    elif segment == 'futures':
        exchange_rate = .0000183 if modern else .0000173
        stt_rate = (.0005 if session >= date(2026, 4, 1) else .0002) if side == 'sell' else 0
    else:
        exchange_rate = (.0000307 if modern else .0000297 if session >= date(2024, 10, 1)
                         else .0000322 if session >= date(2024, 4, 1) else .0000345)
        stt_rate = .001 if segment == 'delivery' else .00025 if side == 'sell' else 0
    exchange = value * exchange_rate
    ipft = value * (.000000001 if modern else .000005 if segment == 'options' else .000001)
    sebi = value * .000001
    stt = value * stt_rate
    stamp = value * {'delivery': .00015, 'intraday': .00003, 'options': .00003, 'futures': .00002}[segment] if side == 'buy' else 0
    dp_base = 20 if segment == 'delivery' and side == 'sell' and dp else 0
    gst = .18 * (brokerage + exchange + ipft + dp_base)
    parts = dict(brokerage=brokerage, exchange=exchange, ipft=ipft, sebi=sebi,
                 stt=stt, stamp=stamp, dp=dp_base, gst=gst)
    return dict(**parts, total=sum(parts.values()))


def equity_charges(price, quantity, side, day, *, intraday=False, dp=True):
    return charges(price, quantity, side, day, segment='intraday' if intraday else 'delivery', dp=dp)


def size_order(equity, cash, fill, stop_fill, risk_pct, day, *, sign=1, intraday=False):
    """Largest quantity satisfying exact capped fees, cash and stop risk."""
    lo, hi = 0, max(0, math.floor(max(0, cash) / fill))
    while lo < hi:
        qty = (lo + hi + 1) // 2
        entry = equity_charges(fill, qty, 'buy' if sign == 1 else 'sell', day, intraday=intraday)['total']
        exit_fee = equity_charges(stop_fill, qty, 'sell' if sign == 1 else 'buy', day, intraday=intraday)['total']
        if qty * fill + entry <= cash and sign * (fill - stop_fill) * qty + entry + exit_fee <= equity * risk_pct / 100:
            lo = qty
        else:
            hi = qty - 1
    return lo


def breakeven_price(entry_cost, quantity, day, slippage_bps, *, intraday=False, sign=1):
    lo, hi = 0, entry_cost / quantity * 2 + 100
    for _ in range(55):
        raw = (lo + hi) / 2
        fill = raw * (1 - sign * slippage_bps / 10000)
        fee = equity_charges(fill, quantity, 'sell' if sign == 1 else 'buy', day, intraday=intraday)['total']
        net = fill * quantity - sign * fee
        if net < entry_cost:
            lo = raw
        else:
            hi = raw
    return hi

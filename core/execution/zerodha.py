"""NSE resident-individual cash equity tariff, reviewed 2026-10-10.

Sources: zerodha.com/charges; Zerodha's 2024-10-01 tariff bulletin;
nsearchives.nseindia.com/content/circulars/FA73061.pdf (2026-03-01).
Trade-level estimates: contract-note aggregation/rounding and account AMC differ.
"""
import math
from datetime import date

SOURCES = ['https://zerodha.com/charges',
           'https://zerodha.com/marketintel/bulletin/391488/revision-in-transactions-charges-from-1st-october-2024',
           'https://nsearchives.nseindia.com/content/circulars/FA73061.pdf']


def equity_charges(price, quantity, side, day, *, intraday=False, dp=True):
    notional = price * quantity
    if side not in ('buy', 'sell') or quantity < 1 or price <= 0 or not math.isfinite(notional):
        raise ValueError('Invalid Zerodha fee inputs.')
    session = date.fromisoformat(str(day))
    if session < date(2024, 10, 1):
        raise ValueError('Zerodha tariff supports sessions from 2024-10-01.')
    brokerage = min(20, notional * .0003) if intraday else 0
    # March 2026 rebalance: 306.99 + .01 per crore, still 307 total.
    exchange = notional * (.000030699 if session >= date(2026, 3, 1) else .0000297)
    ipft = notional * (.000000001 if session >= date(2026, 3, 1) else .000001)
    sebi = notional * .000001
    stt = notional * (.00025 if side == 'sell' else 0) if intraday else notional * .001
    stamp = notional * (.00003 if intraday else .00015) if side == 'buy' else 0
    dp_base = 13 if side == 'sell' and not intraday and dp else 0
    gst = .18 * (brokerage + exchange + ipft + sebi + dp_base)
    parts = dict(brokerage=brokerage, stt=stt, exchange=exchange, ipft=ipft,
                 sebi=sebi, stamp=stamp, dp=dp_base, gst=gst)
    return dict(**parts, total=sum(parts.values()))


def breakeven_price(entry_cost, quantity, day, slippage_bps):
    """Raw sell trigger covering delivery charges, fixed DP and sell slippage."""
    lo, hi = 0, entry_cost / quantity * 2 + 100
    for _ in range(45):
        raw = (lo + hi) / 2
        fill = raw * (1 - slippage_bps / 10000)
        net = fill * quantity - equity_charges(fill, quantity, 'sell', day)['total']
        if net < entry_cost:
            lo = raw
        else:
            hi = raw
    return hi

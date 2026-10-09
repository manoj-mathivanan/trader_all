"""Explicit public Upstox cash-equity fee hypothesis; not an account tariff.

Source: https://upstox.com/brokerage-charges/ (reviewed 2026-10-09).
Current basic brokerage is assumed throughout; historical account plans and
contract-note rounding are unverified. No delivery DP or forced square-off fee.
"""
import math
from datetime import date


def upstox_cash_fees(price, quantity, side, day, multiplier=1):
    if side not in ('buy','sell') or price <= 0 or quantity < 1 or multiplier < 0:
        raise ValueError('Invalid fee input.')
    notional = price*quantity
    if not math.isfinite(notional) or not math.isfinite(multiplier):
        raise ValueError('Fee inputs must be finite.')
    day = date.fromisoformat(str(day))
    if day < date(2024,10,1):
        raise ValueError('Fee hypothesis supports dates from October 2024 only.')
    brokerage = min(20,notional*.001)
    exchange = notional*(.0000307 if day >= date(2026,3,1) else .0000297)
    ipft = notional*(.000000001 if day >= date(2026,3,1) else .000001)
    sebi = notional*.000001
    stt = notional*.00025 if side == 'sell' else 0
    stamp = notional*.00003 if side == 'buy' else 0
    # Include GST on SEBI charges conservatively; source wording varies slightly.
    gst = .18*(brokerage+exchange+ipft+sebi)
    return multiplier*(brokerage+exchange+ipft+sebi+stt+stamp+gst)

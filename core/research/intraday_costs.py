"""Compatibility entry point for shared Upstox Plus intraday fees."""
import math
from core.execution.upstox import equity_charges

def upstox_cash_fees(price, quantity, side, day, multiplier=1):
    if not math.isfinite(multiplier) or multiplier < 0:
        raise ValueError('Invalid fee multiplier.')
    return multiplier*equity_charges(price, quantity, side, day, intraday=True)['total']

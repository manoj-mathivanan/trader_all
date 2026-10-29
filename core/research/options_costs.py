"""Compatibility entry point for shared Upstox Plus NSE options fees."""
from core.execution.upstox import charges

def fees(price, quantity, side, day, *, brokerage=30):
    # Legacy brokerage input cannot override the Plus plan for new executions.
    return charges(price, quantity, side, day, segment='options')

"""Shared cash-constrained percent-risk sizing for daily execution."""
from core.execution.upstox import size_order

def percent_risk_size(equity, cash, fill, stop, config, *, day=None):
    return size_order(equity, cash, fill, stop*(1-config.slippage_bps/10000),
                      config.risk_pct, day)

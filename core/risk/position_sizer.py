"""Shared cash-constrained percent-risk sizing for daily execution."""
import math


def percent_risk_size(equity, cash, fill, stop, config):
    buy_fee = config.buy_cost_bps / 10000
    sell_fee = config.sell_cost_bps / 10000
    slip = config.slippage_bps / 10000
    unit_risk = fill - stop + fill * buy_fee + stop * (sell_fee + slip)
    return max(0, min(math.floor(equity * config.risk_pct / 100 / unit_risk),
                      math.floor(cash / (fill * (1 + buy_fee)))))

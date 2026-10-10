"""Shared cash-constrained percent-risk sizing for daily execution."""
import math


def percent_risk_size(equity, cash, fill, stop, config, *, day=None):
    if getattr(config, 'fee_model', 'custom_bps') == 'zerodha_equity':
        from core.execution.zerodha import equity_charges
        if day is None:
            raise ValueError('Zerodha sizing requires a session date.')
        lo, hi = 0, max(0, math.floor(cash / fill))
        while lo < hi:
            qty = (lo + hi + 1) // 2
            buy = equity_charges(fill, qty, 'buy', day)['total']
            stopped = stop * (1 - config.slippage_bps / 10000)
            sell = equity_charges(stopped, qty, 'sell', day)['total']
            loss = qty * (fill - stopped) + buy + sell
            if qty * fill + buy <= cash and loss <= equity * config.risk_pct / 100:
                lo = qty
            else:
                hi = qty - 1
        return lo
    buy_fee = config.buy_cost_bps / 10000
    sell_fee = config.sell_cost_bps / 10000
    slip = config.slippage_bps / 10000
    unit_risk = fill - stop + fill * buy_fee + stop * (sell_fee + slip)
    return max(0, min(math.floor(equity * config.risk_pct / 100 / unit_risk),
                      math.floor(cash / (fill * (1 + buy_fee)))))

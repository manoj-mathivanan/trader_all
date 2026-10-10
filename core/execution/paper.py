"""Simulated fills only. No broker credentials or order API are used here."""
from typing import Protocol


class BrokerAdapter(Protocol):
    def fill(self, price: float, quantity: int, side: str) -> dict: ...


class PaperBrokerAdapter:
    def __init__(self, config):
        self.config = config

    def fill(self, price, quantity, side, *, day=None, intraday=False):
        if side not in ('buy', 'sell') or price <= 0 or quantity < 1:
            raise ValueError('Invalid simulated order.')
        slip = self.config.slippage_bps / 10000
        rate = (self.config.buy_cost_bps if side == 'buy' else self.config.sell_cost_bps) / 10000
        fill = price * (1 + slip if side == 'buy' else 1 - slip)
        if getattr(self.config, 'fee_model', 'custom_bps') == 'zerodha_equity':
            from core.execution.zerodha import equity_charges
            if day is None:
                raise ValueError('Zerodha fills require the actual session date.')
            charges = equity_charges(fill, quantity, side, day, intraday=intraday)
            return {'price': fill, 'fees': charges['total'], 'charges': charges,
                    'slippage': abs(fill - price) * quantity}
        return {'price': fill, 'fees': fill * quantity * rate,
                'slippage': abs(fill - price) * quantity}

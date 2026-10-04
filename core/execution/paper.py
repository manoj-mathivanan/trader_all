"""Simulated fills only. No broker credentials or order API are used here."""
from typing import Protocol


class BrokerAdapter(Protocol):
    def fill(self, price: float, quantity: int, side: str) -> dict: ...


class PaperBrokerAdapter:
    def __init__(self, config):
        self.config = config

    def fill(self, price, quantity, side):
        if side not in ('buy', 'sell') or price <= 0 or quantity < 1:
            raise ValueError('Invalid simulated order.')
        slip = self.config.slippage_bps / 10000
        rate = (self.config.buy_cost_bps if side == 'buy' else self.config.sell_cost_bps) / 10000
        fill = price * (1 + slip if side == 'buy' else 1 - slip)
        return {'price': fill, 'fees': fill * quantity * rate,
                'slippage': abs(fill - price) * quantity}

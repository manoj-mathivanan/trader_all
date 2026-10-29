"""Simulated fills using the shared Upstox Plus tariff."""
from typing import Protocol
from core.execution.upstox import equity_charges

class BrokerAdapter(Protocol):
    def fill(self, price: float, quantity: int, side: str) -> dict: ...

class PaperBrokerAdapter:
    def __init__(self, config):
        self.config = config

    def fill(self, price, quantity, side, *, day=None, intraday=False, dp=True):
        if day is None:
            raise ValueError('Upstox Plus fills require the actual session date.')
        slip = self.config.slippage_bps / 10000
        fill = price * (1 + slip if side == 'buy' else 1 - slip)
        charges = equity_charges(fill, quantity, side, day, intraday=intraday, dp=dp)
        return dict(price=fill, fees=charges['total'], charges=charges,
                    fee_model='upstox_plus', slippage=abs(fill-price)*quantity)

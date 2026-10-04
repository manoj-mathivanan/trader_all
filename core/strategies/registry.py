"""Small backend registry used by the generic dashboard strategy navigation.

Adding a strategy begins here; strategy-specific execution modules can be wired in
without changing the dashboard shell.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyDefinition:
    id: str
    name: str
    description: str
    status: str
    granularity: str
    trigger_mode: str
    backtest_engine: str | None = None

    def public(self):
        return {"id": self.id, "name": self.name, "description": self.description,
                "status": self.status, "granularity": self.granularity,
                "trigger_mode": self.trigger_mode, "backtest_engine": self.backtest_engine}


REGISTRY = (
    StrategyDefinition("swing_patterns", "Swing patterns", "End-of-day · Indian equities", "active", "daily", "batch", "daily_breakout"),
    StrategyDefinition("intraday_momentum", "Intraday momentum", "Minute bars · planned", "planned", "intraday_1m", "streaming"),
    StrategyDefinition("scalping", "Scalping", "Ticks to minutes · planned", "planned", "tick", "streaming"),
)


def all_strategies():
    return [definition.public() for definition in REGISTRY]


def get_strategy(strategy_id):
    return next((definition for definition in REGISTRY if definition.id == strategy_id), None)

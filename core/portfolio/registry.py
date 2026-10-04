"""Paper execution plugins: a config schema and a runner per implemented strategy.

Momentum must register its own schema/runner here when implemented. The manager,
API, scheduling, and paper settings UI operate on the strategy ID independently.
"""
from dataclasses import dataclass
from typing import Callable
from pydantic import BaseModel
from core.portfolio import paper


@dataclass(frozen=True)
class PaperPlugin:
    config_model: type[BaseModel]
    run_cycle: Callable


PLUGINS = {'swing_patterns': PaperPlugin(paper.PaperConfig, paper.cycle)}


def get_plugin(strategy_id):
    plugin = PLUGINS.get(strategy_id)
    if not plugin:
        raise ValueError('Paper execution is not implemented for this strategy yet.')
    return plugin

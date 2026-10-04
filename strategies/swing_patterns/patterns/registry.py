from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class PatternDefinition:
    id: str
    name: str
    description: str
    history_requirement: str


PATTERNS = (
    PatternDefinition('vcp', 'VCP', 'Volatility contraction with volume dry-up before a pivot breakout.', '50+ sessions'),
    PatternDefinition('blue_sky', 'Blue sky', 'Basing at the all-time high with no overhead supply.', '252+ sessions'),
    PatternDefinition('multiyear', 'Multi-year breakouts', 'A year-plus base releasing back above its old ceiling.', '260+ sessions'),
    PatternDefinition('ipo', 'IPO base', 'A young listing forming its first proper base.', '50+ sessions'),
)


def definitions():
    return [x.__dict__ for x in PATTERNS]


def get(pattern_id):
    return next((x for x in PATTERNS if x.id == pattern_id), None)

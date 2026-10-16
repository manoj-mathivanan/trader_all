"""Shared, serializable rules for investor scans and technical backtests."""
from pydantic import BaseModel, ConfigDict, Field


class Rules(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    resistance_sessions: int = Field(40, ge=20, le=100, title='Resistance sessions')
    max_distance_pct: float = Field(10, ge=.1, le=15, title='Maximum distance below pivot (%)')
    max_extension_pct: float = Field(5, ge=0, le=10, title='Maximum extension above pivot (%)')
    max_base_range_pct: float = Field(30, ge=2, le=40, title='Maximum base range (%)')
    max_contraction_ratio: float = Field(1.15, ge=.1, le=1.5, title='Maximum recent / earlier range')
    max_dry_volume_ratio: float = Field(1.5, ge=.1, le=2, title='Maximum dry / average volume')
    min_breakout_volume_ratio: float = Field(1.05, ge=1, le=5, title='Minimum breakout / average volume')
    min_turnover_rupees: float = Field(5_000_000, ge=0, title='Minimum daily turnover (₹)')
    strict_trend: bool = Field(False, title='Require strict 20/50/100-day alignment')

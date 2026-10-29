from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from core.research.bearish import BearishConfig
from core.research.investor_rules import Rules as InvestorRules

CURRENT_UNIVERSE = 'niftytotalmarket'


class DataPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    universe: Literal["niftytotalmarket"] = Field(CURRENT_UNIVERSE, title="Research universe")


class Settings(DataPreferences):
    # Legacy/internal ranges are retained for frozen research and paper snapshots.
    universe: Literal["nifty50", "nifty500", "niftytotalmarket"] = Field(CURRENT_UNIVERSE, title="Universe")
    start: date = Field(date(2018, 10, 1), title="History from")
    end: date = Field(date(2026, 10, 1), title="History through")

    @model_validator(mode="after")
    def dates(self):
        if self.start >= self.end or (self.end - self.start).days > 3653:
            raise ValueError("Choose an increasing date range of no more than ten years.")
        return self


def current_settings(reference_id=None):
    """Use all 750 members for current research without rewriting frozen inputs."""
    from core.research import store
    with store.LOCK:
        saved = store.read('settings', {})
        value = Settings(**{**saved, 'universe': CURRENT_UNIVERSE})
        if saved and saved.get('universe') != CURRENT_UNIVERSE:
            store.write('settings', {**saved, 'universe': CURRENT_UNIVERSE})
        if reference_id:
            reference = store.read('runs/' + reference_id, {})
            if reference.get('universe'):
                return Settings(**{**value.model_dump(), 'universe': reference['universe']})
        return value


class TradingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: str = Field("Breakout experiment", min_length=1, max_length=80, title="Run name")
    screen_id: str | None = Field(None, max_length=100, title="Saved screen identity")
    # Keep the legacy value valid for old saved experiments; new UI runs default to VCP.
    pattern: Literal["breakout", "vcp", "blue_sky", "multiyear", "ipo"] = Field("breakout", title="Technical screen")
    capital: float = Field(1000000, ge=1000, le=1e10, title="Starting capital (₹)")
    base_days: int = Field(25, ge=5, le=250, title="Base length (sessions)")
    max_depth_pct: float = Field(30, gt=0, le=80, title="Maximum base depth (%)")
    volume_multiple: float = Field(1.5, ge=0.1, le=10, title="Volume / prior 50-session mean")
    sma_days: int = Field(50, ge=5, le=250, title="Trend SMA (sessions)")
    require_long_trend: bool = Field(False, title="Require price above 200-day SMA")
    require_rising_long_trend: bool = Field(False, title="Require rising 200-day SMA (20 sessions)")
    min_rs_rating: float = Field(0, ge=0, le=100, title="Minimum 126-session RS percentile (0 disables)")
    rs_short_lookback: int = Field(63, ge=5, le=252, title="Emerging RS return lookback (sessions)")
    min_short_rs_rating: float = Field(0, ge=0, le=100, title="Minimum emerging RS percentile (0 disables)")
    rs_improvement_sessions: int = Field(20, ge=1, le=126, title="RS improvement lookback (sessions)")
    min_rs_improvement: float = Field(0, ge=0, le=100, title="Minimum RS gain (percentile points, 0 disables)")
    candidate_rank: Literal['alphabetical', 'rs_126', 'fundamental_score'] = Field('alphabetical', title="Simultaneous signal priority")
    min_turnover: float = Field(50000000, ge=0, le=1e12, title="Minimum average turnover (₹)")
    vcp_window_days: int = Field(10, ge=3, le=60, title="VCP contraction window (sessions)")
    vcp_volume_multiple: float = Field(0.8, gt=0, le=1, title="VCP final volume / 50-session mean")
    blue_sky_lookback_days: int = Field(5000, ge=50, le=5000, title="Blue-sky prior high lookback (sessions)")
    multiyear_base_days: int = Field(260, ge=252, le=2500, title="Multiyear base length (sessions)")
    multiyear_max_depth_pct: float = Field(50, gt=0, le=90, title="Multiyear maximum base depth (%)")
    entry_mode: Literal["pivot", "close", "next_open"] = Field("pivot", title="Entry price")
    risk_pct: float = Field(1.5, gt=0, le=5, title="Risk per trade (%)")
    stop_pct: float = Field(8, gt=0, le=50, title="Initial stop (%)")
    winner_exit: Literal["trail_50d", "trail_30w", "trail_pct", "take_8", "take_15", "take_25"] = Field("trail_50d", title="Winner exit")
    skip_weak_markets: bool = Field(False, title="Skip weak markets")
    market_breadth_scope: Literal['market', 'sector'] = Field('market', title='Breadth universe')
    sector_filter: Literal['off', 'trend', 'trend_rs'] = Field('off', title='Sector trend filter')
    market_breadth_pct: float = Field(40, ge=0, le=100, title="Minimum market breadth (%)")
    market_min_coverage_pct: float = Field(80, gt=0, le=100, title="Minimum breadth history coverage (%)")
    ipo_max_age_days: int = Field(730, ge=1, le=3653, title="Maximum IPO age (calendar days)")
    breakeven_r: float = Field(1, ge=0.1, le=10, title="Breakeven trigger (R)")
    trail_pct: float = Field(8, gt=0, le=50, title="Trail below best close (%)")
    max_positions: int = Field(5, ge=1, le=50, title="Maximum open positions")
    max_sector_positions: int = Field(0, ge=0, le=50, title='Maximum positions per sector (0 disables)')
    max_hold_days: int = Field(120, ge=1, le=1000, title="Maximum holding sessions")
    max_open_gap_pct: float = Field(0, ge=0, le=30, title='Maximum upward opening gap (%, 0 disables)')
    require_open_above_pivot: bool = Field(False, title='Require open above breakout level')
    max_extension_pct: float = Field(0, ge=0, le=200, title='Maximum signal extension above SMA50 (%, 0 disables)')
    reentry_cooldown_sessions: int = Field(0, ge=0, le=60, title='Sessions to wait after any exit')
    stalled_exit_sessions: int = Field(0, ge=0, le=120, title='Exit stalled trades after sessions (0 disables)')
    stalled_min_r: float = Field(.5, ge=0, le=3, title='Minimum closing progress before stalled exit (R)')
    failed_breakout_sessions: int = Field(0, ge=0, le=20, title='Early breakout-failure window (sessions, 0 disables)')
    market_risk_scale: float = Field(1, gt=0, le=1, title='Risk multiplier in weak markets (gate off)')
    market_breadth_trend_sessions: int = Field(0, ge=0, le=60, title='Breadth improvement lookback (sessions, 0 disables)')
    fee_model: Literal['upstox_plus', 'custom_bps', 'zerodha_equity'] = Field('upstox_plus', title='Execution fee model')
    # Legacy bps inputs are accepted for saved payload compatibility only.
    # New executions always use the shared Upstox Plus tariff.
    slippage_bps: float = Field(10, ge=0, le=500, title="Slippage per side (bps)")
    buy_cost_bps: float = Field(10, ge=0, le=500, title="Legacy buy bps (ignored; Upstox Plus applies)")
    sell_cost_bps: float = Field(10, ge=0, le=500, title="Legacy sell bps (ignored; Upstox Plus applies)")


    @model_validator(mode='after')
    def sector_breadth_rules(self):
        self.fee_model = 'upstox_plus'
        if self.skip_weak_markets and self.market_breadth_scope == 'sector':
            if self.entry_mode != 'next_open':
                raise ValueError('Sector breadth requires next-session-open entries.')
            if self.market_risk_scale != 1 or self.market_breadth_trend_sessions:
                raise ValueError('Sector breadth does not support market risk scaling or breadth-trend refinements.')
        return self


class BacktestConfig(TradingConfig):
    pattern: Literal['breakout', 'vcp', 'blue_sky', 'multiyear', 'ipo', 'investor_early_breakout'] = Field('breakout', title='Research screen')
    investor_rules: InvestorRules | None = Field(None, title='Investor technical rules')
    simulation_model: Literal['legacy', 'banana_proxy_v1'] = Field('legacy', title='Simulation model')
    reference_same_day: Literal['conservative', 'reference'] = Field('conservative', title='Pivot entry-day stop ordering')
    reference_cap_pct: float = Field(30, ge=5, le=100, title='Maximum reference position (%)')
    reference_turnover_pct: float = Field(10, ge=.5, le=100, title='Maximum median-turnover participation (%)')

    execution_horizon: Literal['swing', 'intraday'] = Field('swing', title='Holding period')
    square_off_time: str = Field('15:00', pattern=r'^\d{2}:\d{2}$', title='Intraday exit cutoff (IST)')
    comparison_run_id: str | None = Field(None, pattern=r'^[0-9a-f]{12}(?:_[a-z0-9]+)?$', title='Frozen comparison run ID')
    minimum_warmup_sessions: int = Field(50, ge=50, le=2500, title="Minimum comparison warmup (sessions)")
    start: date = Field(..., title="Test from")
    end: date = Field(..., title="Test through")
    acknowledge_limitations: bool = Field(False, title="I understand this is an exploratory backtest")

    @model_validator(mode="after")
    def dates(self):
        if self.start >= self.end:
            raise ValueError("Test end must be after test start.")
        if not self.acknowledge_limitations:
            raise ValueError("Acknowledge the data and cost limitations before running.")
        if self.pattern == 'investor_early_breakout':
            if self.entry_mode != 'next_open' or self.execution_horizon != 'swing':
                raise ValueError('Investor technical backtests require swing next-session-open entries.')
            if self.candidate_rank == 'fundamental_score':
                raise ValueError('Investor technical backtests do not use financial or news ranking.')
            if self.require_long_trend or self.require_rising_long_trend:
                raise ValueError('Investor trend qualification uses investor_rules.strict_trend, not the legacy 200-day trend controls.')
            self.investor_rules = self.investor_rules or InvestorRules()
        elif self.investor_rules is not None:
            raise ValueError('Investor rules require the investor early-breakout screen.')
        if self.simulation_model == 'banana_proxy_v1':
            supported = {'name','screen_id','pattern','capital','entry_mode','risk_pct','stop_pct','winner_exit',
                         'candidate_rank','max_positions','fee_model','buy_cost_bps','sell_cost_bps','slippage_bps'}
            for key, field in TradingConfig.model_fields.items():
                if key not in supported and getattr(self,key) != field.default:
                    raise ValueError('Banana proxy does not use legacy control: '+key)
            if (self.pattern not in ('vcp', 'blue_sky', 'multiyear', 'ipo') or self.execution_horizon != 'swing'
                    or self.entry_mode not in ('pivot', 'next_open') or self.winner_exit != 'trail_50d'
                    or self.candidate_rank != 'rs_126'
                    or self.sector_filter != 'off' or self.skip_weak_markets or self.max_sector_positions
                    or self.min_short_rs_rating or self.min_rs_improvement
                    or self.max_open_gap_pct or self.require_open_above_pivot or self.max_extension_pct
                    or self.reentry_cooldown_sessions or self.stalled_exit_sessions or self.failed_breakout_sessions
                    or self.market_risk_scale != 1 or self.market_breadth_trend_sessions):
                raise ValueError('Banana proxy requires long swing pivot/next-open, RS priority, SMA50 close exit, Upstox Plus fees and no legacy refinements.')
        hour, minute = map(int, self.square_off_time.split(':'))
        if not 9*60+20 <= hour*60+minute <= 15*60+20 or minute%5:
            raise ValueError('Choose a five-minute square-off boundary between 09:20 and 15:20 IST.')
        if self.execution_horizon == 'intraday' and self.entry_mode != 'next_open':
            raise ValueError('Intraday backtests require next-session open entries.')
        if self.skip_weak_markets and self.market_breadth_scope == 'sector' and self.execution_horizon != 'swing':
            raise ValueError('Sector breadth currently requires long swing backtests.')
        if self.execution_horizon != 'swing' and (self.min_short_rs_rating or self.min_rs_improvement):
            raise ValueError('Emerging RS filters currently require swing backtests.')
        if self.sector_filter != 'off' and (self.execution_horizon != 'swing' or self.entry_mode != 'next_open'):
            raise ValueError('Sector filters currently require swing next-session-open entries.')
        refinements = (self.max_open_gap_pct or self.require_open_above_pivot or self.max_extension_pct
                       or self.reentry_cooldown_sessions or self.stalled_exit_sessions
                       or self.failed_breakout_sessions or self.market_risk_scale != 1 or self.market_breadth_trend_sessions
                       or self.winner_exit == 'trail_pct')
        if refinements and (self.pattern not in ('vcp', 'blue_sky', 'multiyear', 'ipo', 'breakout', 'investor_early_breakout')
                            or self.execution_horizon != 'swing' or self.entry_mode != 'next_open'):
            raise ValueError('Swing refinements require long swing next-open entries.')
        return self


class BearishBacktestConfig(BacktestConfig, BearishConfig):
    """Research-only short simulation. PaperConfig deliberately stays long-only."""
    pattern: Literal['vcp_breakdown', 'new_lows', 'multiyear_breakdown', 'ipo_breakdown'] = Field('new_lows', title='Bearish screen')
    borrow_cost_bps_year: float = Field(0, ge=0, le=100000, title='Annual stock-borrow cost (bps; 0 excludes)')
    comparison_run_id: str | None = Field(None, pattern=r'^[0-9a-f]{12}(?:_[a-z0-9]+)?$', title='Frozen comparison run ID')
    execution_horizon: Literal['swing', 'intraday'] = Field('swing', title='Short holding period')
    square_off_time: str = Field('15:00', pattern=r'^\d{2}:\d{2}$', title='Intraday buyback cutoff (IST)')

    @model_validator(mode='after')
    def bearish_rules(self):
        if self.sector_filter != 'off':
            raise ValueError('Sector filters currently support long swing strategies only.')
        if self.candidate_rank == 'fundamental_score':
            raise ValueError('Fundamental score priority is available for long buy candidates only.')
        if self.skip_weak_markets or self.require_long_trend or self.require_rising_long_trend or self.min_rs_rating > 0:
            raise ValueError('Use bearish trend, maximum RS and weak-market filters for a bearish backtest.')
        hour, minute = map(int, self.square_off_time.split(':'))
        if not 9*60+20 <= hour*60+minute <= 15*60+20 or minute%5:
            raise ValueError('Choose a five-minute square-off boundary between 09:20 and 15:20 IST.')
        if self.execution_horizon == 'intraday' and (self.entry_mode != 'next_open' or self.borrow_cost_bps_year != 0):
            raise ValueError('Intraday shorts use next-session open entries and no overnight borrow cost.')
        return self

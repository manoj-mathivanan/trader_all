"""Completed-session downside screens; these do not execute long or short trades."""
from bisect import bisect_left, bisect_right
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from core.research import store, market_history, corporate_actions


SCREENS = [('vcp_breakdown', 'VCP breakdown'), ('new_lows', '52-week low'),
           ('multiyear_breakdown', 'Multi-year breakdown'), ('ipo_breakdown', 'IPO base breakdown')]


class BearishConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    pattern: Literal['vcp_breakdown', 'new_lows', 'multiyear_breakdown', 'ipo_breakdown'] = 'vcp_breakdown'
    base_days: int = Field(15, ge=5, le=250, title='Base length (sessions)')
    max_depth_pct: float = Field(35, gt=0, le=80, title='Maximum base depth (%)')
    volume_multiple: float = Field(1, ge=.1, le=10, title='Breakdown volume / prior 50-session mean')
    sma_days: int = Field(50, ge=5, le=250, title='Trend SMA (sessions)')
    require_falling_long_trend: bool = Field(True, title='Require price below falling 200-day SMA')
    max_rs_rating: float = Field(30, ge=0, le=100, title='Maximum 126-session RS percentile')
    min_turnover: float = Field(50000000, ge=0, le=1e12, title='Minimum average turnover (₹)')
    vcp_window_days: int = Field(10, ge=3, le=60, title='Contraction window (sessions)')
    vcp_volume_multiple: float = Field(.9, gt=0, le=1, title='Final contraction volume / 50-session mean')
    low_lookback_days: int = Field(252, ge=50, le=5000, title='Prior low lookback (sessions)')
    multiyear_base_days: int = Field(260, ge=252, le=2500, title='Multi-year base length (sessions)')
    multiyear_max_depth_pct: float = Field(50, gt=0, le=90, title='Multi-year maximum base depth (%)')
    ipo_max_age_days: int = Field(730, ge=1, le=3653, title='Maximum IPO age (calendar days)')
    require_weak_market: bool = Field(True, title='Require weak market breadth')
    max_market_breadth_pct: float = Field(40, ge=0, le=100, title='Maximum symbols above 200-day SMA (%)')
    market_min_coverage_pct: float = Field(80, gt=0, le=100, title='Minimum breadth history coverage (%)')


def lookback_sessions(cfg):
    return (cfg.vcp_window_days if cfg.pattern == 'vcp_breakdown' else
                cfg.low_lookback_days if cfg.pattern == 'new_lows' else
                cfg.multiyear_base_days if cfg.pattern == 'multiyear_breakdown' else cfg.base_days)


def required_history(cfg):
    return 1 + max(126, cfg.sma_days, lookback_sessions(cfg),
                   cfg.vcp_window_days * 3 if cfg.pattern == 'vcp_breakdown' else 0,
                   219 if cfg.require_falling_long_trend else 0)


def evaluate(bars, cfg, i=None):
    """All comparisons use prior bars; the final completed bar is the signal."""
    i = len(bars) - 1 if i is None else i
    window, lookback = cfg.vcp_window_days, lookback_sessions(cfg)
    if i + 1 < required_history(cfg):
        return None
    b = bars[i]
    prior = bars[i-lookback:i]
    floor = min(x['low'] for x in prior)
    ceiling = max(x['high'] for x in prior)
    depth = (ceiling-floor) / ceiling * 100
    avg_volume = sum(x['volume'] for x in bars[i-50:i]) / 50
    sma = sum(x['close'] for x in bars[i-cfg.sma_days+1:i+1]) / cfg.sma_days
    turnover = sum(x['close'] * x['volume'] for x in bars[i-50:i]) / 50
    if not (avg_volume > 0 and b['close'] < floor and b['close'] < sma and turnover >= cfg.min_turnover
            and b['volume'] >= avg_volume * cfg.volume_multiple):
        return None
    if cfg.require_falling_long_trend:
        long_sma = sum(x['close'] for x in bars[i-199:i+1]) / 200
        old_sma = sum(x['close'] for x in bars[i-219:i-19]) / 200
        if b['close'] >= long_sma or long_sma >= old_sma:
            return None
    if cfg.pattern == 'vcp_breakdown':
        windows = [bars[i-window*n:i-window*(n-1)] for n in (3, 2, 1)]
        ranges = [(max(x['high'] for x in w)-min(x['low'] for x in w))/max(x['high'] for x in w) for w in windows]
        volumes = [sum(x['volume'] for x in w)/window for w in windows]
        if not (ranges[0] > ranges[1] > ranges[2] and volumes[0] > volumes[1] > volumes[2]
                and volumes[2] <= avg_volume * cfg.vcp_volume_multiple):
            return None
    if cfg.pattern == 'multiyear_breakdown' and depth > cfg.multiyear_max_depth_pct:
        return None
    if cfg.pattern == 'ipo_breakdown':
        metadata = bars[0].get('listing_metadata', {})
        if not (metadata.get('verified') is True and metadata.get('source') and metadata.get('ipo_verified') is True):
            return None
        age = (date.fromisoformat(b['date']) - date.fromisoformat(metadata.get('ipo_date', metadata['listing_date']))).days
        if not 0 <= age <= cfg.ipo_max_age_days or depth > cfg.max_depth_pct:
            return None
    return dict(date=b['date'], close=b['close'], breakdown_level=floor,
                volume_multiple=b['volume']/avg_volume if avg_volume else None, sma=sma)


def scan(settings, cfg):
    universe = store.read('universes/' + settings.universe, {})
    items = universe.get('instruments', [])
    if not items:
        raise ValueError('Load the universe and daily market history first.')
    reference = market_history.evidence(snapshot=True)
    histories, excluded = {}, []
    today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date().isoformat()
    for item in items:
        record = store.read('bars/' + item['isin'])
        if not record or not record.get('bars'):
            excluded.append(dict(symbol=item['symbol'], reason='Missing daily history'))
            continue
        bars, _ = market_history.prepare(item, record, reference=reference, fingerprint=False)
        bars = [b for b in bars if b['date'] < today]  # Exclude a potentially incomplete current session.
        if not bars:
            excluded.append(dict(symbol=item['symbol'], reason='No eligible completed daily history'))
            continue
        histories[item['symbol']] = (item, bars)
    as_of = max((bars[-1]['date'] for _, bars in histories.values()), default=None)
    ready, returns = {}, {}
    for symbol, (item, bars) in histories.items():
        if bars[-1]['date'] != as_of:
            excluded.append(dict(symbol=symbol, reason='History is stale for the scan session'))
            continue
        bars = corporate_actions.adjusted_bars(bars, as_of)
        ready[symbol] = (item, bars)
        if len(bars) >= 127:
            returns[symbol] = bars[-1]['close'] / bars[-127]['close'] - 1
        else:
            excluded.append(dict(symbol=symbol, reason='Insufficient relative-strength history'))
    values = sorted(returns.values())
    ranks = {s: (bisect_left(values, value)+bisect_right(values, value)-1)/2/max(len(values)-1, 1)*100
             for s, value in returns.items()}
    eligible = [bars for _, bars in ready.values() if len(bars) >= 200]
    breadth = 100 * sum(b[-1]['close'] > sum(x['close'] for x in b[-200:])/200 for b in eligible)/len(eligible) if eligible else None
    coverage = 100 * len(eligible)/len(items)
    gate = not cfg.require_weak_market or (breadth is not None and coverage >= cfg.market_min_coverage_pct
                                         and breadth <= cfg.max_market_breadth_pct)
    matches = []
    for symbol, (item, bars) in ready.items():
        if len(bars) < required_history(cfg):
            if symbol in ranks:
                excluded.append(dict(symbol=symbol, reason=f'Pattern requires {required_history(cfg)} completed sessions'))
            continue
        if symbol not in ranks or ranks[symbol] > cfg.max_rs_rating:
            continue
        result = evaluate(bars, cfg)
        if result and gate:
            matches.append(dict(symbol=symbol, name=item['name'], isin=item['isin'], rs_rating=ranks[symbol], **result))
    return dict(pattern=cfg.pattern, config=cfg.model_dump(), as_of=as_of, universe=settings.universe,
                market_breadth_pct=breadth, market_coverage_pct=coverage, market_gate_passed=gate,
                scanned_symbols=len(ready), total_symbols=len(items), excluded=excluded,
                matches=sorted(matches, key=lambda x: (x['rs_rating'], x['symbol'])))

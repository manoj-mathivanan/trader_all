"""Pure daily-bar pattern predicates. They do not size or execute trades."""
from datetime import date


def _trend_and_liquidity(bars, i, cfg):
    if i < max(cfg.sma_days, 50):
        return False
    sma = sum(x['close'] for x in bars[i - cfg.sma_days + 1:i + 1]) / cfg.sma_days
    turnover = sum(x['close'] * x['volume'] for x in bars[i - 50:i]) / 50
    if getattr(cfg, 'require_long_trend', False) or getattr(cfg, 'require_rising_long_trend', False):
        if i < 199:
            return False
        long_sma = sum(x['close'] for x in bars[i - 199:i + 1]) / 200
        if bars[i]['close'] <= long_sma:
            return False
        if getattr(cfg, 'require_rising_long_trend', False):
            if i < 219:
                return False
            prior_sma = sum(x['close'] for x in bars[i - 219:i - 19]) / 200
            if long_sma <= prior_sma:
                return False
    return bars[i]['close'] > sma and turnover >= cfg.min_turnover


def breakout(bars, i, cfg):
    if i < max(cfg.base_days, cfg.sma_days, 50) or not _trend_and_liquidity(bars, i, cfg):
        return False
    prior = bars[i - cfg.base_days:i]
    high, low = max(x['high'] for x in prior), min(x['low'] for x in prior)
    average_volume = sum(x['volume'] for x in bars[i - 50:i]) / 50
    return (bars[i]['close'] > high and (high - low) / high * 100 <= cfg.max_depth_pct
            and bars[i]['volume'] >= average_volume * cfg.volume_multiple)


def vcp(bars, i, cfg):
    windows = cfg.vcp_window_days
    warmup = max(windows * 3, cfg.sma_days, 50)
    if i < warmup or not _trend_and_liquidity(bars, i, cfg):
        return False
    ranges = []
    volumes = []
    for offset in (3, 2, 1):
        window = bars[i - windows * offset:i - windows * (offset - 1)]
        ranges.append((max(x['high'] for x in window) - min(x['low'] for x in window)) / max(x['high'] for x in window))
        volumes.append(sum(x['volume'] for x in window) / windows)
    prior_high = max(x['high'] for x in bars[i - windows:i])
    average_volume = sum(x['volume'] for x in bars[i - 50:i]) / 50
    return (ranges[0] > ranges[1] > ranges[2] and volumes[0] > volumes[1] > volumes[2]
            and volumes[2] <= average_volume * cfg.vcp_volume_multiple
            and bars[i]['close'] > prior_high and bars[i]['volume'] >= average_volume * cfg.volume_multiple)


def blue_sky(bars, i, cfg):
    # Banana's Blue sky screen is an all-time-high test. Use all available
    # history for the symbol; the configured lookback is only a safety cap.
    lookback = min(cfg.blue_sky_lookback_days, i)
    if i < max(cfg.sma_days, 50) or not _trend_and_liquidity(bars, i, cfg):
        return False
    prior = bars[i - lookback:i]
    average_volume = sum(x['volume'] for x in bars[i - 50:i]) / 50
    return bars[i]['close'] > max(x['high'] for x in prior) and bars[i]['volume'] >= average_volume * cfg.volume_multiple


def multiyear(bars, i, cfg):
    lookback = cfg.multiyear_base_days
    if i < max(lookback, cfg.sma_days, 50) or not _trend_and_liquidity(bars, i, cfg):
        return False
    prior = bars[i - lookback:i]
    high, low = max(x['high'] for x in prior), min(x['low'] for x in prior)
    average_volume = sum(x['volume'] for x in bars[i - 50:i]) / 50
    return ((high - low) / high * 100 <= cfg.multiyear_max_depth_pct
            and bars[i]['close'] > high and bars[i]['volume'] >= average_volume * cfg.volume_multiple)


def ipo(bars, i, cfg):
    """Young-listing base; sourced listing age is required, first-base identity is not proven."""
    metadata = bars[0].get('listing_metadata', {}) if bars else {}
    if metadata.get('verified') is not True or not metadata.get('source') or metadata.get('ipo_verified') is not True:
        return False
    age = (date.fromisoformat(bars[i]['date']) - date.fromisoformat(metadata.get('ipo_date', metadata['listing_date']))).days
    if not 0 <= age <= getattr(cfg, 'ipo_max_age_days', 730):
        return False
    if i < max(cfg.base_days, cfg.sma_days, 50) or not _trend_and_liquidity(bars, i, cfg):
        return False
    prior = bars[i - cfg.base_days:i]
    high, low = max(x['high'] for x in prior), min(x['low'] for x in prior)
    average_volume = sum(x['volume'] for x in bars[i - 50:i]) / 50
    return ((high - low) / high * 100 <= cfg.max_depth_pct
            and bars[i]['close'] > high
            and bars[i]['close'] > sum(x['close'] for x in bars[i - cfg.sma_days + 1:i + 1]) / cfg.sma_days
            and bars[i]['volume'] >= average_volume * cfg.volume_multiple)


SIGNALS = {'breakout': breakout, 'vcp': vcp, 'blue_sky': blue_sky, 'multiyear': multiyear, 'ipo': ipo}


def matches(bars, i, cfg):
    return SIGNALS[cfg.pattern](bars, i, cfg)

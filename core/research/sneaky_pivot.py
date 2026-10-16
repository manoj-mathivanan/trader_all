"""Isolated long-only opening reversal detector; no orders or portfolio dispatch.

Rumers source: https://www.youtube.com/watch?v=zspMXJVbfAY
15-minute levels/candles: 2:26–4:52, 8:37–9:20; crossing entry: 12:44–13:22.
This bounded NSE adaptation uses only prior-session low/high and the first two
opening candles. It does not reproduce discretionary swing levels, delayed
confirmations, line substitutions, or exits shown in the source.
"""
from dataclasses import dataclass
from math import isfinite

from core.research import intraday_data, momentum_indicators


@dataclass(frozen=True)
class OpeningPivotRules:
    # Declared research choices, not numerical parameters from the video.
    level_tolerance_atr: float = 0.05
    min_opening_body_atr: float = 0.25

    def __post_init__(self):
        for value in (self.level_tolerance_atr, self.min_opening_body_atr):
            if not isfinite(value) or value <= 0:
                raise ValueError('Research thresholds must be finite and positive.')


def opening_long_setup(prior_session, current_session, prior_atr,
                       rules=OpeningPivotRules()):
    """Return setup and rejection reason, using completed 09:15–09:45 input.

    Inputs are normalized, completed five-minute bars. The caller must verify
    that prior_session is the immediately preceding regular trading session,
    prior_atr contains no current-day prices, and both sessions share a verified
    price basis. Timestamps in the existing aggregate identify its last constituent
    bar's OPEN; available_at adds five minutes so 09:40 becomes 09:45.

    Entry is a later strict crossing of confirmation_high, NOT a completed third
    candle or next-open market order. Buffers, tick sizes, fills and sizing belong
    to a separately validated simulator. Returning a setup does not imply a fill.
    """
    if not isfinite(prior_atr) or prior_atr <= 0:
        raise ValueError('Prior known ATR must be finite and positive.')
    if not prior_session or not current_session:
        return None, 'missing_session'
    prior_day = prior_session[0]['date']
    day = current_session[0]['date']
    if prior_day >= day:
        raise ValueError('Prior session must precede the signal session.')
    if prior_day in intraday_data.SPECIAL_SESSIONS or day in intraday_data.SPECIAL_SESSIONS:
        return None, 'special_session'
    previous = intraday_data.trading_bars(prior_session, '15:25')
    if len({b['date'] for b in previous}) != 1:
        raise ValueError('Prior session must contain one date.')
    # Slice before validation/aggregation: later candles cannot alter the setup.
    prefix = current_session[:6]
    if len(prefix) < 6:
        return None, 'confirmation_unfinished'
    if len({b['date'] for b in prefix}) != 1:
        raise ValueError('Opening input must contain one date.')
    opening, confirmation = momentum_indicators.aggregate(prefix, 15)
    support = min(b['low'] for b in previous)
    target = max(b['high'] for b in previous)
    tolerance = rules.level_tolerance_atr * prior_atr
    if opening['open'] - opening['close'] < rules.min_opening_body_atr * prior_atr:
        return None, 'opening_not_strong_bearish'
    if abs(opening['low'] - support) > tolerance:
        return None, 'opening_low_away_from_support'
    if abs(confirmation['low'] - support) > tolerance:
        return None, 'confirmation_low_away_from_support'
    if confirmation['close'] <= confirmation['open']:
        return None, 'confirmation_not_bullish'
    if confirmation['close'] <= support:
        return None, 'support_not_reclaimed'
    trigger = confirmation['high']
    if target <= trigger:
        return None, 'target_not_above_trigger'
    return dict(
        version='opening-prior-low-v1', direction='long', date=day,
        prior_session_date=prior_day, available_at=confirmation['timestamp']+300_000,
        entry_window_start='09:45', entry_window_end_exclusive='10:00',
        confirmation_high=trigger, support=support, target_level=target,
        stop_reference_low=min(support, opening['low'], confirmation['low']),
        prior_atr=prior_atr, level_tolerance=tolerance,
        opening_body=opening['open']-opening['close'],
    ), 'setup_ready'


def earlier_session_support(prior_daily, range_low, *, prior_day, lookback=20):
    """Objective proxy: most recent completed session low below prior-day low.

    This is NOT a verified reproduction of the video's discretionary swing low.
    Twenty sessions is a declared research choice. Reject future/unordered data;
    the caller must verify daily and minute price bases before using this level.
    """
    if lookback < 1 or not isfinite(range_low) or range_low <= 0:
        raise ValueError('Invalid support lookback or price.')
    days = [b['date'] for b in prior_daily]
    if not days or days[-1] != prior_day or days != sorted(set(days)):
        raise ValueError('Historical levels need ordered unique days ending at the prior session.')
    for bar in reversed(prior_daily[:-1][-lookback:]):
        if not isfinite(bar['low']) or bar['low'] <= 0:
            raise ValueError('Historical support must be a finite positive price.')
        if bar['low'] < range_low:
            return dict(price=bar['low'], source_date=bar['date'],
                        kind='earlier_session_low_proxy', lookback=lookback)
    return None


def level_long_setups(prior_session, current_session, prior_atr, *,
                      extra_support=None, max_confirmation_candle=3,
                      rules=OpeningPivotRules()):
    """Separate bounded variant: confirmation can be candle two OR three.

    Retains v1's numerical touch/body thresholds. Each confirmation arms a strict
    crossing only during the NEXT 15-minute candle. An unfilled candle-two setup
    expires before a candle-three setup is armed. A stop breach invalidates that
    level; no intraday line substitution or confirmation after candle three.
    Return all eligible setups; a simulator must enforce one filled trade/day.
    """
    if max_confirmation_candle not in (2, 3):
        raise ValueError('Only predeclared two/three-candle confirmation variants are supported.')
    if not isfinite(prior_atr) or prior_atr <= 0:
        raise ValueError('Prior known ATR must be finite and positive.')
    if not prior_session or not current_session:
        return [], 'missing_session'
    day, prior_day = current_session[0]['date'], prior_session[0]['date']
    if prior_day >= day:
        raise ValueError('Prior session must precede the signal session.')
    if day in intraday_data.SPECIAL_SESSIONS or prior_day in intraday_data.SPECIAL_SESSIONS:
        return [], 'special_session'
    previous = intraday_data.trading_bars(prior_session, '15:25')
    if len({b['date'] for b in previous}) != 1:
        raise ValueError('Prior session must contain one date.')
    prefix = current_session[:max_confirmation_candle*3]
    if len(prefix) < 6:
        return [], 'confirmation_unfinished'
    if len({b['date'] for b in prefix}) != 1:
        raise ValueError('Opening input must contain one date.')
    candles = momentum_indicators.aggregate(prefix, 15)
    opening = candles[0]
    if opening['open']-opening['close'] < rules.min_opening_body_atr*prior_atr:
        return [], 'opening_not_strong_bearish'
    support = min(b['low'] for b in previous)
    target = max(b['high'] for b in previous)
    levels = [dict(price=support, source_date=prior_day, kind='prior_session_low')]
    if extra_support is not None:
        if (extra_support['source_date'] >= prior_day or
                not isfinite(extra_support['price']) or not 0 < extra_support['price'] < support):
            raise ValueError('Extra support must be a known earlier price below the prior low.')
        levels.append(dict(extra_support))
    tolerance = rules.level_tolerance_atr*prior_atr
    # Same declared 0.02 ATR structural buffer will be used by the replay.
    stop_buffer = .02*prior_atr
    setups=[]
    for level in levels:
        price=level['price']
        if abs(opening['low']-price)>tolerance:
            continue
        structural_low=min(price,opening['low'])
        invalidation=structural_low-stop_buffer
        for i,confirmation in enumerate(candles[1:],1):
            if confirmation['low'] <= invalidation:
                break  # The originally armed buyer has failed; do not move it lower.
            structural_low=min(structural_low,confirmation['low'])
            if (abs(confirmation['low']-price)>tolerance or
                    confirmation['close']<=confirmation['open'] or
                    confirmation['close']<=price or target<=confirmation['high']):
                continue
            available_at=confirmation['timestamp']+300_000
            start=555+(i+1)*15
            finish=start+15
            setups.append(dict(
                version='opening-level-confirmation-v2', direction='long', date=day,
                prior_session_date=prior_day, available_at=available_at,
                entry_window_start=f'{start//60:02d}:{start%60:02d}',
                entry_window_end_exclusive=f'{finish//60:02d}:{finish%60:02d}',
                confirmation_high=confirmation['high'], support=price,
                support_kind=level['kind'], support_source_date=level['source_date'],
                target_level=target, stop_reference_low=structural_low,
                prior_atr=prior_atr, level_tolerance=tolerance,
                opening_body=opening['open']-opening['close'],
                confirmation_candle=i+1,
            ))
    return sorted(setups,key=lambda s:(s['available_at'],abs(opening['low']-s['support']))), ('setup_ready' if setups else 'no_level_confirmation')


def replay_long_setup(setup, current_session, *, slippage_bps=2,
                      fee_multiplier=1, cash_cap=100_000, risk_cash=1000):
    """Independent-trade development diagnostic, NOT a portfolio backtest.

    Declared fixed choices: stop 0.02 prior ATR below reference, strict crossing
    approximated by 0.001 prior ATR entry buffer, minimum 1.5R to opposite level,
    round-trip friction <=0.25 price R, quantity <=1% preceding completed 5m
    volume. Position quantity includes estimated stop-exit fees in risk budget.
    Entry window is one 15m candle; mandatory exit is 15:00 bar OPEN. Same-bar
    entry/stop ambiguity assumes entry then loss; stop/target ambiguity is
    stop-first. Gap fills are adverse. No favorable target slippage is assumed.
    Tick rounding, queues, historical spreads and shared capital are unmodeled.
    """
    from core.execution.zerodha import equity_charges
    for value in (cash_cap,risk_cash,fee_multiplier):
        if not isfinite(value) or value <= 0:
            raise ValueError('Cash, risk and fee multiplier must be positive.')
    if not isfinite(slippage_bps) or not 0 <= slippage_bps < 10_000:
        raise ValueError('Invalid adverse slippage.')
    bars=intraday_data.trading_bars(current_session,'15:00')
    if any(b['date']!=setup['date'] for b in bars):
        raise ValueError('Replay candles must match the setup date.')
    factor=slippage_bps/10_000
    trigger=setup['confirmation_high']+.001*setup['prior_atr']
    stop=setup['stop_reference_low']-.02*setup['prior_atr']
    target=setup['target_level']
    day=setup['date']
    if stop <= 0 or not stop < trigger < target:
        return None,'invalid_price_levels'
    def charge(price,q,side):
        return equity_charges(price,q,side,day,intraday=True)['total']*fee_multiplier
    for i,bar in enumerate(bars):
        if (bar['timestamp']<setup['available_at'] or
                bar['time']<setup['entry_window_start']):
            continue
        if bar['time']>=setup['entry_window_end_exclusive']:
            break
        if bar['high']<trigger:
            if bar['low']<=stop:
                return None,'support_failed_before_cross'
            continue
        raw_entry=max(bar['open'],trigger)
        entry=raw_entry*(1+factor)
        stop_fill=stop*(1-factor)
        price_risk=entry-stop
        if entry>=target:
            return None,'gap_consumed_target'
        if (target-entry)/price_risk < 1.5:
            return None,'target_room_below_1_5_price_r'
        # Prior constituent volume is known when this 5m execution interval opens.
        limit=min(int(cash_cap/entry),int(risk_cash/(entry-stop_fill)),
                  int(bars[i-1]['volume']*.01) if i else 0)
        lo,hi=0,limit
        while lo<hi:
            q=(lo+hi+1)//2
            buy_fee=charge(entry,q,'buy')
            modeled_loss=q*(entry-stop_fill)+buy_fee+charge(stop_fill,q,'sell')
            if entry*q+buy_fee<=cash_cap and modeled_loss<=risk_cash:
                lo=q
            else:
                hi=q-1
        quantity=lo
        if quantity<1:
            return None,'cash_risk_or_participation_cap'
        buy_fee=charge(entry,quantity,'buy')
        initial_risk=price_risk*quantity
        stop_friction=(entry-raw_entry+stop-stop_fill)*quantity+buy_fee+charge(stop_fill,quantity,'sell')
        if stop_friction>initial_risk*.25:
            return None,'friction_above_0_25_price_r'
        ambiguous_entry=(bar['open']<trigger and bar['low']<=stop)
        ambiguous_exit=False
        for exit_bar in bars[i:]:
            if exit_bar['time']=='15:00':
                raw_exit=exit_bar['open']; exit_reason='cutoff_open'
            elif exit_bar['low']<=stop:
                raw_exit=min(stop,exit_bar['open']); exit_reason='stop'
                ambiguous_exit=exit_bar['high']>=target
            elif exit_bar['high']>=target:
                raw_exit=target; exit_reason='target'
            else:
                continue
            # Entry below trigger + same-bar low cannot use the pre-entry open
            # as an exit gap: assume the adverse stop was reached AFTER entry.
            if exit_bar is bar and exit_reason=='stop':
                raw_exit=stop
            exit_fill=raw_exit*(1-factor)
            fees=buy_fee+charge(exit_fill,quantity,'sell')
            gross=(exit_fill-entry)*quantity
            net=gross-fees
            return dict(date=day,entry_time=bar['time'],exit_time=exit_bar['time'],
                        entry=entry,exit=exit_fill,raw_entry=raw_entry,raw_exit=raw_exit,
                        quantity=quantity,stop=stop,target=target,
                        fees=fees,net_pnl=net,net_r=net/initial_risk,
                        initial_price_risk=initial_risk,
                        modeled_stop_loss=(entry-stop_fill)*quantity+buy_fee+charge(stop_fill,quantity,'sell'),
                        exit_reason=exit_reason,ambiguous_entry=ambiguous_entry,
                        ambiguous_exit=ambiguous_exit,
                        raw_slippage=(entry-raw_entry+raw_exit-exit_fill)*quantity), 'diagnostic_trade'
    return None,'entry_window_expired'


def reprice_diagnostic_trade(trade, *, slippage_bps, fee_multiplier=1):
    """Freeze base-cost eligibility, raw path, quantity and R denominator.

    This isolates cost sensitivity. It deliberately does not resize, drop a
    trade, or change the portfolio when stressed costs exceed base risk limits.
    """
    from core.execution.zerodha import equity_charges
    if (not isfinite(slippage_bps) or not 0<=slippage_bps<10_000 or
            not isfinite(fee_multiplier) or fee_multiplier<=0):
        raise ValueError('Invalid diagnostic cost assumptions.')
    result=dict(trade)
    factor=slippage_bps/10_000
    entry=trade['raw_entry']*(1+factor)
    exit_fill=trade['raw_exit']*(1-factor)
    quantity=trade['quantity']; day=trade['date']
    fees=sum(equity_charges(price,quantity,side,day,intraday=True)['total']
             for price,side in ((entry,'buy'),(exit_fill,'sell')))*fee_multiplier
    pnl=(exit_fill-entry)*quantity-fees
    stop_fill=trade['stop']*(1-factor)
    modeled_stop_loss=(entry-stop_fill)*quantity+(
        equity_charges(entry,quantity,'buy',day,intraday=True)['total']+
        equity_charges(stop_fill,quantity,'sell',day,intraday=True)['total'])*fee_multiplier
    result.update(entry=entry,exit=exit_fill,fees=fees,net_pnl=pnl,
                  net_r=pnl/trade['initial_price_risk'],modeled_stop_loss=modeled_stop_loss,
                  raw_slippage=(entry-trade['raw_entry']+trade['raw_exit']-exit_fill)*quantity)
    return result

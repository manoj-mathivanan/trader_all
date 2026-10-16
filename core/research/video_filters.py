"""Fixed development hypotheses, not parameters selected by backtest results.

Market: prior completed Nifty50 SMA20 versus SMA50, matched to trade direction.
Participation: completed signal minute volume >=1.5x previous20 minute mean.
Displacement: middle FVG candle body >=1x ATR14 known before that candle.
Relative volume is inspired by 0D9yyNrPwdY; all thresholds are research choices.
"""
from statistics import mean
from core.research.video_methods import aggregate_minutes,confirmed_pivots,mirror_bars


def prior_market_regimes(rows):
    """A session's label contains strictly earlier index closes and their date."""
    if any(a['date']>=b['date'] for a,b in zip(rows,rows[1:])):
        raise ValueError('Benchmark sessions must be unique and ordered.')
    result={}
    for j in range(50,len(rows)):
        fast=mean(b['close'] for b in rows[j-20:j])
        slow=mean(b['close'] for b in rows[j-50:j])
        result[rows[j]['date']]=dict(direction=1 if fast>slow else -1 if fast<slow else 0,
                                    as_of=rows[j-1]['date'])
    return result


def setup_features(setup,bars):
    """Only completed bars up through the signal may enter a filter."""
    j=setup['signal_index']
    if j<20 or j>=len(bars):
        raise ValueError('Signal requires20 prior completed minutes.')
    prior_volume=mean(b['volume'] for b in bars[j-20:j])
    ranges=[max(bars[k]['high']-bars[k]['low'],
                abs(bars[k]['high']-bars[k-1]['close']),
                abs(bars[k]['low']-bars[k-1]['close'])) for k in range(j-15,j-1)]
    atr=mean(ranges)
    middle=bars[j-1]
    return dict(relative_volume=bars[j]['volume']/prior_volume if prior_volume>0 else None,
                displacement_atr=abs(middle['close']-middle['open'])/atr if atr>0 else None,
                prior_atr=atr,available_at=bars[j]['timestamp']+60000)


def context_features(current,previous_sessions=(),direction=1):
    """Source-inspired15m context proxies, using only completed frames.

    A close under the last confirmed swing low invalidates bullish context.
    It remains invalid until fresh HH/HL pivots originate after that break.
    Zones are same-session15m three-candle FVGs; a completed close through the
    far edge removes them. The last3 completed entry minutes must put their low
    within a surviving bullish zone identified BEFORE those three minutes began.
    Shorts use exact sign reflection. These
    explicit rules are proxies for Craig's discretionary chart response areas.
    """
    if direction==-1:
        return context_features(mirror_bars(current),[mirror_bars(s) for s in previous_sessions])
    if direction!=1:raise ValueError('Unknown direction.')
    frames=[]
    for session in previous_sessions:frames.extend(aggregate_minutes(session,15))
    frames.extend(aggregate_minutes(current,15))
    events=confirmed_pivots(frames)
    highs=[];lows=[];zones=[];broken=None;states=[]
    for k,bar in enumerate(frames):
        event=events.get(k,{})
        if 'high' in event:highs.append((event['high'],k-2))
        if 'low' in event:lows.append((event['low'],k-2))
        if lows and bar['close']<lows[-1][0] and broken is None:broken=k
        rising=(len(highs)>=2 and len(lows)>=2 and highs[-1][0]>highs[-2][0] and lows[-1][0]>lows[-2][0])
        if broken is not None and rising and highs[-1][1]>broken and lows[-1][1]>broken and bar['close']>=lows[-1][0]:
            broken=None
        zones=[(lo,hi,created) for lo,hi,created in zones if bar['close']>=lo]
        if k>=2 and frames[k-2]['date']==frames[k-1]['date']==bar['date'] and frames[k-2]['high']<bar['low']:
            zones.append((frames[k-2]['high'],bar['low'],bar['available_at']))
        states.append(dict(context_invalidation=broken is None and bool(lows),zones=tuple(zones),
                           available_at=bar['available_at']))
    pointer=-1;result=[]
    for j,bar in enumerate(current):
        while pointer+1<len(frames) and frames[pointer+1]['available_at']<=bar['timestamp']+60000:
            pointer+=1
        if pointer<0 or j<2:
            result.append(dict(context_invalidation=False,higher_fvg_zone=False,available_at=None));continue
        state=states[pointer]
        low=min(b['low'] for b in current[j-2:j+1])
        touch=any(lo<=low<=hi and created<=current[j-2]['timestamp']
                  for lo,hi,created in state['zones'])
        result.append(dict(context_invalidation=state['context_invalidation'],higher_fvg_zone=touch,
                           available_at=state['available_at']))
    return result


def filter_flags(setup,features,regime,prior_stock_day,context=None):
    direction=setup.get('direction',1)
    market=bool(regime and regime['as_of']==prior_stock_day and regime['direction']==direction)
    volume=features['relative_volume'] is not None and features['relative_volume']>=1.5
    displacement=features['displacement_atr'] is not None and features['displacement_atr']>=1
    flags=dict(market=market,relative_volume=volume,displacement=displacement,
               combined=market and volume and displacement)
    if context is not None:
        flags.update(context_invalidation=context['context_invalidation'],higher_fvg_zone=context['higher_fvg_zone'],
                     source_context=context['context_invalidation'] and context['higher_fvg_zone'])
    return flags

"""Fixed NSE adaptations:1m/5m entries and structural/1ATR-minimum stops.

Craig's source entry uses1m. The5m entry and ATR minimum are research hypotheses,
not claims about his rules. All signals map back to minute execution indices.
The default0.05–0.5% stop bounds preserve the original control. The comparison
explicitly allows up to2%. Five-minute expiry and45-minute holding remain fixed.
"""
from statistics import mean
from core.research.video_methods import aggregate_minutes,confirmed_pivots,mirror_bars,structure_trend


def entry_setups(current,previous_sessions=(),direction=1,entry_minutes=1,atr_minimum=False,max_stop_fraction=.005):
    if entry_minutes not in (1,5) or direction not in (1,-1):
        raise ValueError('Only1m/5m entries and long/short directions are supported.')
    if not .0005<=max_stop_fraction<1:
        raise ValueError('Maximum stop fraction must be between0.0005 and1 (exclusive).')
    if direction==-1:
        reflected=entry_setups(mirror_bars(current),[mirror_bars(s) for s in previous_sessions],
                               entry_minutes=entry_minutes,atr_minimum=atr_minimum,max_stop_fraction=max_stop_fraction)
        return [dict(s,entry=-s['entry'],stop=-s['stop'],structural_stop=-s['structural_stop'],direction=-1)
                for s in reflected]
    context=[];history=[]
    for session in previous_sessions:
        context.extend(aggregate_minutes(session,15))
        history.extend(aggregate_minutes(session,entry_minutes))
    entries=aggregate_minutes(current,entry_minutes)
    context.extend(aggregate_minutes(current,15))
    trend=structure_trend(context)
    combined=history+entries
    pivots=confirmed_pivots(entries)
    highs=[];lows=[];setups=[]
    pointer=-1;changed=None;broken_high=None
    for k,bar in enumerate(entries):
        while pointer+1<len(context) and context[pointer+1]['available_at']<=bar['available_at']:
            pointer+=1
        event=pivots.get(k,{})
        if 'high' in event:highs.append(event['high'])
        if 'low' in event:lows.append(event['low'])
        falling=len(highs)>=2 and len(lows)>=2 and highs[-1]<highs[-2] and lows[-1]<lows[-2]
        if falling and bar['close']>highs[-1] and broken_high!=highs[-1]:
            changed,broken_high=k,highs[-1]
        if k<2 or changed is None or k-changed>5 or pointer<0 or not trend[pointer]:continue
        # Signal availability is the end of its final constituent minute.
        minute_index=(k+1)*entry_minutes-1
        if not '09:45'<=current[minute_index]['time']<='14:29':continue
        first,middle=entries[k-2:k]
        if first['high']>=bar['low'] or middle['close']<=middle['open'] or bar['close']<=bar['open']:continue
        entry=(first['high']+bar['low'])/2
        structural=middle['low']-abs(middle['low'])*.0001
        if structural>=entry:continue
        # ATR14 ends BEFORE the middle impulse candle. Prior sessions warm it up;
        # overnight true ranges are included, with action crossings excluded by caller.
        end=len(history)+k-2
        if end<14:continue
        atr=mean(max(combined[j]['high']-combined[j]['low'],
                     abs(combined[j]['high']-combined[j-1]['close']),
                     abs(combined[j]['low']-combined[j-1]['close'])) for j in range(end-13,end+1))
        width=max(entry-structural,atr) if atr_minimum else entry-structural
        if not .0005<=width/abs(entry)<=max_stop_fraction:continue
        floor_used=atr_minimum and atr>entry-structural
        setups.append(dict(signal_index=minute_index,available_at=bar['available_at'],entry=entry,
                           stop=entry-width if floor_used else structural,structural_stop=structural,prior_atr=atr,
                           atr_floor_used=floor_used,
                           entry_minutes=entry_minutes,
                           # Same preceding completed1m participation cap for both frames.
                           volume=current[minute_index]['volume'],expires=minute_index+5))
        changed=None
    return setups

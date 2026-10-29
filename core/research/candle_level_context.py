"""Causal, fixed level/context interpretation for isolated candle research."""
from unittest.mock import patch

from core.research import candle_continuation as execution, candle_rejection as candles


VARIANTS=('geometry_control','known_level','level_context','weak_control','weak_context')
BASELINES={'known_level':'geometry_control','level_context':'known_level','weak_context':'weak_control'}
_original_orders=execution.orders


def state(bars,context):
    """15m pivots become usable only after both right-hand candles complete.

    known_index is the first five-minute candle whose OPEN knows the level.
    Opening-range levels cannot validate their own final constituent candle.
    """
    groups=[]
    for start in range(0,len(bars)-2,3):
        chunk=bars[start:start+3]
        groups.append(dict(open=chunk[0]['open'],close=chunk[-1]['close'],
                           high=max(b['high'] for b in chunk),low=min(b['low'] for b in chunk),
                           known_index=start+3))
    levels=[dict(name='previous_low',role='support',price=context['previous_low'],known_index=0),
            dict(name='previous_high',role='resistance',price=context['previous_high'],known_index=0),
            dict(name='opening_low',role='support',price=groups[0]['low'],known_index=3),
            dict(name='opening_high',role='resistance',price=groups[0]['high'],known_index=3)]
    for center in range(2,len(groups)-2):
        neighbors=groups[center-2:center]+groups[center+1:center+3]
        known=groups[center+2]['known_index']
        for field,role in [('low','support'),('high','resistance')]:
            is_pivot=(all(groups[center][field]<b[field] for b in neighbors) if field=='low'
                      else all(groups[center][field]>b[field] for b in neighbors))
            if is_pivot:
                levels.append(dict(name=f'pivot_{field}_{center}',role=role,price=groups[center][field],known_index=known,
                                   pivot_center_index=center))
    return dict(groups=groups,levels=levels)


def active_levels(snapshot,index,atr):
    available=[g for g in snapshot['groups'] if g['known_index']<=index]
    result=[]
    for level in snapshot['levels']:
        if level['known_index']>index:
            continue
        sign=1 if level['role']=='support' else -1
        broken=any(g['known_index']>=level['known_index'] and sign*(g['close']-level['price'])<-.05*atr for g in available)
        if not broken:
            result.append(level)
    return result


def trend(snapshot,index,sign):
    groups=[g for g in snapshot['groups'] if g['known_index']<=index]
    if len(groups)<2:
        return False
    previous,current=groups[-2:]
    return sign*(current['high']-previous['high'])>0 and sign*(current['low']-previous['low'])>0


def context_gate(bars,context,snapshot,setup,index,sign,require_trend):
    """Select levels born before the pattern, not levels created by its outcome."""
    signal=setup['signal_index']
    anchor=setup.get('impulse_index',signal)
    candidates=active_levels(snapshot,anchor,context['atr'])
    still_active={l['name'] for l in active_levels(snapshot,signal,context['atr'])}
    role='support' if sign==1 else 'resistance'
    tolerance=.05*context['atr']
    touched=[]
    # A continuation must touch the known level during its impulse/pullback;
    # the later resumption candle cannot invent the touch retrospectively.
    touches=range(anchor,signal) if 'impulse_index' in setup else [signal]
    for level in candidates:
        if level['role']!=role or level['name'] not in still_active:
            continue
        if not any(bars[k]['low']<=level['price']+tolerance and bars[k]['high']>=level['price']-tolerance for k in touches):
            continue
        if sign*(bars[signal]['close']-level['price'])<=0 or sign*(bars[index]['open']-level['price'])<=0:
            continue
        touched.append(level)
    if not touched:
        return None
    # Nearest touched level; deterministic source-name tie-break, no best-result choice.
    level=min(touched,key=lambda l:(abs(bars[signal]['close']-l['price']),l['name']))
    metadata=dict(context_level=level['price'],context_level_name=level['name'],
                  context_level_known_index=level['known_index'],context_anchor_index=anchor)
    if require_trend:
        if not trend(snapshot,anchor,sign):
            return None
        raw=bars[index]['open']
        stop=setup['extreme']-sign*.05*context['atr']
        risk=sign*(raw-stop)
        if risk<=0:
            return None
        opposing=[l for l in active_levels(snapshot,signal,context['atr'])
                  if l['role']!=role and sign*(l['price']-raw)>0]
        room=min((sign*(l['price']-raw) for l in opposing),default=None)
        if room is not None and room<2*risk:
            return None
        metadata.update(context_trend=True,opposing_room_r=room/risk if room is not None else None)
    return metadata


def opportunities(bars,context,variant,sign,rules=candles.Rules(),snapshot=None):
    if variant not in VARIANTS or sign not in (-1,1):
        raise ValueError('Unknown context trial/direction.')
    if variant in ('weak_control','weak_context'):
        raw=_original_orders(bars,context,'weak_pullback',sign,rules)
        if variant=='weak_control':
            return raw
    else:
        raw={i+1:dict(signal_index=i,extreme=b['low' if sign==1 else 'high'],atr=context['atr'],
                      kind='market',reference=b['close'])
             for i,b in enumerate(bars[:-1]) if i>=2 and candles.rejection(b,sign,rules)
             and rules.first_entry<=bars[i+1]['time']<=rules.last_entry}
        if variant=='geometry_control':
            return raw
    snapshot=snapshot or state(bars,context)
    output={}
    for j,setup in raw.items():
        metadata=context_gate(bars,context,snapshot,setup,j,sign,variant in ('level_context','weak_context'))
        if metadata is not None:
            output[j]=dict(setup,**metadata)
    return output


def build_states(inputs):
    return {(c['symbol'],day):state(inputs['sessions'][c['symbol']][day],c)
            for day,selected in inputs['plan'].items() for c in selected}


def simulate(inputs,variant,sign,slip,states):
    def provider(bars,context,ignored_variant,direction,rules):
        return opportunities(bars,context,variant,direction,rules,states[(context['symbol'],bars[0]['date'])])
    with patch.object(execution,'orders',provider):
        return execution.simulate(inputs['sessions'],inputs['plan'],'impulse_control',sign,slip)

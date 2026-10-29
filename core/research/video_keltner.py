"""Provisional NSE adaptation of0D9yyNrPwdY; oscillator chart unverified.

Chande CMO14 interpretation, EMA20, Wilder ATR10 (declared choice),1.5 bands,
RVOL vs20 preceding3m bars, next1m market open. Exit percentage, midline buffer,
stop bounds and45m cap are declared adaptations, not exact source rules.
"""
from statistics import mean
from core.execution.upstox import equity_charges
from core.research.video_methods import aggregate_minutes,mirror_bars


def indicators(rows):
    result=[];ema=None;atr=None;trs=[]
    for j,b in enumerate(rows):
        ema=b['close'] if ema is None else ema+(b['close']-ema)*2/21
        tr=b['high']-b['low'] if not j else max(b['high']-b['low'],abs(b['high']-rows[j-1]['close']),abs(b['low']-rows[j-1]['close']))
        trs.append(tr)
        if j==9:atr=mean(trs)
        elif j>9:atr+=(tr-atr)/10
        cmo=None
        if j>=14:
            changes=[rows[k]['close']-rows[k-1]['close'] for k in range(j-13,j+1)]
            total=sum(abs(x) for x in changes)
            cmo=100*sum(changes)/total if total else 0
        pv=mean(x['volume'] for x in rows[j-20:j]) if j>=20 else 0
        result.append(dict(basis=ema,atr=atr,cmo=cmo,rvol=b['volume']/pv if pv else None,
                           upper=ema+1.5*atr if atr is not None else None,
                           lower=ema-1.5*atr if atr is not None else None,
                           available_at=b['available_at']))
    return result


def setups(current,previous_sessions=(),direction=1):
    if direction==-1:
        signals,series=setups(mirror_bars(current),[mirror_bars(s) for s in previous_sessions])
        return [dict(s,stop=-s['stop'],direction=-1) for s in signals],[dict(v,basis=-v['basis']) for v in series]
    if direction!=1:raise ValueError('Invalid direction.')
    history=[b for s in previous_sessions for b in aggregate_minutes(s,3)]
    frames=aggregate_minutes(current,3);all_rows=history+frames
    series=indicators(all_rows);offset=len(history);signals=[]
    for k,b in enumerate(frames):
        j=offset+k;v=series[j]
        minute_index=(k+1)*3-1
        if j<20 or not '09:45'<=current[minute_index]['time']<='14:29':continue
        if (b['close']>v['upper'] and all_rows[j-1]['close']<=series[j-1]['upper']
                and b['close']>b['open'] and v['cmo']>0 and v['rvol']>1.5):
            stop=v['basis']-abs(v['basis'])*.0001
            signals.append(dict(signal_index=minute_index,available_at=v['available_at'],stop=stop,
                                volume=current[minute_index]['volume'],direction=1))
    return signals,series[offset:]


def replay(setup,bars,series,scaled=False,entry_slippage_bps=2,hold_minutes=45):
    if setup.get('direction',1)==-1:
        reflected=dict(setup,stop=-setup['stop'],direction=1)
        trade=replay(reflected,mirror_bars(bars),[dict(v,basis=-v['basis']) for v in series],scaled,entry_slippage_bps,hold_minutes)
        return dict(trade,entry=-trade['entry'],entry_raw=-trade['entry_raw'],stop=-trade['stop'],exit_raw=-trade['exit_raw'],direction=-1,
                    exit_legs=[dict(v,raw=-v['raw']) for v in trade['exit_legs']]) if trade else None
    entered=setup['signal_index']+1
    if entered>=len(bars) or bars[entered]['time']>='14:35':return None
    entry=bars[entered]['open']+abs(bars[entered]['open'])*entry_slippage_bps/10000
    initial=setup['stop'];width=entry-initial
    if not .0005<=width/abs(entry)<=.02:return None
    stop=initial;target=entry+width*(1 if scaled else 2);partial=None;pointer=-1
    for j in range(entered,len(bars)):
        b=bars[j]
        while pointer+1<len(series) and series[pointer+1]['available_at']<=b['timestamp']:pointer+=1
        if partial is not None and pointer>=0:
            basis=series[pointer]['basis'];stop=max(stop,basis-abs(basis)*.0001)
        if j-entered>=hold_minutes or b['time']>='15:15' or j==len(bars)-1:
            raw,reason,market=min(b['open'],stop) if b['open']<=stop else b['open'],'time',True
        elif b['low']<=stop:
            raw,reason,market=min(b['open'],stop),'trail' if partial else 'stop',True
        elif partial is None and b['high']>=target+abs(target)*.0002:
            # Market entry is at OPEN; high is after entry, unlike resting limits.
            if scaled:
                partial=dict(raw=target,market=False,index=j)
                continue
            raw,reason,market=target,'target',False
        else:continue
        legs=([partial] if partial else [])+[dict(raw=raw,market=market,index=j)]
        weighted=sum(v['raw'] for v in legs)/len(legs)
        return dict(date=b['date'],entry_at=bars[entered]['timestamp'],exit_at=b['timestamp']+60000,
                    entry=entry,entry_raw=bars[entered]['open'],stop=initial,exit_raw=weighted,exit_legs=legs,market_exit=market,
                    volume=setup['volume'],reason=reason,ambiguity=b['low']<=stop and b['high']>=target,
                    entry_index=entered,exit_index=j,direction=1,gap_entry=False)
    return None


def settle(trade,quantity,exit_slippage_bps=2,fee_multiplier=1):
    """Charge actual sides on each exit; hold partial cash until final exit.

    For odd shares the first exit takes floor(q/2), remainder stays on trail.
    No reinvestment or partial equity release occurs in the shared ledger.
    """
    direction=trade.get('direction',1);legs=trade['exit_legs']
    parts=(quantity,) if len(legs)==1 else (quantity//2,quantity-quantity//2)
    entry_side,exit_side=('buy','sell') if direction==1 else ('sell','buy')
    fees=equity_charges(trade['entry'],quantity,entry_side,trade['date'],intraday=True)['total']
    proceeds=raw_proceeds=0
    for leg,q in zip(legs,parts):
        if not q:continue
        price=leg['raw']*(1-direction*exit_slippage_bps/10000) if leg['market'] else leg['raw']
        proceeds+=price*q;raw_proceeds+=leg['raw']*q
        fees+=equity_charges(price,q,exit_side,trade['date'],intraday=True)['total']
    fees*=fee_multiplier
    net=direction*(proceeds-trade['entry']*quantity)-fees
    return dict(trade,quantity=quantity,exit=proceeds/quantity,exit_raw=raw_proceeds/quantity,
                fees=fees,net_pnl=net,net_r=net/(quantity*abs(trade['entry']-trade['stop'])))

"""Video-inspired four-week range breakout on daily cash equities; research only."""
from datetime import date, timedelta
from math import floor
from statistics import mean

from core.execution.upstox import equity_charges, size_order


def signals(bars, variant='four_week'):
    if variant not in ('four_week', 'twenty_session'):
        raise ValueError('Unknown range variant.')
    result = {}
    for i, bar in enumerate(bars):
        current = date.fromisoformat(bar['date'])
        monday = current-timedelta(days=current.weekday())
        first = monday-timedelta(weeks=4)
        window = [b for b in bars[max(0, i-35):i]
                  if first.isoformat() <= b['date'] < monday.isoformat()] if variant == 'four_week' else bars[max(0,i-20):i]
        if len(window) < (12 if variant == 'four_week' else 20):
            continue
        if variant == 'four_week' and (date.fromisoformat(window[0]['date'])-first).days > 4:
            continue
        high, low = max(b['high'] for b in window), min(b['low'] for b in window)
        result[bar['date']] = dict(high=high, low=low, close=bar['close'],
            bullish=bar['close'] > high, bearish=bar['close'] < low,
            turnover=mean(b['close']*b['volume'] for b in bars[max(0,i-20):i]),
            last_input_date=window[-1]['date'])
    return result


def simulate(datasets, sessions, start, end, variant='four_week', slip_bps=10):
    capital = cash = 1000000.0
    slip = slip_bps/10000
    prepared = {s:signals(b,variant) for s,b in datasets.items()}
    maps = {s:{b['date']:b for b in rows} for s,rows in datasets.items()}
    days = [d for d in sessions if start <= d <= end]
    positions, trades, curve = {}, [], []
    skipped = 0

    def sell(symbol, day, raw, reason):
        nonlocal cash
        p=positions.pop(symbol)
        fill=raw*(1-slip)
        fees=equity_charges(fill,p['quantity'],'sell',day)['total']
        cash += fill*p['quantity']-fees
        trades.append(dict(symbol=symbol,signal_date=p['signal_date'],entry_date=p['entry_date'],exit_date=day,
            entry=p['entry'],exit=fill,quantity=p['quantity'],stop=p['stop'],reason=reason,
            fees=p['fees']+fees,pnl=(fill-p['entry'])*p['quantity']-p['fees']-fees))

    for day in days:
        previous=sessions[sessions.index(day)-1]
        # Scheduled exits and opening gaps precede fresh orders. Intraday proceeds
        # cannot fund this day's opening orders.
        for symbol in list(positions):
            p=positions[symbol]; b=maps[symbol][day]
            if b['open'] <= p['stop']:
                sell(symbol,day,b['open'],'gap_stop')
            elif p['age'] >= 20:
                sell(symbol,day,b['open'],'20_session_exit')
        opening_equity=cash+sum(p['quantity']*maps[s][day]['open'] for s,p in positions.items())
        candidates=[]
        if day != days[-1]:
            for symbol, ss in prepared.items():
                sig=ss.get(previous)
                if symbol not in positions and sig and sig['bullish']:
                    candidates.append((symbol,sig))
        for symbol,sig in sorted(candidates,key=lambda x:(-x[1]['turnover'],x[0])):
            if len(positions)>=5:
                break
            raw=maps[symbol][day]['open']; fill=raw*(1+slip)
            if raw <= sig['high'] or not 0 < sig['low'] < fill:
                skipped+=1; continue
            budget=min(cash,opening_equity/5)
            q=size_order(opening_equity,budget,fill,sig['low']*(1-slip),.5,day)
            if q<1:
                skipped+=1; continue
            fee=equity_charges(fill,q,'buy',day)['total']
            cash-=q*fill+fee
            positions[symbol]=dict(quantity=q,entry=fill,entry_date=day,signal_date=previous,
                fees=fee,stop=sig['low'],age=0)
        for symbol in list(positions):
            p=positions[symbol]; b=maps[symbol][day]
            if b['low'] <= p['stop']:
                sell(symbol,day,min(b['open'],p['stop']),'stop')
            elif day == days[-1]:
                sell(symbol,day,b['close'],'end_of_sample_close')
            else:
                p['age']+=1
        equity=cash+sum(p['quantity']*maps[s][day]['close'] for s,p in positions.items())
        assert cash >= -.00001
        curve.append(dict(date=day,equity=equity,cash=cash,positions=len(positions)))
    peak=capital; dd=0
    for row in curve:
        peak=max(peak,row['equity']); dd=max(dd,(peak-row['equity'])/peak*100)
    pnl=sum(t['pnl'] for t in trades)
    assert abs(cash-capital-pnl)<.001
    gains=sum(max(0,t['pnl']) for t in trades); losses=-sum(min(0,t['pnl']) for t in trades)
    return dict(metrics=dict(return_pct=100*(cash/capital-1),max_daily_close_drawdown_pct=dd,
        trades=len(trades),win_rate_pct=100*sum(t['pnl']>0 for t in trades)/len(trades) if trades else None,
        profit_factor=gains/losses if losses else None,net_pnl=pnl,fees=sum(t['fees'] for t in trades),
        skipped_gap_or_size=skipped),trades=trades,curve=curve)

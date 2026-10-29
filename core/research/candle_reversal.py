"""Reverse a frozen source entry cohort without inspecting source trade outcomes.

Entry events retain only information available when the original trade opened.
Swapped barriers are known then; reversed exits are evaluated anew on candles.
"""
from collections import Counter
from math import isfinite
from statistics import mean

from core.research.candle_rejection import Rules,exit_trigger,size
from core.research.intraday_costs import upstox_cash_fees


def entry_events(source):
    events={}
    for number,trade in enumerate(source['trades']):
        if trade['direction']!='long':
            raise ValueError('This selected source cohort must contain longs only.')
        day,symbol,index=trade['date'],trade['symbol'],trade['entry_index']
        by_index=events.setdefault(day,{}).setdefault(symbol,{})
        if index in by_index:
            raise ValueError('Duplicate source entry event.')
        # Deliberately exclude source exit, quantity, P&L and win/loss labels.
        by_index[index]=dict(source_trade_index=number,source_stop=trade['stop'],source_target=trade['target'],
                             source_entry_timestamp=trade['entry_timestamp'],signal_timestamp=trade['signal_timestamp'])
    return events


def simulate(inputs,source,mode,slippage_bps,rules=Rules(),fee_multiplier=1):
    if mode not in ('follow','reverse') or not 0<=slippage_bps<10000 or fee_multiplier<0:
        raise ValueError('Invalid reversal assumptions.')
    sign=1 if mode=='follow' else -1
    side_in,side_out=('buy','sell') if sign==1 else ('sell','buy')
    events=entry_events(source)
    equity=peak=rules.capital
    max_dd=0
    trades,curve,diagnostics,decisions=[],[],Counter(),[]
    slip=slippage_bps/10000
    for day,selected in sorted(inputs['plan'].items()):
        capital,used_budget=equity,0
        positions,counts={},Counter()
        bars={c['symbol']:inputs['sessions'][c['symbol']][day] for c in selected}
        for j in range(75):
            for symbol,session in bars.items():
                event=events.get(day,{}).get(symbol,{}).get(j)
                if event is None:
                    continue
                if session[j]['timestamp']!=event['source_entry_timestamp']:
                    raise ValueError('Source entry timestamp does not match frozen candles.')
                diagnostics['source_entries_attempted']+=1
                decision=dict(event,symbol=symbol,date=day,entry_index=j)
                if symbol in positions or counts[symbol]>=rules.max_trades_per_stock or len(positions)>=rules.max_positions:
                    diagnostics['position_or_trade_cap']+=1
                    decisions.append(dict(decision,status='position_or_trade_cap'))
                    continue
                raw=session[j]['open']
                entry=raw*(1+sign*slip)
                stop=event['source_stop'] if mode=='follow' else event['source_target']
                target=event['source_target'] if mode=='follow' else event['source_stop']
                if sign*(entry-stop)<=0 or sign*(target-entry)<=0:
                    diagnostics['invalid_barriers_after_slippage']+=1
                    decisions.append(dict(decision,status='invalid_barriers_after_slippage'))
                    continue
                qty=size(entry,stop,capital,capital-used_budget,sign,day,slip,rules,fee_multiplier)
                if not qty:
                    diagnostics['risk_or_capital_rejected']+=1
                    decisions.append(dict(decision,status='risk_or_capital_rejected'))
                    continue
                fee=upstox_cash_fees(entry,qty,side_in,day,fee_multiplier)
                position=dict(event,entry=entry,raw_entry=raw,stop=stop,target=target,quantity=qty,
                              entry_fee=fee,entry_index=j,entry_timestamp=session[j]['timestamp'],entry_time=session[j]['time'],
                              initial_risk=sign*(entry-stop)*qty,planned_reward_r=sign*(target-entry)/(sign*(entry-stop)))
                used_budget+=entry*qty+fee
                positions[symbol]=position
                counts[symbol]+=1
                decisions.append(dict(decision,status='entered',quantity=qty))
            for symbol in list(positions):
                p,bar=positions[symbol],bars[symbol][j]
                trigger=exit_trigger(p,bar,j,sign,rules)
                if trigger is None:
                    continue
                raw,reason,ambiguous=trigger
                fill=raw*(1-sign*slip)
                exit_fee=upstox_cash_fees(fill,p['quantity'],side_out,day,fee_multiplier)
                fees=p['entry_fee']+exit_fee
                pnl=sign*(fill-p['entry'])*p['quantity']-fees
                equity+=pnl
                trades.append(dict(p,symbol=symbol,date=day,direction='long' if sign==1 else 'short',
                                   exit=fill,raw_exit=raw,exit_timestamp=bar['timestamp'],exit_time=bar['time'],reason=reason,
                                   fees=fees,pnl=pnl,r=pnl/p['initial_risk'],ambiguous=ambiguous,
                                   slippage=(abs(p['entry']-p['raw_entry'])+abs(fill-raw))*p['quantity']))
                diagnostics['ambiguous_stop_target']+=ambiguous
                del positions[symbol]
            marked=equity+sum(sign*(bars[s][j]['close']-p['entry'])*p['quantity']-p['entry_fee'] for s,p in positions.items())
            peak=max(peak,marked)
            max_dd=max(max_dd,(peak-marked)/peak*100)
            if used_budget>capital+1e-6:
                raise ValueError('Daily capital exceeded.')
        if positions:
            raise ValueError('Reversal held positions overnight.')
        curve.append(dict(date=day,equity=equity))
        if equity<=0 or not isfinite(equity):
            raise ValueError('Reversal research capital exhausted.')
    wins,losses=[t for t in trades if t['pnl']>0],[t for t in trades if t['pnl']<0]
    months,stocks={},{}
    for t in trades:
        month=t['date'][:7]
        months[month]=months.get(month,0)+t['pnl']
        stocks[t['symbol']]=stocks.get(t['symbol'],0)+t['pnl']
    metrics=dict(initial_capital=rules.capital,final_equity=equity,return_pct=(equity/rules.capital-1)*100,
                 trade_count=len(trades),win_rate_pct=len(wins)/len(trades)*100 if trades else None,
                 profit_factor=sum(t['pnl'] for t in wins)/-sum(t['pnl'] for t in losses) if losses else None,
                 expectancy_r=mean(t['r'] for t in trades) if trades else None,
                 max_observed_close_drawdown_pct=max_dd,fees=sum(t['fees'] for t in trades),slippage=sum(t['slippage'] for t in trades))
    return dict(metrics=metrics,trades=trades,curve=curve,diagnostics=dict(diagnostics),entry_decisions=decisions,
                monthly_pnl=months,stock_pnl=stocks)

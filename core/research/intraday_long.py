"""Prior-day bullish signals with five-minute execution and compulsory same-day sale."""
import math
from core.execution.paper import PaperBrokerAdapter
from core.research import corporate_actions, intraday_data


def entry_plan(datasets,cfg,entry_warmup=0):
    from strategies.swing_patterns.patterns.signals import matches
    from bisect import bisect_left,bisect_right
    dates = {s:{b['date']:i for i,b in enumerate(rows)} for s,rows in datasets.items()}
    statistics, cache, plan = {}, {}, {}
    def context(symbol,day):
        if symbol not in cache:
            cache[symbol] = corporate_actions.adjusted_bars(datasets[symbol],day)
        return cache[symbol]
    for day in sorted({b['date'] for rows in datasets.values() for b in rows if str(cfg.start)<=b['date']<=str(cfg.end)}):
        candidates = []
        for symbol,rows in datasets.items():
            i = dates[symbol].get(day)
            if i is None or i-1<max(0,entry_warmup):
                continue
            signal_day = rows[i-1]['date']
            cache.clear()
            if not matches(context(symbol,signal_day),i-1,cfg):
                continue
            if signal_day not in statistics:
                returns,eligible,above = {},0,0
                for s in datasets:
                    j = dates[s].get(signal_day)
                    if j is None:
                        continue
                    adjusted = context(s,signal_day)
                    if j>=126:
                        returns[s] = adjusted[j]['close']/adjusted[j-126]['close']-1
                    if j>=199:
                        eligible += 1
                        above += adjusted[j]['close']>sum(b['close'] for b in adjusted[j-199:j+1])/200
                values = sorted(returns.values())
                ranks = {s:((bisect_left(values,r)+bisect_right(values,r)-1)/2/max(len(values)-1,1)*100,r) for s,r in returns.items()}
                gate = not cfg.skip_weak_markets or (eligible>0 and eligible/len(datasets)*100>=cfg.market_min_coverage_pct and above/eligible*100>=cfg.market_breadth_pct)
                statistics[signal_day] = ranks,gate
            ranks,gate = statistics[signal_day]
            rank = ranks.get(symbol,(-1,-1))
            if gate and (cfg.min_rs_rating<=0 or rank[0]>=cfg.min_rs_rating):
                candidates.append(dict(symbol=symbol,signal_date=signal_day,signal_index=i-1,daily_index=i,rank=rank))
        if candidates:
            plan[day] = sorted(candidates,key=lambda x:(-x['rank'][0],-x['rank'][1],x['symbol']) if cfg.candidate_rank=='rs_126' else (x['symbol'],))
    return plan


def simulate(datasets,cfg,sessions,plan=None,entry_warmup=0):
    plan = entry_plan(datasets,cfg,entry_warmup) if plan is None else plan
    broker = PaperBrokerAdapter(cfg)
    slip,buy_fee,sell_fee = cfg.slippage_bps/10000,cfg.buy_cost_bps/10000,cfg.sell_cost_bps/10000
    cash,peak,max_dd = cfg.capital,cfg.capital,0
    trades,orders,curve = [],[],[]
    total_fees = total_slippage = skipped = ambiguous = 0
    excluded_sessions = []
    for day in sorted({b['date'] for rows in datasets.values() for b in rows if str(cfg.start)<=b['date']<=str(cfg.end)}):
        equity_at_open, reserved, selected = cash,0,[]
        for candidate in plan.get(day,[]):
            symbol = candidate['symbol']
            if day in intraday_data.SPECIAL_SESSIONS:
                excluded_sessions.append(dict(symbol=symbol,date=day,reason='Verified special session cannot execute the regular 09:15 entry and cutoff',
                                              evidence=intraday_data.SPECIAL_SESSIONS[day]))
                skipped += 1
                continue
            if len(selected)>=cfg.max_positions:
                skipped += 1
                continue
            raw = sessions.get(symbol,{}).get(day)
            if not raw:
                raise ValueError(f'Missing five-minute input for {symbol} on {day}.')
            if raw[0]['time'] >= cfg.square_off_time:
                excluded_sessions.append(dict(symbol=symbol,date=day,reason='Session opens at or after the sale cutoff; no entry allowed'))
                skipped += 1
                continue
            try:
                bars = intraday_data.trading_bars(raw,cfg.square_off_time)
            except ValueError as exc:
                raise ValueError(f'{symbol} on {day}: {exc}') from None
            daily_open = datasets[symbol][candidate['daily_index']]['open']
            if abs(bars[0]['open']/daily_open-1)>=.35:
                raise ValueError(f'Intraday/daily price units disagree for {symbol} on {day}; review source adjustment before testing.')
            fill = bars[0]['open']*(1+slip)
            distance = fill*cfg.stop_pct/100
            stop = fill-distance
            unit_risk = distance+fill*buy_fee+stop*(sell_fee+slip)
            qty = max(0,min(math.floor(max(0,equity_at_open)*cfg.risk_pct/100/unit_risk),math.floor(max(0,cash-reserved)/(fill*(1+buy_fee)))))
            if qty<1:
                skipped += 1
                continue
            entry = broker.fill(bars[0]['open'],qty,'buy')
            reserved += qty*fill+entry['fees']
            selected.append((candidate,bars,qty,entry,stop,distance))
        # Slots and capital are allocated together at the open; later exits cannot finance more open-time entries.
        for candidate,bars,qty,entry,stop,distance in selected:
            symbol = candidate['symbol']
            fill,best = entry['price'],entry['price']
            target_pct = {'take_8':8,'take_15':15,'take_25':25}.get(cfg.winner_exit)
            target = fill*(1+target_pct/100) if target_pct is not None else None
            trace,exit_bar,exit_price,reason = [],bars[-1],bars[-1]['open'],'Mandatory intraday square-off'
            for b in bars:
                trace.append(dict(date=day,timestamp=b['timestamp'],time=b['time'],stop=stop))
                if b['time']==cfg.square_off_time:
                    break  # Sell at this bar's open; never use its future high/low/close.
                if b['open']<=stop:
                    exit_bar,exit_price,reason = b,b['open'],'Intraday gap through stop'
                    break
                if target is not None and b['open']>=target:
                    exit_bar,exit_price,reason = b,b['open'],f'Intraday take profit {target_pct}%'
                    break
                stop_hit = b['low']<=stop
                target_hit = target is not None and b['high']>=target
                if stop_hit:
                    ambiguous += bool(target_hit)
                    exit_bar,exit_price,reason = b,stop,'Intraday stop loss / trailing stop'
                    break
                if target_hit:
                    exit_bar,exit_price,reason = b,target,f'Intraday take profit {target_pct}%'
                    break
                best = max(best,b['close'])
                if b['close']>=fill*(1+cfg.stop_pct/100*cfg.breakeven_r):
                    breakeven = fill*(1+buy_fee)/(1-sell_fee)/(1-slip)
                    if target is None:
                        length = 150 if cfg.winner_exit=='trail_30w' else 50
                        rows = corporate_actions.adjusted_bars(datasets[symbol],day)
                        idx = candidate['signal_index']
                        trailing = sum(x['close'] for x in rows[idx-length+1:idx+1])/length if idx+1>=length else best*(1-cfg.trail_pct/100)
                    else:
                        trailing = best*(1-cfg.trail_pct/100)
                    stop = max(stop,breakeven,trailing)
            cover = broker.fill(exit_price,qty,'sell')
            fees = entry['fees']+cover['fees']
            pnl = qty*(cover['price']-fill)-fees
            cash += pnl
            total_fees += fees
            total_slippage += entry['slippage']+cover['slippage']
            trades.append(dict(symbol=symbol,direction='long',execution_horizon='intraday',signal_date=candidate['signal_date'],
                               entry_date=day,exit_date=day,entry_time=bars[0]['time'],exit_time=exit_bar['time'],
                               entry_timestamp=bars[0]['timestamp'],exit_timestamp=exit_bar['timestamp'],
                               exit_time_precision='five-minute candle' if reason!='Mandatory intraday square-off' else 'cutoff bar open',
                               entry=fill,exit=cover['price'],quantity=qty,exit_quantity=qty,pnl=pnl,r=pnl/(qty*distance),
                               reason=reason,fees=fees,borrow_cost=0,stop_trace=trace))
            orders.extend([dict(symbol=symbol,date=day,time=bars[0]['time'],side='buy',quantity=qty,price=fill,fees=entry['fees'],status='FILLED'),
                           dict(symbol=symbol,date=day,time=exit_bar['time'],side='sell',quantity=qty,price=cover['price'],fees=cover['fees'],status='FILLED')])
        peak = max(peak,cash)
        max_dd = max(max_dd,(peak-cash)/peak*100)
        curve.append(dict(date=day,equity=round(cash,2),drawdown_pct=round((peak-cash)/peak*100,4)))
    if not curve:
        raise ValueError('No daily sessions in the test interval.')
    wins,losses = [t for t in trades if t['pnl']>0],[t for t in trades if t['pnl']<0]
    return dict(trades=trades,curve=curve,corporate_actions=[],excluded_sessions=excluded_sessions,state=dict(cash=cash,positions={},orders=orders),
                metrics=dict(initial_capital=cfg.capital,final_equity=curve[-1]['equity'],return_pct=(cash/cfg.capital-1)*100,
                             max_drawdown_pct=max_dd,trade_count=len(trades),win_rate=len(wins)/len(trades)*100 if trades else None,
                             expectancy_r=sum(t['r'] for t in trades)/len(trades) if trades else None,
                             profit_factor=sum(t['pnl'] for t in wins)/-sum(t['pnl'] for t in losses) if losses else None,
                             modeled_fees=total_fees,modeled_slippage=total_slippage,modeled_borrow_costs=0,
                             skipped_entries=skipped,ambiguous_stop_target_bars=ambiguous,overnight_positions=0,
                             drawdown_basis='session-end equity'))

"""Explain shorts with frozen signal context and the engine's saved stop ledger."""
from bisect import bisect_left, bisect_right
from types import SimpleNamespace
from core.research import bearish, corporate_actions
from core.research.config import TradingConfig


def explain_trade(result, datasets, trade, bars, first, last):
    cfg = SimpleNamespace(**{**TradingConfig().model_dump(), **bearish.BearishConfig().model_dump(), **result['config']})
    idx = first if cfg.entry_mode == 'close' else first-1
    day = bars[idx]['date']
    signal_bars = corporate_actions.adjusted_bars(bars, day)
    signal = signal_bars[idx]
    lookback = bearish.lookback_sessions(cfg)
    prior = signal_bars[idx-lookback:idx]
    floor = min(x['low'] for x in prior)
    enriched = [dict(b, chart_values={}) for b in bars]
    checks, series = [], []

    def check(label, actual, required, passed):
        checks.append(dict(label=label, actual=actual, required=required, passed=passed))

    for length in sorted({cfg.sma_days, 50, 200} | ({150} if cfg.winner_exit=='trail_30w' else set())):
        key = f'sma_{length}'
        series.append(dict(id=key, label=f'SMA {length}', color={50:'#d18b26',200:'#5879c6'}.get(length,'#9766c5')))
        total = 0
        for i, b in enumerate(bars):
            total += b['close']
            if i >= length:
                total -= bars[i-length]['close']
            if i+1 >= length:
                enriched[i]['chart_values'][key] = total/length
    levels = [('trigger','Broken support',floor,'#2596a2'),
              ('initial_stop','Initial short stop',trade['entry']*(1+cfg.stop_pct/100),'#bd5869'),
              ('activation','Short breakeven activation',trade['entry']*(1-cfg.stop_pct/100*cfg.breakeven_r),'#ac8c49')]
    target = {'take_8':8,'take_15':15,'take_25':25}.get(cfg.winner_exit)
    if target is not None:
        levels.append(('target',f'{target}% decline profit target',trade['entry']*(1-target/100),'#4b9b64'))
    for key, label, price, color in levels:
        series.append(dict(id=key,label=label,color=color))
        for i in range(max(0,idx-lookback) if key=='trigger' else first,last+1):
            enriched[i]['chart_values'][key] = price
    trace = {x['date']:x['stop'] for x in trade.get('stop_trace',[])}
    if trace:
        series.append(dict(id='protective_stop',label='Recorded active short stop',color='#d34848'))
        for b in enriched:
            if b['date'] in trace:
                b['chart_values']['protective_stop'] = trace[b['date']]
    sma = sum(x['close'] for x in signal_bars[idx-cfg.sma_days+1:idx+1])/cfg.sma_days
    check('Close below broken support',signal['close'],f'< {floor:.2f}',signal['close']<floor)
    check('Price below trend average',signal['close'],f'< SMA {cfg.sma_days}: {sma:.2f}',signal['close']<sma)
    preceding = signal_bars[idx-50:idx]
    volume = sum(x['volume'] for x in preceding)/50
    turnover = sum(x['volume']*x['close'] for x in preceding)/50
    check('Breakdown volume / 50-session mean',signal['volume']/volume if volume else None,
          f'≥ {cfg.volume_multiple:g}×',volume>0 and signal['volume']>=volume*cfg.volume_multiple)
    check('Average daily turnover (₹)',turnover,f'≥ {cfg.min_turnover:,.0f}',turnover>=cfg.min_turnover)
    if cfg.require_falling_long_trend:
        long = sum(x['close'] for x in signal_bars[idx-199:idx+1])/200
        old = sum(x['close'] for x in signal_bars[idx-219:idx-19])/200
        check('Price below SMA 200',signal['close'],f'< {long:.2f}',signal['close']<long)
        check('SMA 200 falling over 20 sessions',long,f'< {old:.2f}',long<old)
    check('Bearish pattern qualification',cfg.pattern,'Completed-session predicate passes',bearish.evaluate(signal_bars,cfg,idx) is not None)
    returns, eligible, above = {}, 0, 0
    for symbol, raw in datasets.items():
        j = next((i for i,b in enumerate(raw) if b['date']==day),None)
        if j is None:
            continue
        rows = corporate_actions.adjusted_bars(raw,day)
        if j>=126:
            returns[symbol] = rows[j]['close']/rows[j-126]['close']-1
        if j>=199:
            eligible += 1
            above += rows[j]['close']>sum(x['close'] for x in rows[j-199:j+1])/200
    if trade['symbol'] in returns:
        values = sorted(returns.values())
        r = returns[trade['symbol']]
        rank = (bisect_left(values,r)+bisect_right(values,r)-1)/2/max(len(values)-1,1)*100
        check('126-session RS percentile',rank,f'≤ {cfg.max_rs_rating:g}',rank<=cfg.max_rs_rating)
    if cfg.require_weak_market:
        coverage = eligible/len(datasets)*100
        breadth = above/eligible*100 if eligible else None
        check('Breadth history coverage (%)',coverage,f'≥ {cfg.market_min_coverage_pct:g}',coverage>=cfg.market_min_coverage_pct and eligible>0)
        check('Weak-market breadth (%)',breadth,f'≤ {cfg.max_market_breadth_pct:g}',breadth is not None and breadth<=cfg.max_market_breadth_pct)
    return dict(bars=enriched, series=series, signal=dict(date=day,timestamp=signal['timestamp'],price=signal['close']),
                checks=checks, notices=['Short entry is SELL; exit is BUY to cover. Active stops come from the saved engine ledger.',
                                       'Borrow availability, recalls and dividends owed are not modeled. See the saved run assumptions.',
                                       'Moving-average chart lines use saved candle units; signal checks apply verified corporate actions as of the signal date.'],
                pattern=cfg.pattern, entry_mode=cfg.entry_mode, candidate_rank=cfg.candidate_rank, winner_exit=cfg.winner_exit)

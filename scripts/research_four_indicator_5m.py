"""Frozen, full-window five-minute adaptation of the saved four-indicator rules."""
import argparse
from collections import Counter
from datetime import datetime
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


def export(root):
    from core.research import store, identity, market_history, corporate_actions, intraday_data as intr
    from core.research.four_indicator_swing import stored_parameters
    root.mkdir(parents=True, exist_ok=True)
    with identity.scope({'username': 'manoj'}):
        reference = store.read('runs/d30a9ffd6c7e')
        config = dict(reference['config'], start='2025-10-29', end='2026-10-28',
                      name='All four indicators · 5-minute · last year')
        config.update(stored_parameters(config))
        universe = store.read('universes/niftytotalmarket')
        calendar = store.read('bars/NIFTY50')['bars']
        days = [b['date'] for b in calendar if config['start'] <= b['date'] <= config['end']]
        warmup = [b['date'] for b in calendar if b['date'] < config['start']][-2:]
        required = warmup + days
        evidence = market_history.evidence(snapshot=True)
        manifest = dict(config=config, source_run_id=reference['id'], captured_at=store.now(),
                        universe=universe, days=days, warmup_days=warmup, stocks=[], excluded={})
        from core.research.four_indicator_swing import read_many
        for ordinal, item in enumerate(universe['instruments']):
            symbol = item['symbol']
            try:
                daily, details = market_history.prepare(item, store.read('bars/'+item['isin'], {}), reference=evidence)
                if any(config['start'] <= a['ex_date'] <= config['end'] for a in corporate_actions.actions(daily)):
                    raise ValueError('Known split/bonus in window; share rebasing is unsupported.')
                by_day = {b['date']: b for b in daily}
                if not daily or any(d not in by_day for d in required):
                    raise ValueError('Missing daily context or full-window listing history.')
                dates = sorted(by_day)
                previous = {d: by_day[dates[dates.index(d)-1]] for d in required if dates.index(d) > 0}
                if len(previous) != len(required):
                    raise ValueError('Missing previous-day pivot context.')
                keys = [intr.cache_key(item['isin'], d, 5) for d in required]
                records = read_many(keys)
                packed = []
                bad = []
                for day, key in zip(required, keys):
                    if key not in records:
                        bad.append(day)
                        continue
                    try:
                        bars = intr.trading_bars(intr.cached_bars(records[key], day, 5), '15:25', 5)
                    except ValueError:
                        bad.append(day)
                        continue
                    packed.extend([[b[k] for k in ('timestamp','open','high','low','close','volume')] for b in bars])
                if bad:
                    raise ValueError(f'{len(bad)} missing/incomplete five-minute sessions; first: '+','.join(bad[:5]))
                payload = dict(symbol=symbol, isin=item['isin'], rows=packed, previous=previous, daily_evidence=details)
                raw = json.dumps(payload, separators=(',', ':')).encode()
                filename = item['isin']+'.json.gz'
                (root/filename).write_bytes(gzip.compress(raw, compresslevel=1))
                manifest['stocks'].append(dict(symbol=symbol, file=filename, sha256=hashlib.sha256(raw).hexdigest(), bars=len(packed)))
            except (ValueError, KeyError) as exc:
                manifest['excluded'][symbol] = str(exc)
            if ordinal % 10 == 0 or ordinal+1 == len(universe['instruments']):
                save(root/'manifest.json', manifest)
                print(f"{ordinal+1}/{len(universe['instruments'])}: {len(manifest['stocks'])} eligible; {len(manifest['excluded'])} excluded", flush=True)
        save(root/'manifest.json', manifest)
        print('EXPORT COMPLETE', flush=True)


def fast_values(rows, multiplier):
    """Same Wilder recurrences as shared rules; vectorized Bollinger windows."""
    import numpy as np
    from statistics import mean
    close = rows[:, 4]
    bands = np.full(len(rows), np.nan)
    windows = np.lib.stride_tricks.sliding_window_view(close, 20)
    bands[19:] = windows.mean(axis=1) + multiplier*windows.std(axis=1)
    rsi = np.full(len(rows), np.nan)
    trend_up = np.zeros(len(rows), dtype=bool)
    st = np.full(len(rows), np.nan)
    atr = gain = loss = upper = lower = trend = None
    ranges, gains, losses = [], [], []
    for i, (_, opening, high, low, closing, volume) in enumerate(rows):
        prior = close[i-1] if i else closing
        tr = max(high-low, abs(high-prior), abs(low-prior))
        if i <= 9: ranges.append(float(tr))
        if 0 < i <= 14:
            gains.append(float(max(closing-prior, 0)))
            losses.append(float(max(prior-closing, 0)))
        if i == 9: atr = mean(ranges)
        elif i > 9: atr = (atr*9+tr)/10
        if i == 14: gain, loss = mean(gains), mean(losses)
        elif i > 14:
            gain = (gain*13+max(closing-prior, 0))/14
            loss = (loss*13+max(prior-closing, 0))/14
        if gain is not None:
            rsi[i] = 50 if gain == loss == 0 else 100 if loss == 0 else 100-100/(1+gain/loss)
        if atr is not None:
            basic_upper, basic_lower = (high+low)/2+3*atr, (high+low)/2-3*atr
            upper = basic_upper if upper is None or basic_upper < upper or prior > upper else upper
            lower = basic_lower if lower is None or basic_lower > lower or prior < lower else lower
            if trend is None: trend = -1
            elif trend == -1 and closing > upper: trend = 1
            elif trend == 1 and closing < lower: trend = -1
            st[i], trend_up[i] = (lower if trend == 1 else upper), trend == 1
    return rsi, st, trend_up, bands


def simulate(openings, closes, entries, exits, ranks, stamps, symbols, cfg):
    import numpy as np
    from core.execution.upstox import equity_charges, size_order
    from datetime import timezone, timedelta
    def session(stamp):return datetime.fromtimestamp(int(stamp)/1000,timezone(timedelta(hours=5,minutes=30))).date().isoformat()
    sessions = [session(stamp) for stamp in stamps]
    capital = cash = cfg['capital']
    slip = cfg['slippage_bps']/10000
    positions, trades, curve = {}, [], []
    fees = slippage = 0.
    skipped = 0
    daily_entry_skips = 0
    last_entry_day = {}
    peak = capital
    max_dd = 0.
    def close(s, i, raw, reason):
        nonlocal cash, fees, slippage
        p = positions.pop(s)
        price = raw*(1-slip)
        day=session(stamps[i])
        intraday=session(p['entry_timestamp'])==day
        if intraday:
            actual=equity_charges(p['entry'],p['quantity'],'buy',day,intraday=True)['total']
            correction=actual-p['entry_fee']
            cash-=correction;fees+=correction;p['entry_fee']=actual
        fee = equity_charges(price,p['quantity'],'sell',day,intraday=intraday)['total']
        cash += price*p['quantity']-fee
        fees += fee
        slippage += (raw-price)*p['quantity']
        pnl = (price-p['entry'])*p['quantity']-p['entry_fee']-fee
        trades.append(dict(p, symbol=symbols[s], exit=price,
                           exit_timestamp=int(stamps[i])+(300000 if reason.startswith('End of backtest') else 0),
                           reason=reason, pnl=pnl, fees=p['entry_fee']+fee))
    for i in range(len(stamps)):
        exited = set()
        for s in sorted(positions):
            if exits[i,s]:
                close(s, i, openings[i,s], 'Supertrend reversal · next 5-minute open')
                exited.add(s)
        equity_open = cash+sum(p['quantity']*openings[i,s] for s,p in positions.items())
        budget = equity_open/cfg['max_positions']
        candidates = [int(s) for s in np.flatnonzero(entries[i]) if s not in positions and s not in exited]
        candidates.sort(key=lambda s: (-ranks[i,s], symbols[s]))
        for s in candidates:
            if cfg.get('one_entry_per_day') and last_entry_day.get(s) == sessions[i]:
                daily_entry_skips += 1
                continue
            if len(positions) >= cfg['max_positions']:
                skipped += 1
                continue
            price = openings[i,s]*(1+slip)
            qty = size_order(equity_open,min(budget,cash),price,price,100,session(stamps[i]))
            if qty <= 0:
                skipped += 1
                continue
            fee = equity_charges(price,qty,'buy',session(stamps[i]))['total']
            cash -= price*qty+fee
            fees += fee
            slippage += (price-openings[i,s])*qty
            positions[s] = dict(entry=price, entry_timestamp=int(stamps[i]),
                                signal_timestamp=int(stamps[i-1]) if i else None,
                                quantity=qty, entry_fee=fee)
            last_entry_day[s] = sessions[i]
        if i == len(stamps)-1:
            for s in list(positions): close(s,i,closes[i,s], 'End of backtest · final 5-minute close')
        equity = cash+sum(p['quantity']*closes[i,s] for s,p in positions.items())
        peak = max(peak,equity)
        max_dd = max(max_dd,(peak-equity)/peak*100)
        curve.append(dict(timestamp=int(stamps[i])+300000, equity=equity, cash=cash, positions=len(positions)))
        if cash < -.001: raise ValueError('Negative cash.')
    wins = sum(t['pnl'] for t in trades if t['pnl'] > 0)
    losses = -sum(t['pnl'] for t in trades if t['pnl'] < 0)
    assert abs(cash-capital-sum(t['pnl'] for t in trades)) < .01
    return dict(metrics=dict(final_equity=cash,net_pnl=cash-capital,return_pct=(cash/capital-1)*100,
                    max_drawdown_pct=max_dd,trade_count=len(trades),
                    win_rate=100*sum(t['pnl']>0 for t in trades)/len(trades) if trades else None,
                    profit_factor=wins/losses if losses else None, modeled_fees=fees,modeled_slippage=slippage,
                    skipped_entries=skipped, daily_entry_limit_skips=daily_entry_skips), trades=trades, curve=curve)


def run(root):
    import numpy as np
    from datetime import timezone, timedelta
    manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    cfg = manifest['config']
    stocks = sorted(manifest['stocks'], key=lambda x:x['symbol'])
    # Freeze additional quality exclusions before allocating the portfolio matrix.
    accepted=[]
    for stock in stocks:
        raw=gzip.decompress((root/stock['file']).read_bytes())
        assert hashlib.sha256(raw).hexdigest() == stock['sha256']
        payload=json.loads(raw)
        rows=np.array(payload['rows'])
        reason=None
        if np.any(np.abs(rows[1:,1]/rows[:-1,4]-1)>=.35):
            reason='Unresolved price discontinuity of at least 35% between observed candles.'
        if any(manifest['warmup_days'][0] <= a['ex_date'] <= cfg['end'] for a in payload['daily_evidence'].get('corporate_actions',[])):
            reason='Known split/bonus in indicator warmup or test window.'
        if reason: manifest['excluded'][stock['symbol']]=reason
        else: accepted.append(stock)
    stocks=accepted
    save(root/'eligibility.json',dict(included=[s['symbol'] for s in stocks],excluded=manifest['excluded']))
    if not stocks: raise ValueError('No full-window stocks.')
    n = len(manifest['days'])*75
    shape = (n,len(stocks))
    openings, closes, ranks = [np.empty(shape) for _ in range(3)]
    entries, exits = [np.empty(shape,dtype=bool) for _ in range(2)]
    stamps = None
    for j, stock in enumerate(stocks):
        raw = gzip.decompress((root/stock['file']).read_bytes())
        assert hashlib.sha256(raw).hexdigest() == stock['sha256']
        payload = json.loads(raw)
        rows = np.array(payload['rows'])
        values = fast_values(rows,cfg['bollinger_multiplier'])
        dates = [datetime.fromtimestamp(t/1000,timezone(timedelta(hours=5,minutes=30))).date().isoformat() for t in rows[:,0]]
        r1 = np.array([2*sum(payload['previous'][d][k] for k in ('high','low','close'))/3-payload['previous'][d]['low'] for d in dates])
        rsi, st, up, band = values
        signal = up & (rows[:,4]>st) & (rsi>cfg['rsi_threshold']) & (rows[:,4]>r1) & (rows[:,4]>band)
        offset = len(manifest['warmup_days'])*75
        assert len(rows)-offset == n and dates[offset] == cfg['start'] and dates[-1] == cfg['end']
        current = rows[offset:,0].astype('int64')
        if stamps is None: stamps=current
        else: assert np.array_equal(current,stamps)
        openings[:,j], closes[:,j] = rows[offset:,1], rows[offset:,4]
        # Start in cash. Pre-window candles supply warmup, not pre-window entries.
        entries[:,j] = signal[offset-1:-1]
        entries[0,j] = False
        exits[:,j] = ~up[offset-1:-1]
        ranks[:,j] = rows[offset-1:-1,4]*rows[offset-1:-1,5]
        if j%20 == 0: print(f'Indicators {j+1}/{len(stocks)}',flush=True)
    result = simulate(openings,closes,entries,exits,ranks,stamps,[s['symbol'] for s in stocks],cfg)
    result.update(config=cfg,timeframe_minutes=5,completed_at=datetime.now(timezone.utc).isoformat(),
                  runtime=dict(python=sys.version,numpy=np.__version__),
                  eligible_symbols=len(stocks),excluded_symbols=len(manifest['excluded']),
                  exclusions=manifest['excluded'],sessions=len(manifest['days']),
                  input_manifest_sha256=hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest(),
                  assumptions=['Long cash equities; current universe membership has survivorship bias.',
                    'Five-minute Supertrend(10,3), RSI(14)>65, close above prior daily R1 and Bollinger(20,2.5).',
                    'Completed signals fill at next observed five-minute open; overnight positions carry.',
                    'Start in cash; first test bar supplies signals. No target, holding limit or additional filter.',
                    'Equal equity slots; signals rank by preceding candle turnover; no leverage.',
                    'Upstox Plus fees and 10 bps slippage per side.',
                    'Only full-window complete regular sessions, two warmup sessions and daily pivot context admitted.',
                    'Known in-window splits/bonuses excluded; dividends not reconstructed.',
                    'Unresolved opening jumps of at least 35% versus the previous observed candle are excluded.',
                    'Five-minute close equity drawdown; no bid/ask, participation or intrabar execution validation.'])
    zone=timezone(timedelta(hours=5,minutes=30))
    for trade in result['trades']:
        for key in ('entry','exit','signal'):
            stamp=trade.get(key+'_timestamp')
            trade[key+'_datetime']=datetime.fromtimestamp(stamp/1000,zone).isoformat() if stamp is not None else None
    source_root=Path(__file__).resolve().parents[1]
    result['source_hashes']={name:hashlib.sha256((source_root/name).read_bytes()).hexdigest() for name in
        ('scripts/research_four_indicator_5m.py','core/strategies/four_indicator.py')}
    save(root/'results.json',result)
    import csv
    with (root/'trades.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=list(result['trades'][0]) if result['trades'] else ['symbol'])
        writer.writeheader();writer.writerows(result['trades'])
    print(json.dumps({k:result[k] for k in ('metrics','eligible_symbols','excluded_symbols','sessions')}),flush=True)
    report(root,result)
    return result


def report(root, result):
    from html import escape
    from datetime import timezone,timedelta
    zone=timezone(timedelta(hours=5,minutes=30))
    monthly={}
    capital=result['config']['capital']
    previous=capital
    for row in result['curve']:
        month=datetime.fromtimestamp(row['timestamp']/1000,zone).strftime('%Y-%m')
        monthly[month]=row['equity']
    months=[]
    for month,equity in monthly.items():
        months.append(dict(month=month,net_pnl=equity-previous,return_pct=(equity/previous-1)*100,ending_equity=equity))
        previous=equity
    save(root/'monthly.json',months)
    def table(headers,rows):
        return '<table><tr>'+''.join('<th>'+escape(h)+'</th>' for h in headers)+'</tr>'+''.join('<tr>'+''.join('<td>'+escape(f'{v:,.2f}' if isinstance(v,float) else str(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</table>'
    metrics=result['metrics']
    points=result['curve']
    lo=min(capital,min(p['equity'] for p in points));hi=max(capital,max(p['equity'] for p in points))
    poly=' '.join(f'{30+940*i/max(1,len(points)-1):.1f},{270-230*(p["equity"]-lo)/max(1,hi-lo):.1f}' for i,p in enumerate(points))
    svg=f'<svg viewBox="0 0 1000 310" role="img" aria-label="Equity curve"><text x="30" y="20">Equity INR {lo:,.0f}–{hi:,.0f}</text><polyline fill="none" stroke="#247f70" stroke-width="2" points="{poly}"/><text x="30" y="305">29 Oct 2025</text><text x="860" y="305">28 Oct 2026</text></svg>'
    html='<!doctype html><meta charset="utf-8"><title>All four indicators · 5-minute · one year</title><style>body{font:16px system-ui;max-width:1100px;margin:40px auto;padding:0 20px;color:#192837}table{border-collapse:collapse;margin:20px 0;width:100%}td,th{padding:9px 12px;border:1px solid #dce1e5;text-align:right}td:first-child,th:first-child{text-align:left}th{background:#eef4f5}li{margin:9px 0}svg{width:100%;background:#f4f8f7;border-radius:12px}</style>'
    html+='<h1>All four indicators · 5-minute candles</h1><p>29 October 2025–28 October 2026 · 247 observed sessions · INR 1,000,000 capital · 10 positions maximum.</p>'
    html+=f'<p>{result["eligible_symbols"]} stocks included; {result["excluded_symbols"]} excluded by full-window coverage and corporate-action checks. Research simulation with frozen cached candles.</p>'
    html+=table(['Metric','Result'],[(k.replace('_',' '),v) for k,v in metrics.items()])+svg
    html+='<h2>Monthly marked equity</h2><p>October 2025 and October 2026 are partial months. Capital carries continuously across months.</p>'
    html+=table(['Month','Net P&L (INR)','Return (%)','Ending equity (INR)'],[list(m.values()) for m in months])
    html+='<h2>Rules and assumptions</h2><ul>'+''.join('<li>'+escape(a)+'</li>' for a in result['assumptions'])+'</ul>'
    html+='<p><a href="results.json">Full results</a> · <a href="trades.csv">Trade ledger</a> · <a href="manifest.json">Input manifest</a> · <a href="eligibility.json">Stock exclusions</a></p>'
    (root/'report.html').write_text(html,encoding='utf-8')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['export','run'])
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    (export if args.mode=='export' else run)(args.output)

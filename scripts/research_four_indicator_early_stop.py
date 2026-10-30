"""Research-only fixed protective stops on frozen five-minute four-rule data.

The independent replay is copied from the shared five-minute engine and verified
against it with stops disabled before any stop comparisons are run.
"""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import csv
import gzip
import hashlib
from html import escape
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.research_four_indicator_5m import fast_values, simulate as reference_simulate, save
from scripts.research_four_indicator_tightening import BLOCKS, validate
from core.strategies.four_indicator_intraday import completed_trend, pullback_signals

ZONE = timezone(timedelta(hours=5, minutes=30))
STOPS = (0, .5, 1, 1.5, 2)


def simulate(openings, closes, entries, exits, ranks, stamps, symbols, cfg, lows=None, stop_pct=0):
    import numpy as np
    if not 0 <= stop_pct < 100: raise ValueError("Invalid stop percentage")
    if stop_pct and lows is None: raise ValueError("Stop execution requires lows")
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
            level = positions[s]['entry']*(1-stop_pct/100)
            if stop_pct and openings[i,s] <= level:
                close(s, i, openings[i,s], 'Early stop gap · observed open')
                exited.add(s)
            elif exits[i,s]:
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
        # Resting stops activate immediately after entry. Intrabar proceeds cannot
        # fund entries at this same bar's already-observed open.
        if stop_pct:
            for s in sorted(positions):
                level = positions[s]['entry']*(1-stop_pct/100)
                if lows[i,s] <= level:
                    close(s, i, min(openings[i,s], level), 'Early stop · intrabar touch')
                    trades[-1]['exit_timestamp'] = int(stamps[i])+300000
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


def diagnostics(result, cfg):
    trades = result['trades']
    returns = [100*t['pnl']/(t['entry']*t['quantity']+t['entry_fee']) for t in trades]
    losing = [r for r in returns if r < 0]
    gross = sum((t['exit']-t['entry'])*t['quantity'] for t in trades)
    blocks = []
    equity = cfg['capital']
    for first, last in BLOCKS:
        points = [p for p in result['curve'] if first <= datetime.fromtimestamp(p['timestamp']/1000, ZONE).date().isoformat() <= last]
        ending = points[-1]['equity']
        blocks.append(dict(start=first, end=last, return_pct=100*(ending/equity-1)))
        equity = ending
    return dict(mean_loss_pct=sum(losing)/len(losing) if losing else None,
                worst_trade_pct=min(returns) if returns else None,
                mean_win_pct=sum(r for r in returns if r > 0)/sum(r > 0 for r in returns) if any(r > 0 for r in returns) else None,
                gross_pnl_after_slippage=gross, exit_reasons=dict(Counter(t['reason'] for t in trades)),
                chronological_blocks=blocks)


def paired_diagnostics(baseline, openings, lows, stamps, symbols, cfg, stop_pct):
    """Keep baseline entries/quantities fixed to isolate the early-exit tradeoff.

    This is a diagnostic ledger, not a feasible alternative portfolio: freed cash
    is ignored and entry quantities remain the baseline's quantities.
    """
    from core.execution.upstox import equity_charges
    slip = cfg['slippage_bps']/10000
    indices = {int(t): i for i, t in enumerate(stamps)}
    columns = {symbol: j for j, symbol in enumerate(symbols)}
    rows = []
    for t in baseline['trades']:
        first = indices[t['entry_timestamp']]
        final = indices[t['exit_timestamp']-(300000 if t['reason'].startswith('End of backtest') else 0)]
        # A Supertrend next-open exit precedes that bar's intrabar low.
        last = final+1 if t['reason'].startswith('End of backtest') else final
        s, level = columns[t['symbol']], t['entry']*(1-stop_pct/100)
        hit = next((i for i in range(first, last) if lows[i,s] <= level), None)
        if hit is None:
            continue
        price = min(openings[hit,s], level)*(1-slip)
        exit_day = datetime.fromtimestamp(int(stamps[hit])/1000, ZONE).date().isoformat()
        entry_day = datetime.fromtimestamp(t['entry_timestamp']/1000, ZONE).date().isoformat()
        fees = sum(equity_charges(p, t['quantity'], side, exit_day if side == 'sell' else entry_day,
                                  intraday=entry_day == exit_day)['total']
                   for p, side in ((t['entry'], 'buy'), (price, 'sell')))
        pnl = (price-t['entry'])*t['quantity']-fees
        rows.append(dict(symbol=t['symbol'], entry_timestamp=t['entry_timestamp'],
                         stop_bar_timestamp=int(stamps[hit]), baseline_pnl=t['pnl'], stop_pnl=pnl,
                         delta_pnl=pnl-t['pnl'], baseline_winner=t['pnl'] > 0))
    return dict(stopped_baseline_trades=len(rows), baseline_winners_cut=sum(r['baseline_winner'] for r in rows),
                improved_trades=sum(r['delta_pnl'] > 0 for r in rows),
                worsened_trades=sum(r['delta_pnl'] < 0 for r in rows),
                fixed_entry_delta_pnl=sum(r['delta_pnl'] for r in rows), trades=rows)


def run(source, output):
    import numpy as np
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((source/'manifest.json').read_text(encoding='utf-8'))
    eligibility = json.loads((source/'eligibility.json').read_text(encoding='utf-8'))
    stocks = sorted([s for s in manifest['stocks'] if s['symbol'] in set(eligibility['included'])], key=lambda s:s['symbol'])
    cfg = {k:v for k,v in manifest['config'].items() if k not in ('buy_cost_bps','sell_cost_bps')}
    cfg.update(slippage_bps=10, fee_model='upstox_plus')
    root = Path(__file__).resolve().parents[1]
    files = ['scripts/research_four_indicator_early_stop.py', 'scripts/research_four_indicator_5m.py',
             'scripts/research_four_indicator_tightening.py', 'core/strategies/four_indicator_intraday.py',
             'core/execution/upstox.py']
    hashes = {f:hashlib.sha256((root/f).read_bytes()).hexdigest() for f in files}
    plan = dict(config=cfg, stop_percentages=STOPS, entry_variants=['original','combined'],
                blocks=BLOCKS, eligible_symbols=len(stocks), source_hashes=hashes,
                input_manifest_sha256=hashlib.sha256((source/'manifest.json').read_bytes()).hexdigest(),
                eligibility_sha256=hashlib.sha256((source/'eligibility.json').read_bytes()).hexdigest(),
                methodology=[
                    'Long cash equities. Same completed five-minute entry signals and next-open Supertrend exits as the reference.',
                    'Fixed protective stop measured below actual entry fill including buy slippage. Active during the entry bar and overnight.',
                    'If open is below stop, sell at that open minus sell slippage; otherwise a low touching stop fills at stop minus slippage.',
                    'Opening exits precede new entries. Intrabar stop proceeds cannot fund entries at the same bar open. No same-bar reentry.',
                    'OHLC stop touches assume executable resting orders; spreads, queue, circuits and market impact are not validated. Stop timestamps mark the bar end; actual touch time is unknown.',
                    'Upstox Plus shared charges and 10 bps slippage per side; delivery fees reserved and corrected on same-day exits.',
                    'Original and combined entries each rerun independent portfolios; combined adds prior researched pullback, completed 15-minute trend and one-entry-per-stock-per-day.',
                    'Fixed-entry diagnostics retain baseline quantities; they isolate sacrificed winners and loss savings but are not portfolio returns.',
                    'All historical blocks already inspected. No untouched validation, no optimized threshold, current-universe survivorship bias, no reconstructed dividends.',
                    'Research only; no trading configuration, database or paper portfolio changes.'
                ])
    plan_path = output/'frozen-plan.json'
    normalized = json.loads(json.dumps(plan))
    if plan_path.exists() and json.loads(plan_path.read_text(encoding='utf-8')) != normalized:
        raise ValueError('Plan changed; use a fresh output directory.')
    save(plan_path, plan)
    offset, n = len(manifest['warmup_days'])*75, len(manifest['days'])*75
    openings, lows, closes, ranks = [np.empty((n,len(stocks))) for _ in range(4)]
    entries = {key:np.empty((n,len(stocks)),dtype=bool) for key in ('original','combined')}
    exits = np.empty((n,len(stocks)),dtype=bool)
    stamps = None
    for j, stock in enumerate(stocks):
        raw = gzip.decompress((source/stock['file']).read_bytes())
        if hashlib.sha256(raw).hexdigest() != stock['sha256']: raise ValueError('Candle checksum mismatch')
        payload = json.loads(raw)
        rows = np.array(payload['rows'])
        current = rows[offset:,0].astype('int64')
        if len(current) != n: raise ValueError('Incomplete sessions')
        if stamps is None: stamps = current
        elif not np.array_equal(stamps,current): raise ValueError('Session clock mismatch')
        dates = [datetime.fromtimestamp(t/1000,ZONE).date().isoformat() for t in rows[:,0]]
        r1 = np.array([2*sum(payload['previous'][d][k] for k in ('high','low','close'))/3-payload['previous'][d]['low'] for d in dates])
        rsi, st, up, band = fast_values(rows,cfg['bollinger_multiplier'])
        base = up & (rows[:,4] > st) & (rsi > cfg['rsi_threshold']) & (rows[:,4] > r1) & (rows[:,4] > band)
        combined = pullback_signals(rows,base,rsi,st,up,r1) & completed_trend(rows,fast_values)
        for key, signal in (('original',base),('combined',combined)):
            entries[key][:,j] = signal[offset-1:-1]
            entries[key][0,j] = False
        openings[:,j], lows[:,j], closes[:,j] = rows[offset:,1], rows[offset:,3], rows[offset:,4]
        exits[:,j] = ~up[offset-1:-1]
        ranks[:,j] = rows[offset-1:-1,4]*rows[offset-1:-1,5]
        if j % 50 == 0: print(f'Indicators {j+1}/{len(stocks)}',flush=True)
    symbols = [s['symbol'] for s in stocks]
    summaries = []
    for key in entries:
        settings = dict(cfg,one_entry_per_day=key == 'combined')
        baseline = reference_simulate(openings,closes,entries[key],exits,ranks,stamps,symbols,settings)
        replay = simulate(openings,closes,entries[key],exits,ranks,stamps,symbols,settings)
        if baseline != replay: raise ValueError('Stop-disabled replay differs from reference')
        saved_key = 'baseline' if key == 'original' else 'combined'
        prior_path = source.parent/'four_indicator_tightening_20261029'/saved_key/'results.json'
        if prior_path.exists():
            prior = json.loads(prior_path.read_text(encoding='utf-8'))
            if baseline['metrics'] != prior['metrics'] or baseline['curve'] != prior['curve']:
                raise ValueError('Baseline differs from saved previous comparison')
        print(key+': exact reference baseline and equity curve verified',flush=True)
        for stop in STOPS:
            result = baseline if stop == 0 else simulate(openings,closes,entries[key],exits,ranks,stamps,symbols,settings,lows,stop)
            for t in result['trades']:
                for field in ('entry','exit','signal'):
                    value = t[field+'_timestamp']
                    t[field+'_datetime'] = datetime.fromtimestamp(value/1000,ZONE).isoformat() if value is not None else None
            result.update(config=settings, stop_pct=stop, entry_variant=key)
            audit = validate(result, cfg['capital'])
            detail = diagnostics(result,cfg)
            pair = paired_diagnostics(baseline,openings,lows,stamps,symbols,cfg,stop) if stop else None
            folder = output/(key+'_'+str(stop).replace('.','p'))
            folder.mkdir(exist_ok=True)
            save(folder/'results.json',result)
            save(folder/'validation.json',audit)
            if pair: save(folder/'fixed-entry-diagnostic.json',pair)
            with (folder/'trades.csv').open('w',newline='',encoding='utf-8') as f:
                writer = csv.DictWriter(f,fieldnames=list(result['trades'][0]) if result['trades'] else ['symbol'])
                writer.writeheader();writer.writerows(result['trades'])
            row = dict(entry_variant=key,stop_pct=stop,**result['metrics'],**detail,
                       fixed_entry_diagnostic={k:v for k,v in pair.items() if k != 'trades'} if pair else None,
                       validation=audit)
            summaries.append(row)
            print(json.dumps(row),flush=True)
    if any(hashlib.sha256((root/f).read_bytes()).hexdigest() != h for f,h in hashes.items()):
        raise ValueError('Research code changed while running')
    save(output/'comparison.json',dict(plan=plan,results=summaries,verification='Exact stop-disabled reference replay; saved baseline metrics/curve when available; per-trade fee and final cash reconciliation'))
    columns = ['entry_variant','stop_pct','return_pct','max_drawdown_pct','trade_count','win_rate','profit_factor',
               'mean_loss_pct','mean_win_pct','worst_trade_pct','modeled_fees','modeled_slippage']
    with (output/'comparison.csv').open('w',newline='',encoding='utf-8') as f:
        writer = csv.DictWriter(f,fieldnames=columns,extrasaction='ignore')
        writer.writeheader();writer.writerows(summaries)
    page = '<!doctype html><meta charset="utf-8"><title>Four-rule early stops</title><style>body{font:16px/1.6 system-ui;max-width:1350px;margin:40px auto;padding:20px;color:#193044}table{border-collapse:collapse;width:100%}td,th{padding:9px;border:1px solid #ddd;text-align:right}th{background:#eaf3f4}td:first-child{text-align:left}</style>'
    page += '<h1>Four-rule indicator: early protective stops</h1><p>29 October 2025–28 October 2026 · '+str(len(stocks))+' stocks · five-minute candles · INR 10 lakh · ten positions · fees and 10 bps slippage per side.</p>'
    page += '<p>0% means the current Supertrend exit with no additional stop. Thresholds are price distances from the entry fill; fees and gaps can make net losses larger. All variants are retrospective research.</p><div style="overflow:auto"><table><tr>'+''.join('<th>'+escape(c)+'</th>' for c in columns)+'</tr>'
    for row in summaries:
        page += '<tr>'+''.join('<td>'+escape(f'{row[c]:,.2f}' if isinstance(row[c],float) else str(row[c]))+'</td>' for c in columns)+'</tr>'
    page += '</table></div><h2>Continuous portfolio block returns</h2><table><tr><th>Entries / stop</th>'+''.join('<th>'+a+'–'+b+'</th>' for a,b in BLOCKS)+'</tr>'
    for row in summaries:
        page += '<tr><td>'+escape(row['entry_variant']+' / '+str(row['stop_pct'])+'%')+'</td>'+''.join('<td>'+f'{b["return_pct"]:.2f}%'+'</td>' for b in row['chronological_blocks'])+'</tr>'
    page += '</table><h2>Fixed baseline entry diagnostic</h2><p>Same baseline entry dates and quantities; no reinvestment of freed cash. INR delta measures stop exits versus the original exit on those entries.</p><table><tr><th>Entries / stop</th><th>Stopped</th><th>Baseline winners cut</th><th>Improved trades</th><th>Worsened trades</th><th>P&amp;L delta INR</th></tr>'
    for row in summaries:
        p = row['fixed_entry_diagnostic']
        if p:
            page += '<tr><td>'+row['entry_variant']+' / '+str(row['stop_pct'])+'%</td>'+''.join('<td>'+f'{p[c]:,.2f}'+'</td>' for c in ('stopped_baseline_trades','baseline_winners_cut','improved_trades','worsened_trades','fixed_entry_delta_pnl'))+'</tr>'
    page += '</table><h2>Methods and limits</h2><ul>'+''.join('<li>'+escape(m)+'</li>' for m in plan['methodology'])+'</ul><p><a href="comparison.json">Full comparison</a> · <a href="comparison.csv">CSV</a> · <a href="frozen-plan.json">Frozen plan</a>. Each variant folder retains its trades, equity curve, fee audit and fixed-entry diagnostic.</p>'
    (output/'report.html').write_text(page,encoding='utf-8')
    return summaries


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,default=Path('artifacts/four_indicator_5m_year_20261029'))
    parser.add_argument('--output',type=Path,default=Path('artifacts/four_indicator_early_stop_20261030'))
    args = parser.parse_args()
    run(args.input,args.output)


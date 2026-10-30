"""One fixed profit-protection hypothesis, using existing verified archives."""
from datetime import date, datetime, timezone
from html import escape
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.research import options_backtest as bt, options_history as history
from core.research.options_extended import DiskPrices, merge_unique
from scripts.analyse_options_risk import PRIMARY, digest, stats
from scripts.research_options_premium_stop import risk


def paired_outcomes(baseline, variant):
    identity=lambda t:(t['key'],t['entry_timestamp'])
    old={identity(t):t for t in baseline['trades']}
    new={identity(t):t for t in variant['trades']}
    pairs=[]
    for key in old.keys() & new.keys():
        b,v=old[key],new[key]
        if v['reason']=='fee_breakeven_completed_minute':
            pairs.append(dict(key=v['key'],entry_timestamp=v['entry_timestamp'],
                baseline_pnl=b['pnl'],protection_pnl=v['pnl'],delta=v['pnl']-b['pnl'],
                exited_earlier=v['exit_timestamp']<b['exit_timestamp']))
    pairs.sort(key=lambda p:p['entry_timestamp'])
    return dict(protection_exits_same_entry=pairs,
        original_winners_cut_short=sum(p['baseline_pnl']>0 and p['delta']<0 and p['exited_earlier'] for p in pairs),
        original_losers_improved=sum(p['baseline_pnl']<0 and p['delta']>0 for p in pairs),
        total_same_entry_protection_delta=sum(p['delta'] for p in pairs),
        new_entries_after_exit_changes=len(new.keys()-old.keys()),
        original_entries_absent_in_variant=len(old.keys()-new.keys()))


def main():
    root=Path('artifacts/options_extended_2026').resolve()
    output=root/'breakeven-protection-v1'
    output.mkdir(exist_ok=True)
    paths=['core/research/options_backtest.py','core/research/options_strategy.py',
        'core/strategies/four_indicator.py','core/research/options_costs.py','core/execution/upstox.py',
        'scripts/research_options_breakeven.py','scripts/research_options_premium_stop.py','scripts/analyse_options_risk.py']
    plan=dict(created_at=datetime.now(timezone.utc).isoformat(),activation_fraction=.2,
        hypothesis='Fee-adjusted breakeven protection after a 20% option premium gain may reduce profit giveback.',
        rule='Activate at completed-minute close >= 1.20 times actual entry fill. Latch activation for this position. On a later completed-minute close with estimated net liquidation proceeds <= entry premium plus entry fee, sell at exact next-minute open minus 10bps.',
        fee_threshold='Estimated liquidation uses that completed close minus 10bps sell slippage and current shared date-dependent sell fees. Entry includes actual buy slippage and fee. A gap at next open can still lose money.',
        precedence='Scheduled exit, then original Supertrend exit, then protection. Original rearm logic and no same-minute reentry.',
        scope='Primary 3-minute fixed INR250 strategy; 10bps each side; no fixed 20% loss stop combined with this rule.',
        missing_data='Missing/zero-volume monitoring or exit minute leaves unresolved exposure and suppresses comparison.',
        interpretation='Exploratory retrospective study; both periods already examined. One activation threshold, no parameter search.',
        source_hashes={p:digest(Path(p)) for p in paths})
    plan_file=output/'experiment-plan.json'
    if plan_file.exists():
        old=json.loads(plan_file.read_text())
        if {k:v for k,v in old.items() if k!='created_at'}!={k:v for k,v in plan.items() if k!='created_at'}:
            raise ValueError('Plan changed; use a new experiment version.')
        plan=old
    else:
        history.save_json(plan_file,plan)
    results=dict(plan=plan,periods={})
    for name,months in [('development',range(4,8)),('comparison',range(8,10))]:
        print(name+': verifying archives and preparing original signals',flush=True)
        original=json.loads((root/f'{name}-results.json').read_text())
        db=root/f'{name}-prices.sqlite3'
        if digest(db)!=original['price_index_sha256']:
            raise ValueError('Price index checksum mismatch')
        for record in original['inputs']:
            if digest(root/record['month']/record['file'])!=record['sha256']:
                raise ValueError('Input manifest checksum mismatch')
        minutes,daily,catalogs={},{},{}
        for month in months:
            directory=root/f'2026-{month:02d}'
            _,m,d=bt.load_underlying(directory)
            merge_unique(minutes,m,'timestamp')
            merge_unique(daily,d,'date')
            manifest=json.loads((directory/'research-manifest.json').read_text())
            for record in manifest['catalogs']:
                values=history.validate_contracts(bt.read_evidence(directory,record),record['expiry'])
                if record['expiry'] in catalogs and {c['instrument_key']:c for c in catalogs[record['expiry']]}!={c['instrument_key']:c for c in values}:
                    raise ValueError('Catalog overlap conflict')
                catalogs[record['expiry']]=values
        audit=bt.prepare_signals(sorted(minutes.values(),key=lambda v:v['timestamp']),sorted(daily.values(),key=lambda v:v['date']),
            start=date.fromisoformat(original['start']),end=date.fromisoformat(original['end']),timeframe=3)
        connection=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)
        try:
            prices=DiskPrices(connection)
            config=dict(timeframe=3,premium_variant='fixed_250',chain_policy='observed_traded',slippage_bps=10)
            baseline=bt.replay(audit,prices,catalogs,sorted(catalogs),bt.ReplayConfig(**config))
            if baseline['trades']!=original['replays'][PRIMARY]['trades']:
                raise ValueError('Baseline does not reproduce saved ledger')
            variant=bt.replay(audit,prices,catalogs,sorted(catalogs),bt.ReplayConfig(**config,breakeven_activation_fraction=.2))
            period=dict(baseline_reproduced=True,price_index_sha256=original['price_index_sha256'],
                input_manifest_hashes=original['inputs'],original_results_sha256=digest(root/f'{name}-results.json'),
                baseline=baseline,protection=variant)
            if all(r['diagnostic_summary'] is not None and not r['skipped_entries'] and not audit['excluded_sessions'] for r in (baseline,variant)):
                period['comparison']={key:dict(**stats(r['trades']),**risk(connection,r),
                    activated_trades=sum('protection_activation_timestamp' in t for t in r['trades']),
                    protection_exits=sum(t['reason']=='fee_breakeven_completed_minute' for t in r['trades']))
                    for key,r in [('baseline',baseline),('protection',variant)]}
                period['paired_outcomes']=paired_outcomes(baseline,variant)
            results['periods'][name]=period
            history.save_json(output/f'{name}-results.json',period)
            print(name+': '+json.dumps(period.get('comparison',dict(errors=variant['errors']))),flush=True)
        finally:
            connection.close()
    if any(digest(Path(p))!=h for p,h in plan['source_hashes'].items()):
        raise ValueError('Source changed during replay')
    history.save_json(output/'results.json',results)
    html='<!doctype html><meta charset="utf-8"><title>Profit-protection experiment</title><style>body{font:16px system-ui;max-width:1100px;margin:40px auto;padding:20px}td,th{padding:10px;border-bottom:1px solid #ddd;text-align:left}table{border-collapse:collapse}</style><h1>20% activation: fee-adjusted breakeven protection</h1><p>'+escape(plan['rule'])+'</p><p>'+escape(plan['interpretation'])+'</p>'
    for name,p in results['periods'].items():
        html+='<h2>'+name.title()+'</h2><p>Original saved trade ledger reproduced exactly.</p>'
        if 'comparison' not in p:
            html+='<p>Unresolved or excluded inputs; no aggregate comparison published.</p>'
            continue
        html+='<table><tr><th>Scenario</th><th>Trades</th><th>Net INR</th><th>Observed close drawdown INR</th><th>Drawdown %</th><th>Without top 2 INR</th><th>Activated / exits</th></tr>'
        for key,v in p['comparison'].items():
            dd=v['observed_minute_close_drawdown']
            html+=f'<tr><td>{key}</td><td>{v["trades"]}</td><td>{v["net_pnl"]:,.2f}</td><td>{dd["rupees"]:,.2f}</td><td>{dd["percent"]:.2f}</td><td>{v["without_top_two"]:,.2f}</td><td>{v["activated_trades"]} / {v["protection_exits"]}</td></tr>'
        paired=p['paired_outcomes']
        html+=f'</table><p>Same-entry original winners cut short: {paired["original_winners_cut_short"]}; original losers improved: {paired["original_losers_improved"]}. New entries following exit changes: {paired["new_entries_after_exit_changes"]}; original entries absent: {paired["original_entries_absent_in_variant"]}.</p>'
        html+='<table><tr><th>Entry IST</th><th>Original INR</th><th>Protected INR</th><th>Difference INR</th></tr>'
        for t in paired['protection_exits_same_entry']:
            instant=datetime.fromtimestamp(t['entry_timestamp']/1000,history.IST)
            html+=f'<tr><td>{instant:%Y-%m-%d %H:%M}</td><td>{t["baseline_pnl"]:,.2f}</td><td>{t["protection_pnl"]:,.2f}</td><td>{t["delta"]:,.2f}</td></tr>'
        html+='</table>'
    html+='<h2>Limits</h2><p>Breakeven is an estimated trigger, not a guaranteed fill or zero-loss outcome. Unknown candidate prices and absent bid/ask evidence still prevent validated returns. Minute-close drawdown omits intraminute extremes. Full replay includes later entries following earlier exits. The fixed 20% loss stop from the previous experiment is not combined here. Original artifacts remain unchanged.</p><p><a href="results.json">Full ledgers and provenance</a> · <a href="experiment-plan.json">Recorded hypothesis</a></p>'
    (output/'report.html').write_text(html,encoding='utf-8')


if __name__=='__main__':
    main()

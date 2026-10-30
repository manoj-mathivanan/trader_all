"""Single predeclared premium-loss stop experiment on existing archives."""
from datetime import date, datetime, timezone
from html import escape
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.research import options_backtest as bt, options_history as history
from core.research.options_extended import DiskPrices, merge_unique
from scripts.analyse_options_risk import PRIMARY, digest, stats, trade_marks, drawdown


def risk(connection,replay):
    cash=100000.
    equity=[cash]
    missing=0
    for t in replay['trades']:
        rows=connection.execute('SELECT timestamp,close,volume FROM prices WHERE instrument=? AND timestamp>=? AND timestamp<? ORDER BY timestamp',
            (t['key'],t['entry_timestamp'],t['exit_timestamp'])).fetchall()
        metrics,marks=trade_marks(t,rows,10)
        missing+=metrics['missing_or_zero_volume_minutes']
        equity.extend(cash+p for _,p in marks)
        cash+=t['pnl']
        equity.append(cash)
    return dict(observed_minute_close_drawdown=drawdown(equity),missing_marks=missing)


def main():
    root=Path('artifacts/options_extended_2026').resolve()
    output=root/'premium-stop-v1'
    output.mkdir(exist_ok=True)
    plan=dict(created_at=datetime.now(timezone.utc).isoformat(),
        hypothesis='A fixed premium-loss stop may reduce large losing trades and drawdown.',
        threshold_fraction=.2, threshold_chosen='Single round-number exploratory threshold; no grid search or optimization.',
        rule='If completed one-minute option close <= 80% of actual buy fill, sell at exact following minute open minus 10bps.',
        precedence='Scheduled exit, then original Supertrend exit, then premium stop; one position, same original rearm rule and no same-minute reentry.',
        missing_data='Missing or zero-volume monitoring/fill minute leaves unresolved position and suppresses summary.',
        scope='Full primary-strategy replay including newly available later entries after early exits; original public fees and 10bps each side.',
        interpretation='Both periods already inspected. Retrospective exploratory comparison only; no untouched validation.',
        source_hashes={str(p):digest(p) for p in map(Path,['core/research/options_backtest.py','core/research/options_strategy.py',
            'core/research/options_costs.py','core/execution/upstox.py','scripts/research_options_premium_stop.py'])})
    plan_file=output/'experiment-plan.json'
    if plan_file.exists():
        old=json.loads(plan_file.read_text())
        if {k:v for k,v in old.items() if k!='created_at'}!={k:v for k,v in plan.items() if k!='created_at'}:
            raise ValueError('Existing experiment plan differs; use a new experiment version.')
        plan=old
    else:
        history.save_json(plan_file,plan)
    results=dict(plan=plan,periods={})
    for name,months in [('development',range(4,8)),('comparison',range(8,10))]:
        original=json.loads((root/f'{name}-results.json').read_text())
        db=root/f'{name}-prices.sqlite3'
        if digest(db)!=original['price_index_sha256']:
            raise ValueError('Index checksum mismatch')
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
                if record['expiry'] in catalogs and catalogs[record['expiry']]!=values:
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
                raise ValueError('Current-code baseline does not reproduce saved trade ledger')
            variant=bt.replay(audit,prices,catalogs,sorted(catalogs),bt.ReplayConfig(**config,premium_stop_fraction=.2))
            period=dict(baseline_reproduced=True,price_index_sha256=original['price_index_sha256'],
                input_manifest_hashes=original['inputs'],baseline=baseline,premium_stop=variant)
            if variant['diagnostic_summary'] is not None:
                period['comparison']={key:dict(**stats(replay['trades']),**risk(connection,replay),
                    stop_exits=sum(t['reason']=='premium_stop_completed_minute' for t in replay['trades']))
                    for key,replay in [('baseline',baseline),('premium_stop',variant)]}
            results['periods'][name]=period
        finally:
            connection.close()
        print(name,json.dumps(period.get('comparison',dict(errors=variant['errors']))),flush=True)
    history.save_json(output/'results.json',results)
    html='<!doctype html><meta charset="utf-8"><title>20% premium-stop experiment</title><style>body{font:16px system-ui;max-width:1050px;margin:40px auto;padding:20px}td,th{padding:10px;border-bottom:1px solid #ddd;text-align:left}table{border-collapse:collapse}</style><h1>20% premium-loss stop: exploratory test</h1><p>'+escape(plan['rule'])+'</p><p>'+escape(plan['interpretation'])+'</p>'
    for name,period in results['periods'].items():
        html+='<h2>'+name.title()+'</h2><p>Original saved trade ledger reproduced with current fee code.</p>'
        if 'comparison' not in period:
            html+='<p>Unresolved inputs. No aggregate comparison published.</p>'
            continue
        html+='<table><tr><th>Scenario</th><th>Trades</th><th>Net INR</th><th>Observed close drawdown INR</th><th>Worst-to-peak %</th><th>Without top 2 INR</th><th>Stop exits</th></tr>'
        for key,v in period['comparison'].items():
            dd=v['observed_minute_close_drawdown']
            html+=f'<tr><td>{key}</td><td>{v["trades"]}</td><td>{v["net_pnl"]:,.2f}</td><td>{dd["rupees"]:,.2f}</td><td>{dd["percent"]:.2f}</td><td>{v["without_top_two"]:,.2f}</td><td>{v["stop_exits"]}</td></tr>'
        html+='</table>'
    html+='<h2>Limits</h2><p>The 20% threshold is a research assumption, not a maximum-loss guarantee. Gaps can produce worse fills. Minute closes omit intraminute extremes. Missing candidate prices and absent bid/ask evidence remain. Earlier exits may change subsequent entries; this test performs full replays. No threshold sweep was performed.</p><p><a href="results.json">Full ledgers and metrics</a> · <a href="experiment-plan.json">Recorded experiment plan</a></p>'
    (output/'report.html').write_text(html,encoding='utf-8')


if __name__=='__main__':
    main()

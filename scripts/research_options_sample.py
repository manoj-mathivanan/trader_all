"""Frozen-input options sample comparison; observed-chain results stay diagnostic."""
from datetime import date, datetime, timezone
import argparse
import csv
import hashlib
from html import escape
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research import options_backtest as bt, options_history as history, options_strategy


def run(directory):
    manifest, minutes, daily = bt.load_underlying(directory)
    options, catalogs, expiries = bt.load_option_sample(directory)
    research_manifest = json.loads((directory/'research-manifest.json').read_text(encoding='utf-8'))
    start, end = map(date.fromisoformat, (manifest['start'], manifest['end']))
    scenarios = [('strict_public_10bps', dict(chain_policy='strict', fee_model='upstox_options', brokerage_per_order=30, slippage_bps=10)),
                 ('observed_gross', dict(chain_policy='observed_traded')),
                 ('observed_public_10bps', dict(chain_policy='observed_traded', fee_model='upstox_options', brokerage_per_order=30, slippage_bps=10)),
                 ('observed_public_50bps', dict(chain_policy='observed_traded', fee_model='upstox_options', brokerage_per_order=30, slippage_bps=50))]
    results, summary = {}, []
    for timeframe in (3, 5):
        audit = bt.prepare_signals(minutes, daily, start=start, end=end, timeframe=timeframe)
        for variant in ('fixed_250', 'underlying_1pct'):
            for scenario, overrides in scenarios:
                key = f'{timeframe}m_{variant}_{scenario}'
                result = bt.replay(audit, options, catalogs, expiries,
                    bt.ReplayConfig(timeframe=timeframe, premium_variant=variant, **overrides))
                results[key] = result
                summary.append(dict(id=key, timeframe=timeframe, variant=variant, scenario=scenario,
                    status=result['status'], completed_trades=len(result['trades']),
                    unresolved=bool(result['unresolved_position']), skipped=len(result['skipped_entries']),
                    net_pnl_completed_trades=(result['diagnostic_summary'] or {}).get('net_pnl_completed_trades'),
                    total_fees=(result['diagnostic_summary'] or {}).get('total_fees'),
                    missing_candidate_observations=sum(r['missing_candidate_minutes'] for r in result['selection_coverage'])))
    report = dict(status='diagnostic_research_only', created_at=datetime.now(timezone.utc).isoformat(),
        start=str(start), end=str(end), specification=options_strategy.specification(),
        source_manifests=[dict(file=name, sha256=hashlib.sha256((directory/name).read_bytes()).hexdigest())
                          for name in ('underlying-manifest.json','research-manifest.json')],
        dataset=dict(expiries=sorted(catalogs), contracts=len(options),
            empty_contracts=sum(not bars for bars in options.values()), option_candles=sum(map(len,options.values())),
            provider_failures=research_manifest['failures']),
        fee_hypothesis=dict(source='https://upstox.com/brokerage-charges/', brokerage_source='https://upstox.com/plus/',
            brokerage_per_order=30, account_tariff_verified=False,
            note='Public Plus tariff applied retrospectively for comparison; not a reconstruction of account charges.'),
        limitations=['Retrospective sample; no prospective forward validation or established trading edge.',
            'Strict coverage and observed-traded diagnostics are separate variants.',
            'Missing candidate prices can affect nearest-premium selection; observed results are not validated strategy returns.',
            'Minute OHLC does not contain bid/ask spreads or execution depth.',
            'No intratrade drawdown or historical exchange-calendar certification.'],
        summary=summary, replays=results)
    history.save_json(directory/'research-results.json', report)
    with (directory/'research-summary.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)
    ledgers = []
    for key,result in results.items():
        ledgers.extend(dict(experiment=key, **trade) for trade in result['trades'])
    if ledgers:
        with (directory/'research-trades.csv').open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(ledgers[0]))
            writer.writeheader()
            writer.writerows(ledgers)
    def display(value):
        return f'{value:,.2f}' if isinstance(value, float) else str(value)
    rows = ''.join('<tr>'+''.join(f'<td>{escape(display(row.get(column,"")))}</td>' for column in summary[0])+'</tr>' for row in summary)
    html = '<!doctype html><meta charset="utf-8"><title>NIFTY options sample research</title><style>body{font:15px system-ui;margin:32px;color:#172033}table{border-collapse:collapse;font-size:13px}td,th{padding:9px;border:1px solid #cdd5df;text-align:left}th{background:#edf2f7}p{max-width:1000px}</style>'
    html += f'<h1>NIFTY options sample: {start} to {end}</h1><p><strong>Diagnostic research only. These are not validated strategy returns.</strong></p>'
    html += '<p>'+escape('; '.join(report['limitations']))+'</p>'
    html += '<h2>Observed-traded diagnostic: public fees and 10 bps slippage per side</h2><p>One historical lot per trade; illustrative initial cash INR 100,000. Public Plus brokerage INR 30 per order, with statutory fee hypothesis. Missing candidate prices remain a qualification on every result.</p>'
    html += '<table><tr><th>Timeframe / premium rule</th><th>Trades</th><th>Net P&amp;L (INR)</th><th>Worst trade (INR)</th><th>P&amp;L without two largest winners (INR)</th></tr>'
    for key,result in results.items():
        if key.endswith('observed_public_10bps') and result['diagnostic_summary']:
            value = result['diagnostic_summary']
            html += '<tr>'+''.join('<td>'+escape(display(v))+'</td>' for v in (
                key.replace('_observed_public_10bps',''), value['completed_trades'],value['net_pnl_completed_trades'],
                value['worst_trade_pnl'],value['pnl_without_largest_two_trades']))+'</tr>'
    html += '</table><h2>All scenarios and coverage checks</h2>'
    html += '<table><thead><tr>'+''.join('<th>'+escape(k)+'</th>' for k in summary[0])+'</tr></thead><tbody>'+rows+'</tbody></table>'
    (directory/'research-report.html').write_text(html, encoding='utf-8')
    print(json.dumps(dict(dataset=report['dataset'], summary=summary)), flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=Path('artifacts/options_research'))
    run(parser.parse_args().input)

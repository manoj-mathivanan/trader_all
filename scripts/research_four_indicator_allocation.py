"""Predeclared allocation comparison on a verified frozen daily equity snapshot."""
import argparse
import csv
from datetime import date
import gzip
import hashlib
from html import escape
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research import four_indicator_swing as fs


VARIANTS = {
    'baseline': {},
    'volume_ranking': dict(candidate_ranking='relative_volume'),
    'atr_allocation': dict(target_atr_pct=2, max_position_pct=15),
    'market_scaling': dict(market_weak_scale=.5),
    'sector_scaling': dict(sector_weak_scale=.5),
    'sector_cap': dict(max_sector_pct=30),
    'combined': dict(candidate_ranking='relative_volume', target_atr_pct=2, max_position_pct=15,
                     market_weak_scale=.5, sector_weak_scale=.5, max_sector_pct=30),
}


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')


def run(snapshot, output):
    source = json.loads(gzip.decompress(snapshot.read_bytes()))
    frozen, original = source['frozen'], source['report']
    if fs.digest(frozen) != original['input_sha256']:
        raise ValueError('Frozen snapshot checksum mismatch.')
    cfg = fs.SwingConfig(start=original['config']['start'], end=original['config']['end'],
                         coverage_mode='available_history', capital=1000000, max_positions=10,
                         rule_set='bollinger', rsi_threshold=65, bollinger_multiplier=2.5,
                         slippage_bps=original['config'].get('slippage_bps',10))
    middle = cfg.start + (cfg.end-cfg.start)//2
    periods = {'full':cfg, 'earlier':cfg.model_copy(update={'end':middle}),
               'later':cfg.model_copy(update={'start':date.fromordinal(middle.toordinal()+1)})}
    root = Path(__file__).resolve().parents[1]
    files = ['core/strategies/four_indicator_allocation.py','core/research/four_indicator_swing.py',
             'core/strategies/four_indicator.py','core/execution/upstox.py',
             'scripts/research_four_indicator_allocation.py']
    plan = dict(input_sha256=original['input_sha256'], snapshot=str(snapshot.resolve()),
                config=cfg.model_dump(mode='json'), variants=VARIANTS,
                periods={k:dict(start=str(v.start),end=str(v.end)) for k,v in periods.items()},
                eligible_symbols=len(frozen['datasets']),
                source_sha256={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in files},
                limitations=[
                    'All periods have previously been inspected. Chronological cash-start blocks are retrospective diagnostics, not untouched validation.',
                    'Current frozen universe and sector labels cause survivorship and historical classification bias.',
                    'Same completed-close entry eligibility and next-open Supertrend exits. No executable protective stop or calibrated win probability.',
                    'Breadth uses available frozen stock candles, not an official index. Missing coverage uses the weak multiplier.',
                    'Controls apply to new entries; holdings are not rebalanced. Realized exposure can exceed caps after price changes.',
                    'Full delivery charges and explicit slippage follow the shared engine; historical tariff changes, dividends and market impact are not reconstructed.',
                    'No application storage, existing paper portfolio, or production settings are modified.',
                ])
    output.mkdir(parents=True, exist_ok=True)
    plan_path = output/'frozen-plan.json'
    if plan_path.exists() and json.loads(plan_path.read_text(encoding='utf-8')) != plan:
        raise ValueError('Comparison plan changed; choose a new output directory.')
    save(plan_path,plan)
    data = frozen['datasets']
    signals = fs.features(data, lambda s: print(s,flush=True), **fs.stored_parameters(cfg.model_dump()))
    records = []
    for period, settings in periods.items():
        for name, options in VARIANTS.items():
            config = settings.model_copy(update=options)
            result = fs.simulate(data,signals,config,fs.RULES[3],instruments=frozen['universe']['instruments'])
            metrics = result['metrics']
            if abs(metrics['final_equity']-config.capital-sum(t['pnl'] for t in result['trades'])) > 1e-5:
                raise ValueError('Trade accounting mismatch.')
            # Same signal universe, frozen inputs, costs and exits for every comparison.
            if name == 'baseline':
                plain = fs.simulate(data,signals,settings,fs.RULES[3])
                if plain['curve'] != result['curve']:
                    raise ValueError('Default allocation changed legacy fills.')
            row = dict(period=period,variant=name,**metrics,
                       turnover_multiple=metrics['traded_notional']/config.capital,
                       pnl_excluding_top_five=metrics['net_pnl']-metrics['top_five_pnl'])
            records.append(row)
            save(output/f'{period}-{name}.json',dict(config=config.model_dump(mode='json'),
                 input_sha256=plan['input_sha256'],**result))
            print(f'{period} / {name}: return {metrics["return_pct"]:.2f}%; drawdown {metrics["max_drawdown_pct"]:.2f}%; {metrics["trade_count"]} trades',flush=True)
    save(output/'comparison.json',dict(plan=plan,results=records))
    columns = ['period','variant','return_pct','max_drawdown_pct','trade_count','win_rate',
               'profit_factor','average_exposure_pct','turnover_multiple','modeled_fees','net_pnl','pnl_excluding_top_five']
    with (output/'comparison.csv').open('w',newline='',encoding='utf-8') as handle:
        writer = csv.DictWriter(handle,fieldnames=columns,extrasaction='ignore')
        writer.writeheader(); writer.writerows(records)
    page = ('<!doctype html><meta charset="utf-8"><title>Four-indicator allocation comparison</title>'
            '<style>body{font:15px/1.5 system-ui;color:#203341;margin:32px}table{border-collapse:collapse;width:100%}'
            'td,th{border:1px solid #ccd5dd;padding:8px;text-align:right}th{background:#eef3f6}'
            '.scroll{overflow:auto}p{max-width:1000px}</style><h1>Four-indicator allocation comparison</h1>'
            f'<p>{cfg.start} to {cfg.end} · {len(data)} frozen stocks · INR 10 lakh · ten positions maximum. '
            'RSI &gt;65, Bollinger 20/2.5, prior-day R1 and Supertrend 10/3. Same entries and exits throughout.</p>'
            '<p>Research only. None of these periods is untouched validation. Smaller allocations can lower both return and drawdown; '
            'compare exposure and turnover alongside performance.</p><div class="scroll"><table><tr>'
            + ''.join(f'<th>{escape(c.replace("_"," "))}</th>' for c in columns) + '</tr>')
    for row in records:
        page += '<tr>'+''.join('<td>'+escape(f'{row[c]:,.2f}' if isinstance(row[c],float) else str(row[c]) if row[c] is not None else '—')+'</td>' for c in columns)+'</tr>'
    page += '</table></div><h2>Predeclared variants</h2>'
    page += ''.join(f'<p><b>{escape(k)}</b>: {escape(json.dumps(v))}</p>' for k,v in VARIANTS.items())
    page += '<h2>Limits of this comparison</h2>'+''.join(f'<p>{escape(s)}</p>' for s in plan['limitations'])
    (output/'report.html').write_text(page,encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, default=Path('artifacts/four_indicator_year_20261025/frozen.json.gz'))
    parser.add_argument('--output', type=Path, default=Path('artifacts/four_indicator_allocation_20261030'))
    args = parser.parse_args()
    run(args.snapshot,args.output)

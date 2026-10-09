"""Matched five-position swing comparison using frozen prices and dated filings."""
import argparse
from pathlib import Path
import sys
import hashlib
import json
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research import backtest, store, fundamental_history
from core.research.config import BacktestConfig, Settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', required=True, help='Saved swing backtest with frozen price inputs')
    parser.add_argument('--start', default='2026-06-01')
    parser.add_argument('--end', default='2026-10-01')
    args = parser.parse_args()
    reference = store.read('runs/'+args.reference)
    if not reference:
        parser.error('Reference run does not exist')
    if reference['config'].get('execution_horizon', 'swing') != 'swing':
        parser.error('Choose a swing reference run')
    evidence = fundamental_history.capture(reference['universe_snapshot'], lambda x: print(x, flush=True))
    comparison = dict(reference=args.reference, start=args.start, end=args.end, max_positions=5,
                      financial_sha256=evidence['sha256'], notice=evidence['notice'], runs=[])
    settings = Settings(universe=reference['universe'])
    for pattern in ('blue_sky', 'vcp'):
        for ranking in ('alphabetical', 'fundamental_score'):
            cfg = BacktestConfig(**{**reference['config'], 'start':args.start, 'end':args.end,
                                   'max_positions':5, 'pattern':pattern, 'candidate_rank':ranking,
                                   'name':f'{pattern} five positions · {ranking}', 'comparison_run_id':args.reference})
            run_id = uuid4().hex[:12]
            backtest.run(settings, cfg, lambda x: print(x, flush=True), run_id, fundamental_evidence=evidence)
            result = store.read('runs/'+run_id)
            # Assess closed trade entry dates, including the final test liquidation.
            scores = fundamental_history.Scores(evidence, cfg.entry_mode)
            values = [scores(t['symbol'], t['entry_date']) for t in result['trades']]
            usable = [v for v in values if fundamental_history.rank_key(v, '')[0] <= 0]
            comparison['runs'].append(dict(id=run_id, pattern=pattern, ranking=ranking, metrics=result['metrics'],
                                           trades_with_usable_score=len(usable), trades_without_usable_score=len(values)-len(usable),
                                           mean_entry_score=sum(v['score'] for v in usable)/len(usable) if usable else None,
                                           price_manifest_sha256=hashlib.sha256(json.dumps(result['manifest'],sort_keys=True).encode()).hexdigest()))
            print(comparison['runs'][-1], flush=True)
            store.write('company/validation/fundamental-ranking-comparison', comparison)
    rows = ['# Fundamental ranking comparison', '', f'Period: {args.start} to {args.end}; five positions; ₹10 lakh starting capital.', '',
            'Identical frozen prices, universe, costs, signal rules and exits within each pair. Ranking is the only changed setting. '
            'This comparison does not add the live score/coverage buy filter.', '',
            '| Screen | Priority | Return | Max drawdown | Trades | Win rate | Trades with usable score | Mean entry score |',
            '|---|---|---:|---:|---:|---:|---:|---:|']
    for r in comparison['runs']:
        m = r['metrics']
        rows.append(f"| {r['pattern']} | {r['ranking']} | {m['return_pct']:.2f}% | {m['max_drawdown_pct']:.2f}% | {m['trade_count']} | {m['win_rate'] or 0:.2f}% | {r['trades_with_usable_score']}/{m['trade_count']} | {r['mean_entry_score'] or 0:.2f} |")
    rows.extend(['', evidence['notice'], '', 'Scores use publication dates and verified raw filing checksums. '
                 'Intermediate historical quarters are incomplete. The short window and current constituents limit conclusions. '
                 'A higher score is a financial quality preference, not a forecast of price returns.', '',
                 'Run IDs: '+', '.join(r['id'] for r in comparison['runs'])])
    for pattern in ('blue_sky','vcp'):
        pair = [r for r in comparison['runs'] if r['pattern']==pattern]
        if len({r['price_manifest_sha256'] for r in pair}) != 1:
            raise ValueError('Comparison price inputs differ')
    (store.ROOT/'FUNDAMENTAL_RANKING_COMPARISON.md').write_text('\n'.join(rows)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()

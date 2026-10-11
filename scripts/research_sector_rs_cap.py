"""Matched frozen-data comparison of RS70, sector cap2, and their combination."""
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.research import backtest, corporate_actions, fundamental_history, market_history
from core.research.config import BacktestConfig
from core.research.relative_strength import StrengthHistory
from core.research.sector_breadth import SectorBreadth
from scripts.run_sector_forward_test import engine
from scripts.research_sector_emerging_rs import PERIODS


def main():
    output = ROOT / 'artifacts/sector_rs_cap'
    output.mkdir(parents=True, exist_ok=True)
    read = lambda name: json.loads((ROOT / ('data/' + name + '.json')).read_text(encoding='utf-8'))
    original = read('runs/5cafe09b6cdc')
    data = read('run_data/5cafe09b6cdc')
    financial = read('run_fundamentals/5cafe09b6cdc')
    assert all(market_history.digest(data[m['symbol']]) == m['sha256'] for m in original['manifest'])
    assert financial['sha256'] == original['fundamental_reference']['sha256']
    assert not any(a['price_basis'] == 'raw' or a['volume_basis'] == 'raw'
                   for rows in data.values() for a in corporate_actions.actions(rows))
    instruments = original['universe_snapshot']['instruments']
    sectors = {i['symbol']: i['sector'] for i in instruments}
    base = BacktestConfig(**original['config'])
    scores = fundamental_history.Scores(financial)
    gate = SectorBreadth(data, instruments, 60, 80)
    strength = StrengthHistory(data)
    variants = {'control': (0, 0), 'rs70': (70, 0), 'sector_cap2': (0, 2), 'rs70_sector_cap2': (70, 2)}
    protocol = dict(source_run=original['id'], eligible_stocks=len(data), periods=PERIODS, variants=variants,
                    notice='All historical periods were previously inspected; these are retrospective robustness diagnostics, not untouched out-of-sample validation. Each period starts with fresh capital and holdings. Full run carries positions continuously.',
                    source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (output / 'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')
    signal, old_strength = backtest.signal, backtest.emerging_rs.StrengthHistory
    cache = {}
    def cached(bars, i, cfg):
        key = id(bars), i
        if key not in cache:
            cache[key] = signal(bars, i, cfg)
        return cache[key]
    backtest.signal = cached
    backtest.emerging_rs.StrengthHistory = lambda datasets, context=None: strength
    results = {}
    try:
        for name, (rs, cap) in variants.items():
            results[name] = {}
            for period, (start, end) in PERIODS.items():
                cfg = base.model_copy(update={'start': date.fromisoformat(start), 'end': date.fromisoformat(end),
                                             'min_short_rs_rating': rs, 'skip_weak_markets': False})
                audit = []
                result = engine(cap, sectors, audit)(data, cfg, fundamental_scores=scores, sector_gate=gate)
                if name == 'control' and period == 'full':
                    assert result['metrics'] == original['metrics']
                    assert result['curve'] == original['curve']
                    fields = ['symbol', 'entry_date', 'exit_date', 'entry', 'exit', 'quantity', 'pnl', 'r', 'reason', 'fees']
                    assert [{k: t[k] for k in fields} for t in result['trades']] == [{k: t[k] for k in fields} for t in original['trades']]
                summary = dict(**result['metrics'], losses=sum(t['pnl'] < -1e-6 for t in result['trades']),
                               cap_rejections=sum(a.get('reason') == 'Two positions in sector' for a in audit))
                results[name][period] = summary
                (output / f'{name}_{period}.json').write_text(json.dumps(dict(metrics=summary, trades=result['trades'], curve=result['curve'], audit=audit), indent=2), encoding='utf-8')
                (output / 'comparison.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
                print(name, period, json.dumps(summary), flush=True)
    finally:
        backtest.signal, backtest.emerging_rs.StrengthHistory = signal, old_strength


if __name__ == '__main__':
    main()

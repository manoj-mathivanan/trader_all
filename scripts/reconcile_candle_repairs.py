"""Read-only replay of a frozen paper checkpoint; emits narrowly bound evidence."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research import store, market_history, candle_repairs, backtest, data_quality
from core.portfolio import paper


def reconcile(portfolio, data_dir):
    cycles = portfolio.get('cycles', [])
    if not cycles or any(c.get('sessions') != 1 or c.get('start') != c.get('end') for c in cycles):
        raise ValueError('This replay supports evidenced single-session cycles only; broader checkpoints require a separate reconstruction.')
    if any(c['config']['capital'] != cycles[0]['config']['capital'] for c in cycles):
        raise ValueError('Capital changes require separate reconciliation.')
    store.DATA = Path(data_dir)
    new_ref = market_history.evidence(snapshot=True)
    old_ref = deepcopy(new_ref); old_ref['candle_repairs'] = {}
    inputs = ({}, {})
    for item in portfolio['universe_snapshot']['instruments']:
        record = store.read('bars/' + item['isin'])
        if paper.digest(record['bars'], portfolio['ledger']['last_session']) != portfolio['fingerprints'][item['symbol']]:
            raise ValueError('Frozen source does not match processed checkpoint: ' + item['symbol'])
        for index, ref in enumerate((old_ref, new_ref)):
            bars, _ = market_history.prepare(item, record, reference=ref)
            if bars:
                inputs[index][item['symbol']] = bars
    ledgers = [None, None]
    for cycle in cycles:
        cfg = paper.PaperConfig(**cycle['config'])
        simulation = SimpleNamespace(**cfg.model_dump(), start=cycle['start'], end=cycle['end'])
        for index in range(2):
            data_quality.require_no_anomalies(data_quality.audit(inputs[index], start=cycle['start'], end=cycle['end']))
            ledgers[index] = backtest.simulate(inputs[index], simulation, state=ledgers[index], liquidate=False,
                                              allow_entries=cycle['status']=='active', entry_warmup=backtest.required_warmup(cfg))['state']
    # Saved order metadata is added by paper.cycle after fills. Restrict this first
    # reconciliation to checkpoints without orders so equality covers every field.
    if portfolio['ledger']['orders'] or any(x['orders'] for x in ledgers):
        raise ValueError('Fill-bearing checkpoints require a separate order-metadata reconciliation.')
    if not ledgers[0] == ledgers[1] == portfolio['ledger']:
        raise ValueError('Replayed ledgers differ; no reconciliation evidence emitted.')
    return {**candle_repairs.checkpoint_identity(portfolio, new_ref), 'result':'identical_ledgers',
            'checked_cycles': len(cycles), 'checked_symbols': len(inputs[1]),
            'notice':'Original, corrected and saved ledgers match exactly; no cash, fills or positions rewritten.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--portfolio', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = reconcile(json.loads(args.portfolio.read_text(encoding='utf-8')), args.data_dir)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump({result['portfolio_id']:result}, stream, indent=2)
    print(json.dumps(result, indent=2))

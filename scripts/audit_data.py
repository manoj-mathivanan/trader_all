"""Read-only local gap/history audit. Writes only the explicitly chosen report."""
import argparse
import json
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research import data_quality, market_history, provenance, backtest
from core.research.config import BacktestConfig


def audit_directory(root):
    findings, symbols = [], {}
    for path in sorted((root / 'universes').glob('*.json')):
        universe = json.loads(path.read_text(encoding='utf-8'))
        symbols.update({item['isin']: item['symbol'] for item in universe.get('instruments', [])})
    scanned = 0
    for path in sorted((root / 'bars').glob('*.json')):
        record = json.loads(path.read_text(encoding='utf-8'))
        symbol = symbols.get(path.stem, record.get('symbol', path.stem))
        scanned += 1
        findings.extend(data_quality.audit({symbol: record['bars']})['findings'])
    # Exact holding-period overlap is only one channel of impact. Signals, warmup,
    # breadth and ranking can be affected even if a symbol was never traded.
    runs = []
    for path in sorted((root / 'runs').glob('*.json')):
        result = json.loads(path.read_text(encoding='utf-8'))
        overlaps = []
        for trade in result.get('trades', []):
            for finding in findings:
                if (trade['symbol'] == finding['symbol']
                        and trade['entry_date'] <= finding['date'] <= trade['exit_date']):
                    overlaps.append({'symbol': trade['symbol'], 'entry_date': trade['entry_date'],
                                     'exit_date': trade['exit_date'], 'anomaly_date': finding['date']})
        runs.append({'run_id': result.get('id', path.stem), 'holding_period_overlaps': overlaps})
    return {'version': data_quality.VERSION, 'adjustment_status': 'unverified',
            'gap_threshold_pct': data_quality.GAP_THRESHOLD_PCT,
            'symbols_scanned': scanned, 'runs_scanned': len(runs),
            'findings': findings, 'runs': runs,
            'limitations': ['Current cached bars were scanned; frozen run inputs may differ.',
                           'No event calendar was matched. A gap does not confirm a split/bonus.',
                           'No overlap does not establish clean signals, warmup, breadth or ranking.',
                           'Smaller corporate actions can remain undetected.']}


def audit_frozen_runs(root, replay_dir=None):
    started_provenance = provenance.capture()
    reference = market_history.evidence()
    listing_path = root / 'metadata/listings.json'
    action_path = root / 'metadata/corporate_actions.json'
    local_listings = json.loads(listing_path.read_text(encoding='utf-8')) if listing_path.exists() else {}
    reference['listings'] = market_history.merge_listings(reference.get('listings', {}), local_listings)
    reference['corporate_actions'] = json.loads(action_path.read_text(encoding='utf-8')) if action_path.exists() else {}
    reference['local_metadata_frozen'] = True
    records = []
    for index, path in enumerate(sorted((root / 'runs').glob('*.json'))):
        result = json.loads(path.read_text(encoding='utf-8'))
        snapshot = root / 'run_data' / path.name
        run = {'run_id': result.get('id', path.stem), 'replay_status': 'not_needed'}
        if not snapshot.exists():
            run['replay_status'] = 'missing_frozen_inputs'
            records.append(run)
            continue
        with snapshot.open('rb') as stream:
            run['frozen_input_sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
        datasets = json.loads(snapshot.read_text(encoding='utf-8'))
        end = result['config']['end']
        run['frozen_findings'] = data_quality.audit(datasets, end=end)['findings']
        by_symbol = {x['symbol']: x for x in result.get('universe_snapshot', {}).get('instruments', [])}
        derived, changes = {}, []
        for symbol, bars in datasets.items():
            item = by_symbol.get(symbol)
            if item is None:
                derived[symbol] = bars
                continue
            prepared, details = market_history.prepare(item, {'bars': bars}, reference=reference, fingerprint=False)
            if details.get('removed_prelisting_bars') or details.get('quarantine') or details.get('candle_repairs'):
                changes.append({'symbol': symbol, **details})
            if prepared:
                derived[symbol] = prepared
        run['history_changes'] = changes
        run['remaining_findings'] = data_quality.audit(derived, end=end)['findings']
        if changes or run['frozen_findings']:
            run['replay_status'] = 'needs_review'
        if replay_dir is not None and changes:
            try:
                cfg = BacktestConfig(**result['config'])
                data_quality.require_no_anomalies(data_quality.audit(derived, end=end))
                if cfg.pattern == 'ipo':
                    derived = {s: rows for s, rows in derived.items() if rows[0].get('listing_metadata', {}).get('ipo_verified') is True}
                warmup = max(backtest.required_warmup(cfg), cfg.minimum_warmup_sessions)
                derived = {s: rows for s, rows in derived.items()
                           if sum(b['date'] < str(cfg.start) for b in rows) >= warmup}
                if not derived:
                    raise ValueError('No eligible inputs after sourced history and warmup checks.')
                replay = backtest.simulate(derived, cfg)
                replay.pop('state')
                replay.update(original_run_id=run['run_id'], config=result['config'],
                              history_changes=changes, provenance=started_provenance,
                              warning='Replay uses current code and current evidence; metric changes cannot be attributed solely to one data repair. Survivorship bias remains.')
                replay_dir.mkdir(parents=True, exist_ok=True)
                (replay_dir / path.name).write_text(json.dumps(replay, indent=2, allow_nan=False) + '\n')
                run.update(replay_status='replayed', old_metrics=result['metrics'], new_metrics=replay['metrics'])
            except ValueError as exc:
                run.update(replay_status='blocked', reason=str(exc))
        records.append(run)
        if (index + 1) % 10 == 0:
            print(f'Audited {index + 1} frozen reports.', flush=True)
    ended_provenance = provenance.capture()
    return {'version': 2, 'runs_scanned': len(records), 'runs': records,
            'provenance': started_provenance,
            'source_changed_during_audit': started_provenance['source_tree_sha256'] != ended_provenance['source_tree_sha256'],
            'limitations': ['Full frozen candle inputs scanned, including warmup; no reports or ledgers overwritten.',
                           'Unclassified events and gaps still block reruns. Event/listing evidence coverage is partial.',
                           'No clean result proves an edge. Current-universe survivorship bias remains.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path(__file__).resolve().parents[1] / 'data')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--frozen', action='store_true', help='Audit actual saved inputs, not current cache')
    parser.add_argument('--replay-dir', type=Path, help='New directory for separate replays when history changes are fully cleared')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new output file; existing audit reports are preserved.')
    if args.replay_dir and (not args.frozen or args.replay_dir.exists()):
        parser.error('--replay-dir requires --frozen and a new directory.')
    report = audit_frozen_runs(args.data_dir, args.replay_dir) if args.frozen else audit_directory(args.data_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    if args.frozen:
        print(f"Audited {report['runs_scanned']} frozen reports. Saved {args.output}.")
    else:
        print(f"Scanned {report['symbols_scanned']} symbols and {report['runs_scanned']} reports; "
              f"{len(report['findings'])} gaps need review. Adjustment status remains unverified.")

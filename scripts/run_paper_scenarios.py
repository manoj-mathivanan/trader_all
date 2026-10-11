"""Run saved midday sector scenarios, with independent durable ledgers."""
import argparse
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.portfolio import manager
from scripts.setup_sector_paper_scenarios import SCENARIOS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--status', action='store_true')
    args = parser.parse_args()
    output = []
    for identity in SCENARIOS:
        p = manager.get('swing_patterns', identity)
        if not p:
            raise ValueError('Missing registered scenario: ' + identity)
        if not args.status:
            # Shared store.LOCK serializes this process with its own callers;
            # the dashboard owns automatic executions. Automation reads status
            # rather than starting a second executor alongside the scheduler.
            raise ValueError('Use the dashboard scheduler or scenario cycle endpoint to execute. CLI is status-only to avoid concurrent writers.')
        ledger = p.get('ledger', {})
        output.append(dict(id=identity, name=p['config']['name'], execution_time=p['config']['execution_time'],
                           time=f"{p['config']['run_hour']:02}:{p['config']['run_minute']:02} IST",
                           last_session=ledger.get('last_session'), equity=p.get('metrics', {}).get('final_equity', p['config']['capital']),
                           orders=len(ledger.get('orders', [])), positions=len(ledger.get('positions', {})),
                           closed_trades=len(ledger.get('trades', []))))
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()

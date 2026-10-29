"""Export research specification, probe Upstox access, or archive a bounded sample."""
import argparse
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from core.research import options_history as history, options_strategy, store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['spec', 'probe', 'sample', 'underlying', 'research'], default='spec')
    parser.add_argument('--start', type=date.fromisoformat)
    parser.add_argument('--end', type=date.fromisoformat)
    parser.add_argument('--max-contracts', type=int, default=40)
    parser.add_argument('--output', type=Path, default=Path('artifacts/options_research'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    history.save_json(args.output/'specification.json', options_strategy.specification())
    if args.mode == 'spec':
        print(json.dumps(dict(status='specification_saved', file=str(args.output/'specification.json'))))
        return 0
    try:
        token = store.token()
    except Exception:
        history.save_json(args.output/'access.json', dict(status='credentials_unavailable',
            reason='Configured credential store could not supply an Upstox token.'))
        print('Configured credential store could not supply an Upstox token. See access.json.')
        return 2
    end = args.end or datetime.now(history.IST).date()-timedelta(days=1)
    try:
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            if args.mode == 'probe':
                result = history.probe(client, token, end)
                history.save_json(args.output/'access.json', result)
                print(json.dumps(result))
                return 0 if all(x['status'] == 'accessible' for x in result.values()) else 2
            if args.start is None or args.end is None:
                parser.error('sample/underlying requires explicit --start and --end dates')
            if args.mode == 'underlying':
                result = history.download_underlying(client, token, start=args.start, end=end, output=args.output)
                print(json.dumps({k: result[k] for k in ('status', 'minute_bars', 'daily_bars', 'backtest_ready')}))
                return 0
            if args.mode == 'research':
                result = history.download_research(client, token, start=args.start, end=end, output=args.output,
                    log=lambda message: print(message, flush=True))
                print(json.dumps(dict(status=result['status'], contracts=len(result['files']), failures=len(result['failures']))))
                return 0 if not result['failures'] else 2
            result = history.download_sample(client, token, start=args.start, end=end,
                output=args.output, max_contracts=args.max_contracts)
            print(json.dumps({k: result[k] for k in ('status', 'expiry', 'selected_contract_count', 'backtest_ready')}))
            return 0 if not result['failures'] else 2
    except (ValueError, KeyError) as exc:
        # ProviderError messages deliberately exclude raw bodies and credentials.
        print(str(exc))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

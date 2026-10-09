"""Run with .venv/Scripts/python.exe scripts/pull_fundamentals.py."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.research import fundamentals, store


def main():
    parser=argparse.ArgumentParser(description='Pull and validate quarterly NSE fundamentals; no API key required.')
    parser.add_argument('--universe',default='niftytotalmarket',choices=['niftytotalmarket','nifty500','nifty50'])
    parser.add_argument('--symbols',nargs='+',help='Optional symbols for a focused retry/validation.')
    parser.add_argument('--retry-failed',action='store_true',help='Retry failed downloads checked today; current quarters remain skipped.')
    parser.add_argument('--validate-only',action='store_true',help='Audit stored hashes, company identity, dates and ratio arithmetic without network.')
    args=parser.parse_args()
    items=store.read('universes/'+args.universe,{}).get('instruments',[])
    if not items:
        parser.error('No stored universe. Refresh market universe first.')
    if args.symbols:
        symbols={s.upper() for s in args.symbols}
        items=[i for i in items if i['symbol'] in symbols]
        absent=symbols-{i['symbol'] for i in items}
        if absent:
            parser.error('Symbols outside stored universe: '+', '.join(sorted(absent)))
    result=fundamentals.audit(items) if args.validate_only else fundamentals.pull(items,lambda m:print(m,flush=True),retry_failed=args.retry_failed)
    print(json.dumps(result['counts'],sort_keys=True))
    return 1 if result['counts'].get('failed') else 0


if __name__=='__main__':
    raise SystemExit(main())

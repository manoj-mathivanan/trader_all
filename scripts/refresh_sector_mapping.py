"""Refresh official sector benchmark mappings without a price-provider token."""
import sys
import json
from pathlib import Path
from collections import Counter
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research import sector, store
from core.research.config import Settings


def main():
    settings = Settings(universe='niftytotalmarket')
    universe = store.read('universes/'+settings.universe, {})
    instruments = universe.get('instruments', [])
    if not instruments:
        raise ValueError('Refresh the Total Market universe first.')
    prior = store.read('sector/mapping', {})
    # Retain an explicit recoverable copy before replacing the live classification.
    if prior:
        store.write('sector/mapping_before_expansion', prior)
    with httpx.Client(timeout=40, follow_redirects=True, headers={'User-Agent':'Mozilla/5.0'}) as client:
        mapping = sector.refresh_mapping(client, settings, instruments, lambda m: print(m, flush=True))
    newly_mapped = sorted(s for s, row in mapping.items() if row['index'] and not prior.get('mappings', {}).get(s, {}).get('index'))
    unresolved = [dict(symbol=s, **row) for s, row in mapping.items() if not row['index']]
    missing_prices = {row['index'] for row in mapping.values() if row['index'] and not store.read('sector/prices/'+row['index'], {}).get('bars')}
    report = dict(completed_at=store.now(), total=len(mapping),
        mapped=sum(bool(row['index']) for row in mapping.values()), newly_mapped=newly_mapped,
        unresolved=unresolved, unresolved_industries=dict(Counter(row['industry'] for row in unresolved)),
        missing_index_prices=sorted(missing_prices),
        stocks_waiting_for_index_prices=sum(row['index'] in missing_prices for row in mapping.values()),
        notice=sector.NOTICE)
    store.write('sector/mapping_expansion', report)
    print(json.dumps({k:v for k,v in report.items() if k not in ('newly_mapped','unresolved')}, indent=2))


if __name__ == '__main__':
    main()

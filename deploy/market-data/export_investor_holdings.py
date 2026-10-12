"""Expose only open paper holdings to the user's authenticated local monitor."""
import json
from pathlib import Path
from datetime import datetime,timezone

root=Path('/srv/trader/data')
universe=json.loads((root/'universes/niftytotalmarket.json').read_text())
known={i['symbol']:i for i in universe.get('instruments',[])}
holdings=[]
paths=list((root/'portfolios').glob('*.json'))+list((root/'portfolio_scenarios').rglob('*.json'))
legacy=root/'paper_portfolio.json'
if legacy.exists():paths.append(legacy)
for path in paths:
    portfolio=json.loads(path.read_text())
    for symbol,position in portfolio.get('ledger',{}).get('positions',{}).items():
        item=known.get(symbol)
        if item:
            holdings.append(dict(isin=item['isin'],symbol=symbol,portfolio=portfolio.get('id',path.stem),
                                 entry_date=position.get('entry_date',position.get('date')),
                                 quantity=position.get('quantity')))
print(json.dumps(dict(as_of=datetime.now(timezone.utc).isoformat(),holdings=holdings)))

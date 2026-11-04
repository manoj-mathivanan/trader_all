"""Read-only calculator fallback for a local UI ahead of the production API."""
import csv
import io
import math
import time
from urllib.parse import unquote
import httpx
from fastapi.responses import JSONResponse

_members = None
_expires = 0


async def preview(client, production, headers, path):
    global _members, _expires
    try:
        if _members is None or time.monotonic() >= _expires:
            response = await client.get('https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv',
                                        headers={'User-Agent': 'Mozilla/5.0'}, follow_redirects=True, timeout=6)
            response.raise_for_status()
            rows = list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))
            members = [{'symbol': r['Symbol'].strip(), 'name': r['Company Name'].strip(),
                        'isin': r['ISIN Code'].strip()} for r in rows if not r['Symbol'].startswith('DUMMY')]
            if len(members) < 45 or len({r['isin'] for r in members}) != len(members):
                raise ValueError('Invalid membership')
            _members, _expires = members, time.monotonic() + 3600
        if path == 'intraday/stocks':
            return JSONResponse({'cached': False, 'as_of': time.strftime('%Y-%m-%d', time.gmtime()),
                                 'price_mode': 'saved_close',
                                 'stocks': sorted(_members, key=lambda i: i['symbol'])})
        # Prices require production authentication; the public member list does not.
        bootstrap = await client.get(production + '/api/bootstrap', headers=headers, timeout=15)
        if bootstrap.status_code != 200:
            return JSONResponse({'detail': 'Sign in to load stock prices.'}, status_code=bootstrap.status_code)
        instruments = {i['isin']: i for i in bootstrap.json().get('instruments', [])}
        symbol = unquote(path.removeprefix('intraday/price/'))
        member = next((i for i in _members if i['symbol'] == symbol), None)
        if member is None:
            raise ValueError('Select a Nifty 50 stock.')
        item = instruments.get(member['isin'], {})
        value = item.get('close')
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError('No saved price is available for this stock. Enter a price manually.')
        return JSONResponse({'price': value, 'as_of': item.get('last'), 'source': 'Saved daily close'})
    except (httpx.HTTPError, KeyError, ValueError):
        return JSONResponse({'detail': 'Stock data is unavailable. Retry or enter a price manually.'}, status_code=503)

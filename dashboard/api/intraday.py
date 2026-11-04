"""Read-only Nifty 50 membership and observed prices for the scenario calculator."""
import csv
import io
import math
import time
import httpx
from fastapi import APIRouter
from core.research import store, upstox

router = APIRouter(prefix='/api/intraday')
_membership = None
_expires = 0


@router.get('/backtests/{report_id}')
def target_backtest(report_id: str):
    from pathlib import Path
    from fastapi.responses import FileResponse, JSONResponse
    if report_id not in ('hdfcbank-target', 'hdfcbank-short-target', 'hdfcbank-target02', 'hdfcbank-short-target02'):
        return JSONResponse({'detail': 'Unknown backtest.'}, status_code=404)
    report = Path(__file__).resolve().parents[1] / 'reports' / (report_id + '.json')
    if not report.is_file():
        return JSONResponse({'detail': 'The HDFCBANK backtest has not been generated.'}, status_code=404)
    return FileResponse(report, media_type='application/json')


def membership():
    global _membership, _expires
    if _membership is not None and time.monotonic() < _expires:
        return _membership
    try:
        with httpx.Client(timeout=8, follow_redirects=True) as client:
            response = client.get(upstox.UNIVERSES['nifty50'], headers={'User-Agent': 'Mozilla/5.0'})
            response.raise_for_status()
        rows = list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))
        items = [{'symbol': r['Symbol'].strip(), 'name': r['Company Name'].strip(),
                  'isin': r['ISIN Code'].strip()} for r in rows if not r['Symbol'].startswith('DUMMY')]
        if len(items) < 45 or len({r['isin'] for r in items}) != len(items):
            raise ValueError('Invalid constituent list')
        _membership = {'instruments': items, 'fetched_at': store.now(), 'cached': False}
        _expires = time.monotonic() + 3600
        return _membership
    except (httpx.HTTPError, ValueError, KeyError):
        saved = store.read('universes/nifty50', {})
        if not saved.get('instruments'):
            raise ValueError('Nifty 50 list is unavailable. Retry later; manual prices still work.') from None
        return {**saved, 'cached': True}


@router.get('/stocks')
def stocks():
    universe = membership()
    catalog = store.read('bar_catalog', {})
    return {'as_of': universe.get('fetched_at'), 'cached': universe['cached'],
            'stocks': [{**{k: item.get(k, '') for k in ('symbol', 'name', 'isin')},
                        'price': catalog.get(item['isin'], {}).get('close'),
                        'price_as_of': catalog.get(item['isin'], {}).get('last')}
                       for item in sorted(universe['instruments'], key=lambda i: i['symbol'])]}


@router.get('/price/{symbol}')
def price(symbol: str):
    item = next((i for i in membership()['instruments'] if i['symbol'] == symbol), None)
    if item is None:
        raise ValueError('Select a Nifty 50 stock.')
    try:
        token = store.token()
        with httpx.Client(timeout=8) as client:
            response = client.get('https://api.upstox.com/v2/market-quote/quotes',
                                  params={'instrument_key': 'NSE_EQ|' + item['isin']},
                                  headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'})
            response.raise_for_status()
        payload = response.json()
        quote = next(q for q in payload.get('data', {}).values()
                     if q.get('instrument_token') == 'NSE_EQ|' + item['isin'])
        value = float(quote['last_price'])
        if not math.isfinite(value) or value <= 0 or not quote.get('timestamp'):
            raise ValueError('Invalid quote')
        return {'price': value, 'as_of': quote['timestamp'], 'source': 'Upstox quote'}
    except (httpx.HTTPError, ValueError, KeyError, TypeError, StopIteration):
        saved = store.read('bar_catalog', {}).get(item['isin'], {})
        value = saved.get('close')
        if not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
            raise ValueError('No quote or saved closing price is available. Enter a price manually.') from None
        return {'price': value, 'as_of': saved.get('last'), 'source': 'Saved daily close (quote unavailable)'}

"""Read-only provider/event sample. Never emits authentication data."""
import argparse
import csv
import io
import json
import urllib.request
import urllib.error
import zipfile
from pathlib import Path


def fetch(url, headers=None):
    try:
        request = urllib.request.Request(url, headers=headers or {'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(request, timeout=12) as response:
            return response.read(), response.status
    except urllib.error.HTTPError as exc:
        return None, exc.code
    except Exception as exc:
        return None, type(exc).__name__


def probe(data_dir, private_dir, universe='niftytotalmarket'):
    samples = {}
    universe = json.loads((data_dir / 'universes' / (universe + '.json')).read_text())
    token_path = private_dir / 'upstox.json'
    token = json.loads(token_path.read_text()).get('access_token') if token_path.exists() else None
    for symbol, days in {'NESTLEIND': ['2024-01-04', '2024-01-05', '2025-08-07', '2025-08-08'],
                         'RELIANCE': ['2024-10-25', '2024-10-28']}.items():
        item = next(x for x in universe['instruments'] if x['symbol'] == symbol)
        record = json.loads((data_dir / 'bars' / (item['isin'] + '.json')).read_text())
        sample = {'isin': item['isin'], 'cached_bars': [b for b in record['bars'] if b['date'] in days]}
        if token:
            url = f"https://api.upstox.com/v2/fundamentals/{item['isin']}/corporate-actions"
            raw, status = fetch(url, {'Authorization': 'Bearer ' + token, 'Accept': 'application/json'})
            sample.update(event_api_source=url, event_api_status=status)
            if status == 200:
                payload = json.loads(raw)
                sample['provider_events'] = payload.get('data', [])
        samples[symbol] = sample
    for symbol, url, day in [
        ('NESTLEIND', 'https://nsearchives.nseindia.com/content/historical/EQUITIES/2024/JAN/cm04JAN2024bhav.csv.zip', '2024-01-04'),
        ('RELIANCE', 'https://nsearchives.nseindia.com/content/historical/EQUITIES/2024/OCT/cm25OCT2024bhav.csv.zip', '2024-10-25')]:
        raw, status = fetch(url)
        sample = samples[symbol]
        sample.update(exchange_source=url, exchange_status=status)
        if status == 200:
            archive = zipfile.ZipFile(io.BytesIO(raw))
            rows = csv.DictReader(io.StringIO(archive.read(archive.namelist()[0]).decode()))
            match = next((r for r in rows if r.get('SYMBOL') == symbol and r.get('SERIES') == 'EQ'), None)
            sample['exchange_row'] = match
            cached = next((b for b in sample['cached_bars'] if b['date'] == day), None)
            if match and cached:
                sample['raw_to_cached_price_ratio'] = float(match['CLOSE']) / cached['close']
                sample['cached_to_raw_volume_ratio'] = cached['volume'] / float(match['TOTTRDQTY'])
    return {'version': 1, 'samples': samples,
            'limitations': 'A small sample cannot certify every symbol/event. Provider events require independent verification.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--private-dir', type=Path, required=True)
    parser.add_argument('--universe', default='niftytotalmarket', choices=['niftytotalmarket', 'nifty500', 'nifty50'], help='Current 750-stock universe; older snapshots can be audited explicitly')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists.')
    report = probe(args.data_dir, args.private_dir, args.universe)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print('Probe complete; public event/candle evidence saved. No credentials included.')

"""Extend only missing daily inputs for a declared backtest and its warmup."""
from datetime import date, timedelta
import httpx

from core.research import backtest, market_data, market_history, store


def backfill(settings, cfg, log, job_id=None):
    if cfg.comparison_run_id:
        raise ValueError('Backfill a fresh backtest; comparison inputs are frozen.')
    universe = store.read('universes/'+settings.universe)
    if not universe:
        raise ValueError('Refresh the universe first.')
    token = store.token()
    warmup = max(backtest.required_warmup(cfg), cfg.minimum_warmup_sessions)
    reference = market_history.evidence(snapshot=True)
    result = dict(job_id=job_id, universe=settings.universe, started_at=store.now(),
                  test_start=str(cfg.start), end=str(cfg.end), minute_start=str(cfg.end+timedelta(days=1)),
                  warmup_sessions=warmup,
                  daily_bars=0, stocks=[], failures=[], skipped_quarantined=[], reused_symbols=0)
    with httpx.Client(timeout=40) as client:
        calendar = market_data.upstox.fetch_range(client, market_data.BENCHMARK, token,
                                                  cfg.start-timedelta(days=warmup*2+30), cfg.end)
        earlier = [row['date'] for row in calendar if row['date'] < str(cfg.start)]
        if len(earlier) < warmup:
            raise ValueError('Benchmark history does not cover the required warmup sessions.')
        # Stock calendars can omit an observed benchmark session. Keep a small
        # buffer so one absent stock session does not leave it one candle short.
        start = date.fromisoformat(earlier[-min(len(earlier), warmup+10)])
        sessions = [row['date'] for row in calendar if row['date'] >= str(start)]
        result['daily_start'] = str(start)
        store.write('price_backfills/'+str(job_id), result)
        log(f'Backfill missing daily ranges: {start} to {cfg.end}; '
            f'{warmup} warmup sessions before {cfg.start}. Existing candles are retained.')
        for index, item in enumerate(universe['instruments'], 1):
            if item['isin'] in reference.get('quarantine', {}):
                result['skipped_quarantined'].append(item['symbol'])
                continue
            try:
                record = store.read('bars/'+item['isin'], {})
                if record.get('bars'):
                    bars, _ = market_history.prepare(item, record, reference=reference, fingerprint=False)
                    if (record.get('requested_start', bars[0]['date'] if bars else '') <= str(cfg.start)
                            and record.get('requested_end', '') >= str(cfg.end)
                            and sum(row['date'] < str(cfg.start) for row in bars) >= warmup):
                        result['reused_symbols'] += 1
                        continue
                listing = market_history.listing_for(item, reference.get('listings', {}))
                stock_start = max(start, date.fromisoformat(listing['listing_date'])) if (
                    listing and listing.get('verified') is True) else start
                unavailable = []
                count = market_data.save_daily(client, item, token, stock_start, cfg.end,
                                              sessions=sessions, allow_empty_prefix=True,
                                              unavailable_ranges=unavailable)
                result['daily_bars'] += count
                result['stocks'].append(dict(symbol=item['symbol'], isin=item['isin'], bars=count))
                if unavailable:
                    result['failures'].append(dict(symbol=item['symbol'],
                        message='Provider returned no candles for some observed sessions.', ranges=unavailable))
                    log(f"{item['symbol']}: {len(unavailable)} ranges unavailable; "
                        f'{count} valid missing bars saved, existing candles retained.')
            except Exception as exc:
                message = market_data.error_detail(exc)
                result['failures'].append(dict(symbol=item['symbol'], message=message))
                log(f"{item['symbol']}: {message} Existing candles retained.")
                if isinstance(exc, ValueError) and '401/403' in str(exc):
                    raise
            if index % 25 == 0 or index == len(universe['instruments']):
                log(f"Daily backfill {index}/{len(universe['instruments'])}: "
                    f"{result['daily_bars']} bars added, {len(result['failures'])} unavailable requests.")
    result['partial'] = bool(result['failures'])
    result['completed_at'] = store.now()
    store.write('price_backfills/'+str(job_id), result)
    log(f"Backfill saved {result['daily_bars']} missing daily bars. "
        'Stocks may still lack warmup, verified listing evidence or clean prices; rerun the eligibility check.')
    return result

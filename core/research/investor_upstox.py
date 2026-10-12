"""Instrument-keyed Upstox news; API summaries are never full article evidence."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
import httpx
from core.research import investor_intelligence as intel, store

URL = 'https://api.upstox.com/v2/news'


def normalize(raw, item, at):
    if not isinstance(raw, dict) or not isinstance(raw.get('heading'), str) or not isinstance(raw.get('article_link'), str) or not isinstance(raw.get('summary', ''), str):
        raise ValueError('Invalid news fields')
    published = datetime.fromtimestamp(float(raw['published_time']) / 1000, timezone.utc)
    if not at - timedelta(days=7) <= published <= at:
        raise ValueError('Outside provider window')
    url = intel.canonical(raw['article_link'])
    title = intel.clean(raw['heading'])[:300]
    if not title:
        raise ValueError('Missing headline')
    summary = intel.clean(raw.get('summary', ''))[:6000]
    text = title + (' — ' + summary if summary else '')
    return dict(id=hashlib.sha256(url.encode()).hexdigest()[:24], title=title, text=text,
                url=url, published_at=published.isoformat(), retrieved_at=at.isoformat(),
                sha256=hashlib.sha256(text.encode()).hexdigest(), source_id='upstox',
                publisher='Upstox News', source_kind='reporting', evidence_scope='api_summary',
                provider_instrument_keys=[item['key']])


def refresh(items, *, force=False, transport=None, log=lambda message: None):
    at = intel.company.utcnow()
    existing = {a['id']: a for a in store.read('investor/news', {}).get('articles', [])}
    targets = {i['isin']: dict(i, key=i.get('key') or 'NSE_EQ|' + i['isin']) for i in items}
    coverage, collected, pending = [], [], []
    for item in targets.values():
        cached = store.read('investor/discovery/upstox-' + item['isin'], {})
        ttl = 1800 if cached.get('coverage', {}).get('status') in ('available', 'empty') else 300
        if not force and 0 <= intel.cache_age(cached) < ttl:
            coverage.append(cached['coverage'])
            collected.extend(cached.get('articles', []))
        else:
            pending.append(item)
    if pending:
        try:
            token = store.token()
        except ValueError:
            token = None
        auth_failed = not token
        with httpx.Client(timeout=20, transport=transport, follow_redirects=False) as client:
            for offset in range(0, len(pending), 30):
                batch = pending[offset:offset + 30]
                by_key = {i['key']: i for i in batch}
                found = {i['isin']: {} for i in batch}
                skipped = {i['isin']: 0 for i in batch}
                failure = None
                try:
                    if auth_failed:
                        raise ValueError('Upstox access unavailable. Save a valid Analytics Token in production Settings.')
                    log('Fetching Upstox news for ' + ', '.join(i['symbol'] for i in batch) + '.')
                    page, total = 1, 1
                    while page <= total:
                        params = dict(category='instrument_keys', instrument_keys=','.join(by_key), page_number=page, page_size=100)
                        with client.stream('GET', URL, params=params, headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}) as response:
                            if response.status_code in (401, 403):
                                auth_failed = True
                                raise ValueError('Upstox rejected access. Replace the expired or invalid token in production Settings.')
                            if response.status_code != 200:
                                raise ValueError('Upstox news returned HTTP ' + str(response.status_code) + '.')
                            body = bytearray()
                            for chunk in response.iter_bytes():
                                body.extend(chunk)
                                if len(body) > 5_000_000:
                                    raise ValueError('Upstox news response exceeded size limit.')
                        payload = json.loads(body)
                        if not isinstance(payload, dict) or payload.get('status') != 'success' or not isinstance(payload.get('data'), dict):
                            raise ValueError('Upstox news response was invalid.')
                        digest = hashlib.sha256(body).hexdigest()
                        store.write('investor/feed_responses/upstox-' + digest,
                                    dict(as_of=at.isoformat(), source_id='upstox', request=params, response=payload))
                        for key, rows in payload['data'].items():
                            if key not in by_key:
                                continue
                            if not isinstance(rows, list):
                                raise ValueError('Upstox news items were invalid.')
                            item = by_key[key]
                            for raw in rows:
                                try:
                                    article = normalize(raw, item, at)
                                    previous = existing.get(article['id'], {})
                                    article['first_seen_at'] = previous.get('first_seen_at', previous.get('retrieved_at', at.isoformat()))
                                    found[item['isin']][article['id']] = article
                                except (ValueError, KeyError, TypeError, OverflowError, OSError):
                                    skipped[item['isin']] += 1
                        pagination = payload.get('metadata', {}).get('page', {})
                        if 'total_pages' not in pagination:
                            raise ValueError('Upstox pagination metadata missing; coverage may be incomplete.')
                        total = int(pagination['total_pages'])
                        if total > 100 or total < 0:
                            raise ValueError('Upstox pagination exceeds supported range.')
                        if int(pagination.get('page_number', page)) != page:
                            raise ValueError('Upstox returned an unexpected page.')
                        page += 1
                except (httpx.HTTPError, ValueError, TypeError, KeyError):
                    failure = ('Upstox access unavailable. Save a valid Analytics Token in production Settings.'
                               if auth_failed else 'Upstox news fetch incomplete or unavailable; retained articles do not establish complete coverage.')
                for item in batch:
                    articles = list(found[item['isin']].values())
                    row = dict(id='upstox', name='Upstox News: ' + item['symbol'], isin=item['isin'],
                               kind='reporting', url=URL, checked_at=at.isoformat(), count=len(articles),
                               skipped=skipped[item['isin']], status='unavailable' if failure else ('available' if articles else 'empty'),
                               reason=failure or 'Past 7 days only. API summaries require linked full article review; an empty result means unknown.')
                    store.write('investor/discovery/upstox-' + item['isin'], dict(as_of=at.isoformat(), articles=articles, coverage=row))
                    coverage.append(row)
                    collected.extend(articles)
    with store.LOCK:
        news = store.read('investor/news', {})
        by_id = {a['id']: a for a in news.get('articles', [])}
        for article in collected:
            previous = by_id.get(article['id'], {})
            article['first_seen_at'] = previous.get('first_seen_at', previous.get('retrieved_at', article['retrieved_at']))
            article['provider_instrument_keys'] = sorted(set(article['provider_instrument_keys'] + previous.get('provider_instrument_keys', [])))
            by_id[article['id']] = article
            intel.archive_article(article)
        news['articles'] = sorted(by_id.values(), key=lambda a: a['published_at'], reverse=True)[:3000]
        news['upstox_coverage'] = coverage
        store.write('investor/news', news)
    return dict(count=len({a['id'] for a in collected}), coverage=coverage,
                partial=any(r['status'] == 'unavailable' or r['skipped'] for r in coverage))

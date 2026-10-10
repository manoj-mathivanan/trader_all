"""Quarter-aware NSE fundamentals cache. No LLM calls or historical substitution."""
import hashlib
import math
import time
import uuid
import os
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
import httpx
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from core.research import store, official_filings
from pydantic import BaseModel, ConfigDict, Field


class BuyScreen(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    min_score: float = Field(60,ge=0,le=100,title='Minimum fundamental score')
    min_coverage_pct: float = Field(80,ge=0,le=100,title='Minimum evidence coverage (%)')
    max_age_days: int = Field(180,ge=1,le=730,title='Maximum financial period age (days)')


def buy_screen(strategy):
    if strategy not in ('swing_patterns','intraday_momentum'):
        raise ValueError('Unknown strategy.')
    return BuyScreen(**store.read('company/buy_screens/'+strategy,{}))


def buy_check(isin, strategy, *, at=None, screen=None):
    cfg=screen or buy_screen(strategy)
    result=check(isin,at=at)
    reasons=[]
    if result['score'] is None:
        reasons.append('Missing validated fundamentals')
    elif result['score'] < cfg.min_score:
        reasons.append(f"Score {result['score']} below {cfg.min_score}")
    if result['coverage_pct'] < cfg.min_coverage_pct:
        reasons.append(f"Evidence coverage {result['coverage_pct']}% below {cfg.min_coverage_pct}%")
    if result.get('period_age_days',cfg.max_age_days+1) > cfg.max_age_days:
        reasons.append('Financial period is stale')
    if result.get('latest_index_period') and result['snapshot'] and result['latest_index_period'] > result['snapshot']['period_end']:
        reasons.append('Newer published quarter has not passed validation')
    reasons.extend(result['flags'])
    return dict(**result,strategy_id=strategy,screen=cfg.model_dump(),buy_allowed=not reasons,block_reasons=reasons,
                checked_at=(at or datetime.now(timezone.utc)).isoformat())


def quarter_end(day):
    month = ((day.month - 1) // 3 + 1) * 3
    first_next = date(day.year + (month == 12), month % 12 + 1, 1)
    return first_next - timedelta(days=1)


def completed_quarter(day):
    end = quarter_end(day)
    return end if end <= day else quarter_end(date(day.year, ((day.month-1)//3)*3+1, 1)-timedelta(days=1))


def next_quarter(period):
    return quarter_end(date.fromisoformat(period)+timedelta(days=1)).isoformat()


def key(isin):
    import re
    if not re.fullmatch(r'IN[A-Z0-9]{10}', isin):
        raise ValueError('Invalid equity ISIN.')
    return 'company/fundamentals/'+isin


def validate(snapshot, documents, item, at):
    """Re-parse saved bytes, verify identity/dates/hash and independently rebuild ratios."""
    from core.research.company_review import FundamentalInput
    clean = FundamentalInput.model_validate({k:v for k,v in snapshot.items() if k in FundamentalInput.model_fields})
    if clean.isin != item['isin']:
        raise ValueError('Snapshot identity mismatch.')
    parsed = []
    for doc in documents:
        if doc['artifact'] != 'company/filings/'+doc['sha256']+'.html':
            raise ValueError('Invalid filing artifact path.')
        data = (store.DATA/doc['artifact']).read_bytes()
        if hashlib.sha256(data).hexdigest() != doc['sha256']:
            raise ValueError('Filing checksum mismatch.')
        parsed.append(official_filings.parse(data.decode('utf-8'), doc['url'], item, at))
    rebuilt = official_filings.calculate(parsed, item)
    if not rebuilt:
        raise ValueError('No validated financial metrics.')
    if snapshot['company_type'] != rebuilt['company_type']:
        raise ValueError('Filing taxonomy classification mismatch.')
    for field in FundamentalInput.model_fields:
        if field.endswith('_pct') or field in ('debt_equity','interest_coverage','cash_profit_ratio','auditor_concern','governance_concern'):
            if snapshot.get(field) != rebuilt.get(field):
                raise ValueError('Recalculated financial metric mismatch: '+field)
    for calc in snapshot.get('calculations', []):
        a,b = Decimal(calc['current']),Decimal(calc['prior'])
        value = (a/b-1)*100 if calc['formula']=='(current / prior - 1) * 100' else a/b*(100 if calc.get('percentage') else 1)
        if not math.isclose(float(value),calc['value'],rel_tol=1e-10,abs_tol=1e-10):
            raise ValueError('Ratio arithmetic mismatch.')
    return dict(status='passed', validated_at=at.isoformat(), documents=len(parsed), sha256_verified=True,
                identity_verified=True, metrics_recomputed=True)


def pull_stock(item, *, at=None, retry_failed=False, log=lambda _:None, client=None):
    from core.research import company_review as cr
    at = at or datetime.now(timezone.utc)
    today = at.astimezone(official_filings.IST).date()
    path = key(item['isin'])
    record = store.read(path, {})
    period = record.get('last_period_end')
    if period and period >= completed_quarter(today).isoformat() and record.get('latest_index_period', period) <= period:
        return dict(symbol=item['symbol'], isin=item['isin'], status='skipped_current', period_end=period)
    checked = record.get('last_checked_at')
    try:
        recent = checked and timedelta(0) <= at - datetime.fromisoformat(checked) < timedelta(hours=24)
    except (ValueError, TypeError):
        recent = False
    if recent and not (retry_failed and record.get('pull_status') in ('failed','unsupported')):
        status = 'skipped_checked_today' if checked[:10] == at.isoformat()[:10] else 'skipped_recent_check'
        return dict(symbol=item['symbol'], isin=item['isin'], status=status, period_end=period,
                    next_check_at=(datetime.fromisoformat(checked)+timedelta(hours=24)).isoformat())
    record.update(company=item, last_attempted_at=at.isoformat(), last_checked_at=at.isoformat())
    try:
        index = official_filings.discover(item, at, client=client)
        if index['status'] != 'available':
            raise ValueError('NSE filing index unavailable; existing data retained.')
        sources = index['sources']
        if not sources:
            reason = 'No supported NSE financial filings available; existing data retained.'
            record.update(pull_status='unsupported', reason=reason)
            store.write(path, record)
            return dict(symbol=item['symbol'], isin=item['isin'], status='unsupported', reason=reason)
        newest = max(s['period_end'] for s in sources)
        record['latest_index_period'] = newest
        if period and newest <= period:
            record.update(pull_status='awaiting_next_quarter', reason='Next quarter has not been published in the supported NSE index.')
            store.write(path, record)
            return dict(symbol=item['symbol'], isin=item['isin'], status='awaiting_next_quarter', period_end=period)
        # Prefer consolidated evidence, use standalone only when consolidated is absent.
        basis = 'consolidated' if any(s['basis']=='consolidated' and s['period_end']==newest for s in sources) else 'standalone'
        result = official_filings.retrieve(item, [s for s in sources if s['basis']==basis], at, log=log,
                                          cached_documents=record.get('documents', []), client=client)
        snapshot = result['snapshot']
        if not snapshot or snapshot['period_end'] != newest:
            raise ValueError('Latest indexed quarter could not be validated; existing data retained.')
        validation = validate(snapshot, result['documents'], item, at)
        snapshot.update(id=uuid.uuid4().hex, recorded_at=at.isoformat())
        record.update(snapshot=snapshot, score=cr.score(snapshot,at=at), documents=result['documents'],
                      validation=validation, download_failures=result['failures'], last_period_end=snapshot['period_end'],
                      next_quarter_end=next_quarter(snapshot['period_end']), last_pulled_at=at.isoformat(),
                      pull_status='updated', reason='', index_url=index['url'])
        store.write(path+'/history/'+snapshot['id'], record)
        store.write(path, record)
        return dict(symbol=item['symbol'], isin=item['isin'], status='updated', period_end=snapshot['period_end'],
                    score=record['score']['score'], coverage_pct=record['score']['coverage_pct'])
    except Exception as exc:
        # Never store provider headers/credentials or discard a previous validated snapshot.
        record.update(pull_status='failed', reason=str(exc) if isinstance(exc,ValueError) else 'Validation/download failed: '+type(exc).__name__)
        store.write(path, record)
        return dict(symbol=item['symbol'], isin=item['isin'], status='failed', reason=record['reason'])


@contextmanager
def pull_lock():
    path=store.DATA/'company/fundamentals-pull.lock'
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as handle:
        handle.seek(0,2)
        if handle.tell()==0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            raise ValueError('Another fundamentals pull is running. Let it finish before retrying.') from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name=='nt':
                msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                fcntl.flock(handle.fileno(),fcntl.LOCK_UN)


def pull(items, log=lambda _:None, job_id=None, *, retry_failed=False, at=None):
    with pull_lock():
        return _pull(items,log,job_id,retry_failed=retry_failed,at=at)


class FilingClient(httpx.Client):
    """Share connections while spacing all worker requests by at least 200 ms."""
    def __init__(self):
        super().__init__(timeout=httpx.Timeout(20, connect=5), follow_redirects=False,
                         headers={'User-Agent':'TraderCompanyResearch/1.0', 'Accept':'application/json,text/html'})
        self.request_lock = Lock()
        self.last_request = 0.0

    def send(self, *args, **kwargs):
        with self.request_lock:
            delay = .2 - (time.monotonic() - self.last_request)
            if delay > 0:
                time.sleep(delay)
            self.last_request = time.monotonic()
        return super().send(*args, **kwargs)


def _pull(items, log=lambda _:None, job_id=None, *, retry_failed=False, at=None):
    at = at or datetime.now(timezone.utc)
    result = dict(job_id=job_id, started_at=store.now(), total_symbols=len(items), counts={}, stocks=[])
    store.write('company/fundamentals_pull',result)
    def worker(item, client):
        messages = []
        try:
            row = pull_stock(item,at=at,retry_failed=retry_failed,log=messages.append,client=client)
        except ValueError as exc:
            row = dict(symbol=item['symbol'],isin=item['isin'],status='unsupported',reason=str(exc))
        except Exception as exc:
            row = dict(symbol=item['symbol'],isin=item['isin'],status='failed',
                       reason='Download/cache failed: '+type(exc).__name__)
        return row, messages

    log('Fundamentals: reusing cached quarters and publication checks from the last 24 hours; three workers check due companies.')
    ordered = {}
    with FilingClient() as client, ThreadPoolExecutor(max_workers=3, thread_name_prefix='fundamentals') as pool:
        pending = {pool.submit(worker, item, client): i for i, item in enumerate(items)}
        for n, future in enumerate(as_completed(pending), 1):
            row, messages = future.result()
            ordered[pending[future]] = row
            result['stocks'].append(row)
            status = row['status']
            result['counts'][status] = result['counts'].get(status, 0) + 1
            for message in messages:
                log(message)
            if status in ('failed', 'unsupported', 'updated'):
                log(f"Fundamentals {n}/{len(items)} · {row['symbol']}: {status}.")
            if n % 25 == 0 or n == len(items):
                store.write('company/fundamentals_pull',result)
                log(f"Fundamentals checked {n}/{len(items)}: {result['counts']}.")
    result['stocks'] = [ordered[i] for i in range(len(items))]
    result.update(completed_at=store.now(),partial=bool(result['counts'].get('failed') or result['counts'].get('unsupported')))
    result['coverage'] = coverage(items)
    store.write('company/fundamentals_pull',result)
    return result


def coverage(items):
    """Report saved snapshots separately from comparative source filings, without inference."""
    from collections import Counter
    current, versions, documents, statuses = [], {}, {}, Counter()
    for item in items:
        try:
            name = key(item['isin'])
        except ValueError:
            statuses['unsupported'] += 1
            continue
        record = store.read(name, {})
        statuses[record.get('pull_status', 'not_pulled')] += 1
        if record.get('validation', {}).get('status') == 'passed' and record.get('snapshot'):
            current.append(record['snapshot'])
            versions[(item['isin'], record['snapshot']['id'])] = record['snapshot']
            for document in record.get('documents', []):
                documents[document['sha256']] = document
        for path in (store.DATA/name/'history').glob('*.json'):
            old = store.read(name+'/history/'+path.stem, {})
            if old.get('validation', {}).get('status') == 'passed' and old.get('snapshot'):
                versions[(item['isin'], old['snapshot']['id'])] = old['snapshot']
                for document in old.get('documents', []):
                    documents[document['sha256']] = document
    periods = Counter(s['period_end'] for s in current)
    by_company = {}
    for (isin, _), snapshot in versions.items():
        by_company.setdefault(isin, set()).add(snapshot['period_end'])
    source_periods = Counter(d['end'] for d in documents.values() if d.get('end'))
    published = [d['filed_at'] for d in documents.values() if d.get('filed_at')]
    result = dict(measured_at=store.now(), total_symbols=len(items), validated_symbols=len(current),
                  missing_symbols=len(items)-len(current), pull_statuses=dict(statuses),
                  snapshot_periods=dict(sorted(periods.items())), retained_snapshot_versions=len(versions),
                  distinct_company_periods=sum(map(len, by_company.values())),
                  companies_with_multiple_snapshot_periods=sum(len(p)>1 for p in by_company.values()),
                  source_filings=len(documents), source_periods=dict(sorted(source_periods.items())),
                  first_source_publication=min(published, default=None), last_source_publication=max(published, default=None),
                  notice='Source filings include quarterly and annual comparables; they are not a complete quarter-by-quarter scored history. Snapshots were collected retrospectively; publication time and recorded time must both be respected.')
    store.write('company/fundamentals_coverage', result)
    return result


def check(isin, *, at=None):
    from core.research import company_review as cr
    at=at or datetime.now(timezone.utc)
    record=store.read(key(isin),{})
    evidence=store.read('company/evidence',{'fundamentals':[],'articles':[]})
    snapshot=cr.latest_snapshot(evidence,isin,at)
    scored=cr.score(snapshot,at=at)
    checked=record.get('last_checked_at')
    known=bool(checked and datetime.fromisoformat(checked)<=at)
    return dict(isin=isin, **scored, last_checked_at=checked if known else None,
                last_pulled_at=(snapshot or {}).get('recorded_at'),
                next_quarter_end=next_quarter(snapshot['period_end']) if snapshot else None,
                latest_index_period=record.get('latest_index_period') if known else None,
                pull_status=record.get('pull_status','not_pulled') if known else 'not_checked_at_decision_time')


def audit(items):
    rows=[]
    at=datetime.now(timezone.utc)
    for item in items:
        try:
            record=store.read(key(item['isin']),{})
            status=validate(record['snapshot'],record['documents'],item,at) if record.get('snapshot') else dict(status='missing')
            rows.append(dict(symbol=item['symbol'],isin=item['isin'],**status))
        except Exception as exc:
            rows.append(dict(symbol=item['symbol'],isin=item['isin'],status='failed',reason=type(exc).__name__))
    result=dict(validated_at=at.isoformat(),stocks=rows,counts={s:sum(r['status']==s for r in rows) for s in ('passed','missing','failed')})
    store.write('company/fundamentals_validation',result)
    return result

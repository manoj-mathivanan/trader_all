"""Indian API observations and a pre-buy consensus gate; no trading side effects."""
from datetime import datetime, time as day_time, timedelta, timezone
from decimal import Decimal, InvalidOperation
import math
import threading
import time
from zoneinfo import ZoneInfo

import httpx


LABELS = {1: 'Strong Buy', 2: 'Buy', 3: 'Hold', 4: 'Sell', 5: 'Strong Sell'}


def count(value):
    if isinstance(value, bool):
        raise ValueError('Invalid analyst count.')
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ValueError('Invalid analyst count.') from None
    if not number.is_finite() or number < 0 or number != number.to_integral_value():
        raise ValueError('Invalid analyst count.')
    return int(number)


def consensus(payload):
    """Fail closed on missing coverage, malformed votes, or inconsistent totals."""
    if not isinstance(payload, dict) or not payload.get('companyName'):
        raise ValueError('Provider returned no company identity.')
    bar = payload.get('recosBar') or {}
    rows = payload.get('analystView') or []
    if bar.get('isDataPresent') is not True:
        return dict(status='no_coverage', company=payload['companyName'], analysts=0, buy_share_pct=None)
    if not isinstance(rows, list):
        raise ValueError('Unexpected analyst response shape.')
    votes, totals = {}, []
    for row in rows:
        code = count(row.get('ratingValue'))
        n = count(row.get('numberOfAnalystsLatest'))
        if code == 6 and row.get('ratingName') == 'Total':
            totals.append(n)
            continue
        if code not in LABELS or row.get('ratingName', '').strip().casefold() != LABELS[code].casefold() or code in votes:
            raise ValueError('Unknown, duplicate or inconsistent analyst rating.')
        votes[code] = n
    total = sum(votes.values())
    if not total or any(n != total for n in totals) or count(bar.get('noOfRecommendations')) != total:
        raise ValueError('Analyst count totals are inconsistent.')
    mean = sum(code*n for code, n in votes.items())/total
    reported = float(bar.get('meanValue'))
    if not math.isfinite(reported) or abs(mean-reported) > .011:
        raise ValueError('Analyst mean is inconsistent with votes.')
    positive = votes.get(1, 0)+votes.get(2, 0)
    return dict(status='available', company=payload['companyName'], analysts=total,
                positive_analysts=positive, buy_share_pct=positive/total*100,
                mean=mean, votes=votes)


class IndianAPIClient:
    """Serial requests, with at least 1.05 seconds AFTER each response before the next call."""
    def __init__(self, key, *, interval=1.05, transport=None, clock=time.monotonic, sleep=time.sleep):
        if interval < 1:
            raise ValueError('Indian API requires at most one request per second.')
        self.interval, self.clock, self.sleep = interval, clock, sleep
        self.ready = 0
        self.lock = threading.Lock()
        self.client = httpx.Client(base_url='https://stock.indianapi.in', timeout=30,
                                   headers={'X-API-Key': key, 'Accept': 'application/json'},
                                   transport=transport, follow_redirects=False)
        self.requests = 0

    def close(self):
        self.client.close()

    def stock(self, symbol):
        with self.lock:
            self.sleep(max(0, self.ready-self.clock()))
            requested_at = datetime.now(timezone.utc).isoformat()
            try:
                self.requests += 1
                response = self.client.get('/stock', params={'name': symbol})
                status = response.status_code
                if status != 200:
                    # Do not log request headers, raw exceptions or credentials.
                    raise ValueError('Indian API returned HTTP '+str(status)+'. Collection stopped; no automatic retries.')
                payload = response.json()
            finally:
                self.ready = self.clock()+self.interval
            observed_at = datetime.now(timezone.utc).isoformat()
            return dict(symbol=symbol, requested_at=requested_at, observed_at=observed_at,
                        endpoint='https://stock.indianapi.in/stock', http_status=status,
                        payload=payload)


class ConsensusGate:
    """Default is causal: a snapshot must have been observed before the entry open."""
    def __init__(self, observations, *, threshold_pct=75, allow_hindsight=False, max_age_days=7):
        if not 0 <= threshold_pct <= 100 or max_age_days < 0:
            raise ValueError('Invalid consensus filter settings.')
        self.observations = observations
        self.threshold_pct = threshold_pct
        self.allow_hindsight = allow_hindsight
        self.max_age_days = max_age_days

    def __call__(self, symbol, signal_date, entry_date):
        observation = self.observations.get(symbol)
        evidence = dict(threshold_pct=self.threshold_pct, signal_date=signal_date,
                        entry_date=entry_date, hindsight=self.allow_hindsight)
        if not observation:
            return False, dict(evidence, reason='analyst_snapshot_missing')
        if observation.get('identity_verified') is not True:
            return False, dict(evidence, reason='analyst_identity_unverified')
        try:
            observed = datetime.fromisoformat(observation['observed_at'])
            if observed.tzinfo is None:
                raise ValueError('Observation requires timezone.')
            opening = datetime.combine(datetime.fromisoformat(entry_date).date(), day_time(9, 15), ZoneInfo('Asia/Kolkata'))
            if not self.allow_hindsight:
                if observed > opening:
                    return False, dict(evidence, reason='analyst_snapshot_not_yet_available')
                if opening-observed > timedelta(days=self.max_age_days):
                    return False, dict(evidence, reason='analyst_snapshot_stale')
            value = consensus(observation['payload'])
        except (ValueError, KeyError, TypeError, AttributeError):
            return False, dict(evidence, reason='analyst_snapshot_invalid')
        evidence.update(value, observed_at=observation['observed_at'])
        if value['status'] != 'available':
            return False, dict(evidence, reason='analyst_no_coverage')
        # Compare integers to avoid rounded 74.995% passing a 75% threshold.
        passed = value['positive_analysts']*100 >= self.threshold_pct*value['analysts']
        return passed, dict(evidence, reason='analyst_pass' if passed else 'analyst_below_threshold')

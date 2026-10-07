"""Exact-row, sourced corrections of derived research inputs only."""
from datetime import date
import hashlib
import json
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Values(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)

    @model_validator(mode='after')
    def range(self):
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close) or self.low > self.high:
            raise ValueError('Repair contains invalid OHLCV.')
        return self


class Repair(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1)
    date: date
    expected: Values
    replacement: Values
    source: str = Field(pattern=r'^https://')
    source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    basis_source: str = Field(pattern=r'^https://')
    reason: str = Field(min_length=1)


def apply(bars, records):
    repairs = [Repair(**r).model_dump(mode='json') for r in records]
    if len({r['date'] for r in repairs}) != len(repairs) or len({r['id'] for r in repairs}) != len(repairs):
        raise ValueError('Duplicate candle repair dates or IDs.')
    by_date = {r['date']: r for r in repairs}
    rows, applied = [], []
    for bar in bars:
        repair = by_date.get(bar['date'])
        if repair is None:
            rows.append(bar)
            continue
        values = {k: bar[k] for k in repair['expected']}
        if values not in (repair['expected'], repair['replacement']):
            raise ValueError(f"Candle repair evidence no longer matches {bar['date']}; investigate provider revision before simulation.")
        rows.append({**bar, **repair['replacement']})
        applied.append(repair)
    return rows, applied


def reconcile(previous, current, last, *, relevant_from=None):
    """A changed derived input policy cannot silently resume a processed ledger."""
    before = [r for r in previous.get('candle_repairs', []) if r['date'] <= last and (relevant_from is None or r['date'] >= relevant_from)]
    after = [r for r in current.get('candle_repairs', []) if r['date'] <= last and (relevant_from is None or r['date'] >= relevant_from)]
    if before != after:
        raise ValueError('Derived candle repairs changed for processed history; paper cycle halted for reconciliation. Ledger unchanged.')


def checkpoint_identity(portfolio, reference):
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    return {'portfolio_id': portfolio['id'],
            'checkpoint_sha256': digest({k: portfolio.get(k) for k in ('ledger', 'config', 'fingerprints', 'cycles', 'start_session', 'universe_snapshot')}),
            'repair_policy_sha256': digest(reference.get('candle_repairs', {}))}


def reconciliation_matches(record, portfolio, reference):
    return (record.get('result') == 'identical_ledgers'
            and all(record.get(k) == v for k, v in checkpoint_identity(portfolio, reference).items()))

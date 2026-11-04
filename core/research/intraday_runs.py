"""Saved custom target experiments over the audited minute archive."""
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from core.research import identity, intraday_target, jobs, store

CATALOG = 'intraday_target_catalog'


class TargetRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    stock: str = Field(min_length=1, max_length=24)
    target_pct: float = Field(gt=0, lt=100, allow_inf_nan=False)
    entry_time: str = '09:30'
    direction: Literal['long', 'short'] = 'long'

    @field_validator('stock')
    @classmethod
    def normalize_stock(cls, value):
        value = value.strip().upper()
        if not re.fullmatch(r'[A-Z0-9&.\-]+', value):
            raise ValueError('Choose a stock from the audited list.')
        return value

    @field_validator('entry_time')
    @classmethod
    def entry_time_in_session(cls, value):
        return intraday_target.validate_entry_time(value)


def report_key(report_id):
    if not re.fullmatch(r'custom-[a-f0-9]{12}', report_id):
        raise ValueError('Invalid custom backtest ID.')
    return 'intraday_target_reports/'+report_id


def summaries():
    return store.read(CATALOG, [])


def execute(config, log, job_id, owner=None):
    report = intraday_target.build_report(**config, log=log)
    report.update(id='custom-'+job_id, custom=True, created_by=owner, config=config,
                  trade_count=len(report['days']), skipped_count=len(report['skipped']))
    summary = {k:v for k,v in report.items() if k not in ('days','curve','skipped','assumptions','fee_sources')}
    with store.LOCK:
        key = report_key(report['id'])
        if store.read(key) is not None:
            raise ValueError('This experiment is already saved; create a new backtest.')
        store.write(key, report)
        store.write(CATALOG, [summary]+summaries())
    log(f'Saved {report["trade_count"]} trades; net P&L {report["final_pnl"]:.2f}.')
    return {'report_id': report['id']}


def submit(value):
    if value.stock not in intraday_target.instruments():
        raise ValueError('Choose a stock from the audited list.')
    config, owner = value.model_dump(), identity.username()
    return jobs.submit('intraday_target', lambda log, job_id: execute(config, log, job_id, owner), config)

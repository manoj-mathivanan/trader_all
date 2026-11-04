"""Saved custom target experiments over the audited minute archive."""
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from core.research import identity, intraday_target, jobs, store

CATALOG = 'intraday_target_catalog'


class TargetRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    stock: str = Field(min_length=1, max_length=24)
    target_pct: float = Field(gt=0, lt=100, allow_inf_nan=False)
    entry_time: str = '09:30'
    direction: Literal['long', 'short'] = 'long'
    stop_loss_enabled: bool = False
    stop_loss_delay_minutes: int = Field(default=30, ge=0, le=359, strict=True)
    stop_loss_pct: float = Field(default=.2, gt=0, lt=100, allow_inf_nan=False)
    reverse_once_on_stop: bool = False

    @model_validator(mode='after')
    def stop_before_exit(self):
        intraday_target.stop_activation(self.entry_time, self.stop_loss_enabled, self.stop_loss_delay_minutes, self.stop_loss_pct)
        if self.reverse_once_on_stop and (not self.stop_loss_enabled or self.target_pct*2>=100):
            raise ValueError('Reversal requires a stop loss and an initial target below 50%.')
        return self

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
                  trade_count=report.get('trade_count',len(report['days'])), skipped_count=len(report['skipped']))
    summary = {k:v for k,v in report.items() if k not in ('days','trades','curve','skipped','assumptions','fee_sources')}
    with store.LOCK:
        key = report_key(report['id'])
        if store.read(key) is not None:
            raise ValueError('This experiment is already saved; create a new backtest.')
        store.write(key, report)
        store.write(CATALOG, [summary]+summaries())
    log(f'Saved {report["trade_count"]} trades across {len(report["days"])} days; {report.get("reversal_count",0)} reversals; {report.get("stop_loss_exits",report.get("stop_loss_days",0))} stop-loss exits; net P&L {report["final_pnl"]:.2f}.')
    return {'report_id': report['id']}


def submit(value):
    if value.stock not in intraday_target.instruments():
        raise ValueError('Choose a stock from the audited list.')
    config, owner = value.model_dump(), identity.username()
    title = f'Intraday backtest · {value.stock} · '+('Buy' if value.direction=='long' else 'Sell')
    if value.reverse_once_on_stop:
        title += ' · Reverse once'
    return jobs.submit(title, lambda log, job_id: execute(config, log, job_id, owner), config)

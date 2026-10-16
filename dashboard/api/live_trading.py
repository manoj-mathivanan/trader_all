"""Live trading routes; app authentication and origin boundary apply to this router."""
from datetime import date
from typing import Literal
from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field
from core.portfolio import live

router = APIRouter(prefix='/api/live')


@router.get('')
def state():
    return live.public_state()


@router.put('/config')
def config(value: live.LiveConfig):
    return live.save_config(value)


@router.put('/connection')
def connection(value: live.Connection):
    return live.save_connection(value)


@router.post('/refresh')
def refresh():
    with live.mutex('live_control', timeout=30), live.Broker() as broker:
        account = live.refresh_account(broker)
        live.reconcile(broker, live.ledger(), account['orders'])
    return live.public_state()


@router.get('/history')
def history(start: date, end: date, page: int = Query(1, ge=1, le=10000)):
    return live.history(start, end, page)


@router.post('/preview')
def preview():
    return live.preview()


class Start(BaseModel):
    model_config = ConfigDict(extra='forbid')
    acknowledge_real_orders: bool = False


@router.post('/start')
def start(value: Start):
    if not value.acknowledge_real_orders:
        raise ValueError('Acknowledge real-money automatic orders before starting.')
    return live.start()


@router.post('/stop')
def stop():
    return live.stop()


class Pause(BaseModel):
    paused: bool


@router.put('/pause')
def pause(value: Pause):
    return live.pause(value.paused)


class Resolve(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    intent_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    order_id: str = Field('', max_length=80, pattern=r'^[A-Za-z0-9_-]*$')
    confirmed_not_placed: bool = False
    confirmed_history_details: bool = False
    final_status: Literal['complete', 'cancelled', 'rejected'] = 'cancelled'
    filled_quantity: int = Field(0, ge=0)
    average_price: float = Field(0, ge=0)


@router.post('/resolve')
def resolve(value: Resolve):
    final_report = {'status': value.final_status, 'filled_quantity': value.filled_quantity,
                    'average_price': value.average_price} if value.confirmed_history_details else None
    return live.resolve_unknown(value.intent_id, value.order_id, value.confirmed_not_placed, final_report)

"""Explicit split/bonus contracts. Never infer a factor from a price gap."""
from copy import deepcopy
from datetime import date
from fractions import Fraction
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

VERSION = 'split-bonus-v1'


class Action(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, str_strip_whitespace=True)
    id: str = Field(min_length=1)
    kind: Literal['split', 'bonus']
    ex_date: date
    share_factor: float = Field(gt=0, le=1000)
    price_basis: Literal['raw', 'already_adjusted']
    volume_basis: Literal['raw', 'already_adjusted']
    verified: Literal[True]
    source: str = Field(min_length=1)
    basis_source: str = Field(min_length=1)

    @model_validator(mode='after')
    def matching_basis(self):
        if self.price_basis != self.volume_basis:
            raise ValueError('Mixed price/volume adjustment bases are not supported.')
        if self.kind == 'bonus' and self.share_factor <= 1:
            raise ValueError('A bonus share factor must exceed one.')
        return self


def attach(bars, records):
    if not bars or not records:
        return bars
    try:
        actions = [Action(**item).model_dump(mode='json') for item in records]
    except ValueError:
        raise ValueError('Corporate-action evidence is invalid or its price/volume basis is unverified.') from None
    if len({x['id'] for x in actions}) != len(actions) or len({x['ex_date'] for x in actions}) != len(actions):
        raise ValueError('Duplicate corporate actions; combine same-date share factors into one verified contract.')
    return [dict(bars[0], corporate_actions=sorted(actions, key=lambda x: x['ex_date'])), *bars[1:]]


def actions(bars):
    return bars[0].get('corporate_actions', []) if bars else []


def adjusted_bars(bars, through):
    """Signal units as of this date; future actions cannot change past predicates."""
    applicable = [x for x in actions(bars) if x['ex_date'] <= str(through)]
    if not any(x['price_basis'] == 'raw' or x['volume_basis'] == 'raw' for x in applicable):
        return bars
    result = []
    for bar in bars:
        row = dict(bar)
        for action in applicable:
            if bar['date'] < action['ex_date']:
                if action['price_basis'] == 'raw':
                    for field in ('open', 'high', 'low', 'close'):
                        row[field] /= action['share_factor']
                if action['volume_basis'] == 'raw':
                    row['volume'] *= action['share_factor']
        result.append(row)
    return result


def rebase_position(position, mark, action):
    """Physical shares change; cost basis, fees, cash and monetary initial risk do not."""
    result = deepcopy(position)
    result.setdefault('entry_fill', position['entry'])
    result.setdefault('entry_quantity', position['quantity'])
    factor = Fraction(str(action['share_factor']))
    quantity = factor * position['quantity']
    if quantity.denominator != 1:
        raise ValueError('Corporate action produces fractional shares; cash-in-lieu accounting is unsupported. Ledger unchanged.')
    result['quantity'] = int(quantity)
    for key in ('entry', 'stop', 'best_close'):
        result[key] /= float(factor)
    return result, mark / float(factor)

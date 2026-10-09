"""Reusable swing presets shared by research and paper configuration forms."""
import hashlib
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from core.research import store
from core.research.config import TradingConfig


class ScreenInput(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    name: str = Field(min_length=1, max_length=80)
    pattern: Literal['vcp', 'blue_sky', 'multiyear', 'ipo'] = Field('vcp')
    base_days: int = Field(25, ge=5, le=250)
    max_depth_pct: float = Field(30, gt=0, le=80)
    volume_multiple: float = Field(1.5, ge=0.1, le=10)
    sma_days: int = Field(50, ge=5, le=250)
    require_long_trend: bool = False
    require_rising_long_trend: bool = False
    min_rs_rating: float = Field(0, ge=0, le=100)
    min_turnover: float = Field(50000000, ge=0, le=1e12)
    vcp_window_days: int = Field(10, ge=3, le=60)
    vcp_volume_multiple: float = Field(0.8, gt=0, le=1)
    blue_sky_lookback_days: int = Field(5000, ge=50, le=5000)
    multiyear_base_days: int = Field(260, ge=252, le=2500)
    multiyear_max_depth_pct: float = Field(50, gt=0, le=90)
    ipo_max_age_days: int = Field(730, ge=1, le=3653)
    trading_defaults: TradingConfig | None = None
    minimum_warmup_sessions: int | None = Field(None, ge=50, le=2500)
    source_run_id: str | None = Field(None, pattern=r'^[0-9a-f]{12}(?:_[a-z0-9]+)?$')
    description: str = Field('', max_length=1500)

    @model_validator(mode='after')
    def consistent_defaults(self):
        if self.trading_defaults:
            if self.pattern != self.trading_defaults.pattern:
                raise ValueError('Saved strategy and trading defaults must use the same pattern.')
            for key in type(self).model_fields:
                if key in TradingConfig.model_fields and key != 'name':
                    value = getattr(self.trading_defaults,key)
                    if key in self.model_fields_set and getattr(self,key) != value:
                        raise ValueError('Conflicting saved strategy filter: '+key)
                    setattr(self,key,value)
            self.trading_defaults = self.trading_defaults.model_copy(update={'name':self.name})
        return self


def identity(name):
    return 'custom_'+hashlib.sha1(name.encode('utf-8')).hexdigest()[:10]


def available():
    # Bundled presets survive deployment to a separate paper state directory.
    bundled=[]
    directory=store.ROOT/'strategies/swing_patterns/presets'
    for path in sorted(directory.glob('*.json')):
        value=ScreenInput.model_validate(json.loads(path.read_text(encoding='utf-8')))
        bundled.append(dict(**value.model_dump(mode='json'),id=identity(value.name),bundled=True))
    saved=store.read('screens',[])
    return saved+[p for p in bundled if p['id'] not in {s['id'] for s in saved}]

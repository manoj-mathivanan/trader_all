"""Named five-indicator paper strategy: four entry conditions plus RS126 ranking."""
from typing import Literal
from pydantic import Field
from core.portfolio import four_indicator_paper
from core.research import store,four_indicator_swing as fs
from datetime import date

STRATEGY='five_indicator_swing'


class PaperConfig(four_indicator_paper.PaperConfig):
    name: str = Field('Five-indicator daily swing',min_length=1,max_length=80)
    rule_set: Literal['bollinger'] = Field('bollinger',title='Four-indicator entry conditions')
    candidate_ranking: Literal['rs_126'] = Field('rs_126',title='Fifth indicator: RS126 candidate ranking')
    slot_scale: Literal[1.0] = Field(1.0,title='Normal cash slots')


def save(config,settings,*,create=False,portfolio_id=None):
    return four_indicator_paper.save(config,settings,create=create,portfolio_id=portfolio_id,strategy_id=STRATEGY)


def cycle(log,job_id,*,ingest=True,portfolio_id=None):
    return four_indicator_paper.cycle(log,job_id,ingest=ingest,portfolio_id=portfolio_id,
                                     strategy_id=STRATEGY,config_model=PaperConfig,published_only=True)


def published_end(universe,end,symbols=None):
    """Wait for published daily data instead of freezing revisable minute aggregates."""
    if not universe or not universe.get('instruments'):
        raise ValueError('Refresh the stock universe before starting five-indicator paper.')
    benchmark=store.read('bars/NIFTY50',{})
    days=sorted(b['date'] for b in benchmark.get('bars',[]) if b['date']<=str(end)
                and b['date'] not in benchmark.get('provisional_daily',{}))
    if not days:raise ValueError('No published benchmark sessions are available yet.')
    candidate=days[-1]
    items=[i for i in universe['instruments'] if symbols is None or i['symbol'] in symbols]
    records=fs.read_many(['bars/'+i['isin'] for i in items])
    blocked=[]
    for record in records.values():
        if not record or not record.get('bars') or record['bars'][-1]['date']<candidate:continue
        blocked.extend(d for d in record.get('provisional_daily',{}) if d<=candidate)
    if blocked:days=[d for d in days if d<min(blocked)]
    if not days:raise ValueError('Stock daily candles are still provisional; retry after published data arrives.')
    return date.fromisoformat(days[-1])

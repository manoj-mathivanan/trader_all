"""Four indicators followed by a >=75% Buy/Strong Buy pre-entry filter."""
from typing import Literal
from pydantic import Field
from core.portfolio import four_indicator_paper
from core.research import indian_api
from core.research.analyst_consensus import ConsensusGate

STRATEGY = 'four_indicator_analyst'


class PaperConfig(four_indicator_paper.PaperConfig):
    name: str = Field('Four indicators + analyst consensus',min_length=1,max_length=80)
    rule_set: Literal['bollinger'] = 'bollinger'
    candidate_ranking: Literal['turnover'] = 'turnover'
    analyst_buy_threshold_pct: Literal[75] = Field(75,title='Minimum Buy + Strong Buy opinions (%)')
    slot_scale: Literal[1.0] = 1.0


def save(config,settings,*,create=False,portfolio_id=None):
    return four_indicator_paper.save(config,settings,create=create,portfolio_id=portfolio_id,strategy_id=STRATEGY)


def prepare_filter(frozen,portfolio,signals,log):
    items={item['symbol']:item for item in frozen['universe']['instruments']}
    # Collect completed-session setups for a future open; this collection cannot
    # retroactively authorize entries at an open before the observation time.
    end=max(rows[-1]['date'] for rows in frozen['datasets'].values())
    candidates=[symbol for symbol,rows in frozen['datasets'].items() if rows[-1]['date']==end
                and len(rows)>100 and all(c['passed'] for c in signals[symbol][-1]['checks'])]
    for symbol in sorted(candidates):indian_api.collect(items[symbol],log)
    log('Analyst snapshots checked for '+str(len(candidates))+' completed-session setups; past opens require prior observations.')
    def gate(symbol,signal_date,entry_date):
        observation=indian_api.at_open(symbol,entry_date)
        if observation:
            frozen.setdefault('analyst_observations',{}).setdefault(symbol,{})[observation['observed_at']]=observation
        return ConsensusGate({symbol:observation} if observation else {},threshold_pct=75)(symbol,signal_date,entry_date)
    return gate


def cycle(log,job_id,*,ingest=True,portfolio_id=None):
    return four_indicator_paper.cycle(log,job_id,ingest=ingest,portfolio_id=portfolio_id,
        strategy_id=STRATEGY,config_model=PaperConfig,published_only=True,entry_filter_factory=prepare_filter)

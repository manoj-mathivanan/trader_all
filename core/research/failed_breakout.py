"""Research-only opening-range failure reversal; completed-candle decisions."""
import math
from statistics import mean
from pydantic import Field, model_validator
from core.execution.paper import PaperBrokerAdapter
from core.research import intraday_data, scalping


class FailedBreakoutConfig(scalping.ScalpingConfig):
    name: str = Field('Opening-range failed breakout reversal', min_length=1, max_length=80)
    opening_minutes: int = Field(15, ge=5, le=60)
    failure_minutes: int = Field(5, ge=1, le=15)
    min_opening_relative_volume: float = Field(1.5, gt=0, le=20)
    min_activity_score: float = Field(60, ge=0, le=100)
    max_selected_stocks: int = Field(3, ge=1, le=20)
    min_reward_cost_ratio: float = Field(1.5, ge=1, le=10)
    min_net_reward_r: float = Field(0.5, ge=0, le=5)
    first_entry_time: str = Field('09:30', pattern=r'^\d{2}:\d{2}$')
    last_entry_time: str = Field('11:00', pattern=r'^\d{2}:\d{2}$')
    min_stop_pct: float = Field(0.1, gt=0, le=5)
    max_stop_pct: float = Field(1.0, gt=0, le=10)
    max_positions: int = Field(2, ge=1, le=20)
    max_trades_per_symbol: int = Field(1, ge=1, le=20)
    max_holding_minutes: int = Field(15, ge=1, le=120)

    @model_validator(mode='after')
    def opening_rules(self):
        h, m = map(int, self.first_entry_time.split(':'))
        if h*60+m < 9*60+15+self.opening_minutes:
            raise ValueError('Entries must follow the completed opening range.')
        if self.max_positions > self.max_selected_stocks:
            raise ValueError('Position limit cannot exceed selected stocks.')
        if self.max_trades_per_symbol != 1:
            raise ValueError('This declared experiment permits one trade per stock per day.')
        return self


def opening_context(sessions, candidate, day, cfg):
    last = 9*60+15+cfg.opening_minutes-1
    cutoff = f'{last//60:02d}:{last%60:02d}'
    opening = intraday_data.trading_bars(sessions[day], cutoff, 1)
    volumes = [sum(b['volume'] for b in intraday_data.trading_bars(sessions[d], cutoff, 1))
               for d in candidate['history']]
    if len(volumes) < 2 or mean(volumes) <= 0:
        raise ValueError('Opening relative volume needs at least two prior complete opening sessions.')
    volume = sum(b['volume'] for b in opening)
    rv = volume/mean(volumes)
    high, low = max(b['high'] for b in opening), min(b['low'] for b in opening)
    midpoint = (high+low)/2
    width_pct = (high-low)/midpoint*100
    # Fixed normalization across all cost scenarios: selection cannot improve simply because fees change.
    components = dict(relative_volume=40*min(1, rv/3), range_opportunity=40*min(1, width_pct/1.6),
                      liquidity=20*min(1, max(0, math.log10(max(1, candidate['turnover']/5e7))/2)))
    return dict(high=high, low=low, midpoint=midpoint, width_pct=width_pct,
                relative_volume=rv, score=sum(components.values()), components=components,
                known_at=opening[-1]['timestamp']+60000, history_sessions=len(volumes))


def select(plan, sessions, cfg):
    selected = {}
    for day, candidates in sorted(plan.items()):
        eligible = []
        for candidate in candidates:
            context = opening_context(sessions[candidate['symbol']], candidate, day, cfg)
            if context['relative_volume'] >= cfg.min_opening_relative_volume and context['score'] >= cfg.min_activity_score:
                eligible.append(dict(candidate, opening_context=context))
        selected[day] = sorted(eligible, key=lambda c: (-c['opening_context']['score'], -c['turnover'], c['symbol']))[:cfg.max_selected_stocks]
    return selected


def features(sessions, candidate, day, cfg):
    bars = intraday_data.trading_bars(sessions[day], cfg.square_off_time, 1)
    context = candidate['opening_context']
    return bars, [context]*len(bars)


def signal(bars, values, j, cfg):
    if j <= cfg.opening_minutes:
        return None
    context = values[j]
    b = bars[j]
    buffer = cfg.entry_buffer_bps/10000
    for side, sign in [('short', -1), ('long', 1)]:
        if cfg.direction not in ('both', side):
            continue
        bound = context['high'] if sign == -1 else context['low']
        # Prior close is outside; the current completed close returns inside with a reversal body.
        def outside(bar):
            return -sign*(bar['close']-bound*(1-sign*buffer)) > 0
        if not outside(bars[j-1]) or not context['low'] < b['close'] < context['high']:
            continue
        if sign*(b['close']-b['open']) <= 0 or sign*(b['close']-context['midpoint']) >= 0:
            continue
        start = j-1
        while start >= cfg.opening_minutes and outside(bars[start]):
            start -= 1
        start += 1
        if j-start > cfg.failure_minutes:
            continue
        observed = bars[start:j+1]
        stop = (max(p['high'] for p in observed) if sign == -1 else min(p['low'] for p in observed))*(1-sign*buffer)
        return dict(direction=side, sign=sign, trigger=bound, stop=stop,
                    indicators=dict(context, breakout_timestamp=bars[start]['timestamp'], failed_after_minutes=j-start))
    return None


def target(setup, fill, distance, cfg):
    return setup['indicators']['midpoint']


def entry_allowed(setup, raw, fill, target_price, unit_risk, cfg):
    sign = setup['sign']
    broker = PaperBrokerAdapter(cfg)
    exit_fill = broker.fill(target_price, 1, 'sell' if sign == 1 else 'buy')
    fee_rate = (cfg.buy_cost_bps if sign == 1 else cfg.sell_cost_bps)/10000
    entry_fee = fill*fee_rate
    gross_reward = sign*(target_price-raw)
    net_reward = sign*(exit_fill['price']-fill)-entry_fee-exit_fill['fees']
    costs = sign*(fill-raw)+exit_fill['slippage']+entry_fee+exit_fill['fees']
    return gross_reward > 0 and gross_reward >= costs*cfg.min_reward_cost_ratio and net_reward >= unit_risk*cfg.min_net_reward_r


def simulate(daily, cfg, sessions, plan):
    result = scalping.simulate(daily, cfg, sessions, plan, feature_provider=features,
                              signal_provider=signal, target_provider=target, entry_gate=entry_allowed)
    for trade in result['trades']:
        trade['reason'] = trade['reason'].replace('Pullback stop loss', 'Failed-breakout stop loss').replace('Gap through pullback stop', 'Gap through failed-breakout stop')
    result['strategy'] = 'opening_range_failed_breakout'
    result['selection_plan'] = plan
    result['config'] = cfg.model_dump(mode='json')
    return result

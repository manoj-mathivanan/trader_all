"""Fixed causal selection diagnostics; development hypotheses, no live settings."""
from collections import defaultdict
from statistics import mean

VARIANTS=('base','market_aligned','top10_turnover','early','long_only','short_only','market_top10')


def prior_liquidity_ranks(by_symbol):
    """Rank prior20-session average close*volume; ties use symbol, never returns."""
    days=defaultdict(list)
    for symbol,rows in by_symbol.items():
        if any(a['date']>=b['date'] for a,b in zip(rows,rows[1:])):raise ValueError('Daily dates must be ordered and unique.')
        for j in range(20,len(rows)):
            prior=rows[j-20:j]
            score=mean(b['close']*b['volume'] for b in prior)
            days[rows[j]['date']].append((symbol,score,rows[j-1]['date']))
    return {day:{symbol:dict(rank=rank,turnover=score,as_of=as_of)
                 for rank,(symbol,score,as_of) in enumerate(sorted(values,key=lambda x:(-x[1],x[0])),1)}
            for day,values in days.items()}


def flags(trade):
    aligned=trade.get('market_direction')==trade.get('direction',1)
    liquid=trade.get('liquidity_rank',999)<=10
    return dict(base=True,market_aligned=aligned,top10_turnover=liquid,
                early='09:45'<=trade['signal_time']<'10:30',
                long_only=trade.get('direction',1)==1,short_only=trade.get('direction',1)==-1,
                market_top10=aligned and liquid)


def time_bucket(trade):
    t=trade['signal_time']
    return '09:45-10:30' if t<'10:30' else '10:30-12:00' if t<'12:00' else '12:00-14:30'

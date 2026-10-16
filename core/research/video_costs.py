"""Matched-order cost sensitivity, not calibrated spread/queue estimates."""
from core.research.video_keltner import settle


def reprice(ledger,extra_bps=0,fee_multiplier=1):
    if extra_bps<0 or fee_multiplier<=0:raise ValueError('Invalid cost scenario.')
    # Same signal identities, quantities, stop/target orders and exit times.
    # Extra adverse entry cost on every trade; extra exit cost on market exits.
    return [settle(dict(t,entry=t['entry']+t['entry_raw']*t.get('direction',1)*extra_bps/10000),
                   t['quantity'],2+extra_bps,fee_multiplier) for t in ledger]


def break_even_extra_bps(ledger):
    """Maximum equal extra bps at entry/market exit; None if base already loses."""
    pnl=lambda b:sum(t['net_pnl'] for t in reprice(ledger,b))
    if not ledger or pnl(0)<=0:return None
    low,high=0,100
    if pnl(high)>0:raise ValueError('Break-even outside declared100bps bracket.')
    for _ in range(40):
        mid=(low+high)/2
        if pnl(mid)>0:low=mid
        else:high=mid
    return round((low+high)/2,4)

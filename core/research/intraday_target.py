"""One daily long at 09:30, target or manual 15:15 exit, compounded net of fees."""
from datetime import date
import hashlib
import json
from core.execution.zerodha import equity_charges, SOURCES
from core.research import intraday_data


def simulate(sessions, expected, *, start='2024-11-04', end='2026-11-03', capital=500000, direction='long'):
    if direction not in ('long', 'short'):
        raise ValueError('Direction must be long or short.')
    short = direction == 'short'
    initial = capital
    days, skipped = [], []
    digest = hashlib.sha256()
    for day in expected:
        record = sessions.get(day)
        if not record:
            raise ValueError(f'Missing session: {day}')
        bars = intraday_data.cached_bars(record, day, 1)
        from scripts.pull_nifty_minute_history import audit_session, expected_times
        audit = audit_session(day, bars)
        if audit['missing_minutes'] or audit['extra_minutes'] or audit['duplicate_minutes']:
            raise ValueError(f'Incomplete session: {day}')
        digest.update(json.dumps([day, bars], sort_keys=True, separators=(',', ':')).encode())
        if '09:30' not in expected_times(day):
            skipped.append(dict(date=day, reason='Special session has no 09:30 entry'))
            continue
        by_time = {b['time']: b for b in bars}
        if '15:15' not in by_time:
            raise ValueError(f'Missing exit candle: {day}')
        entry = by_time['09:30']['open']
        quantity = max(0, int(capital * 5 // entry))
        if not quantity:
            skipped.append(dict(date=day, reason='Insufficient capital for one share'))
            continue
        target = entry * (.995 if short else 1.005)
        hit = next((b for b in bars if '09:30' <= b['time'] < '15:15' and
                    (b['low'] <= target if short else b['high'] >= target)), None)
        # The 15:15 open can fill a resting target before the manual market exit.
        if hit:
            exit_price, exit_time = target, hit['time']
        elif (by_time['15:15']['open'] <= target if short else by_time['15:15']['open'] >= target):
            hit = by_time['15:15']
            exit_price, exit_time = target, '15:15'
        else:
            exit_price, exit_time = by_time['15:15']['open'], '15:15'
        buy = equity_charges(exit_price if short else entry, quantity, 'buy', day, intraday=True)
        sell = equity_charges(entry if short else exit_price, quantity, 'sell', day, intraday=True)
        fees = {k: buy[k] + sell[k] for k in buy if k != 'total'}
        charges = sum(fees.values())
        gross = (entry-exit_price if short else exit_price-entry)*quantity
        net = gross-charges
        opening = capital
        capital += net
        days.append(dict(date=day, entry_price=entry, target_price=target, exit_price=exit_price,
            entry_time='09:30', exit_time=exit_time, quantity=quantity,
            outcome='success' if hit else 'failure', gross_pnl=gross, charges=charges,
            fees=fees, net_pnl=net, opening_capital=opening, closing_capital=capital))
    gross = sum(d['gross_pnl'] for d in days)
    charges = sum(d['charges'] for d in days)
    return dict(id='hdfcbank-0930-'+('short-' if short else '')+'target05-2y', direction=direction, stock='HDFCBANK', stock_name='HDFC Bank Ltd.',
        strategy=('Sell at 09:30 IST; buy back at −0.5%' if short else 'Buy at 09:30 IST; sell at +0.5%')+', otherwise exit at 15:15 IST. Compound daily at 5× leverage.',
        start=start, end=end, starting_capital=initial, leverage=5, target_pct=.5,
        success_days=sum(d['outcome']=='success' for d in days),
        failure_days=sum(d['outcome']=='failure' for d in days),
        net_profitable_days=sum(d['net_pnl']>0 for d in days),
        total_gross_pnl=gross, total_charges=charges, final_pnl=gross-charges,
        final_capital=capital, return_pct=(capital/initial-1)*100, days=days, skipped=skipped,
        expected_sessions=len(expected), input_sha256=digest.hexdigest(), fee_sources=SOURCES,
        curve=[dict(date=start+' · initial', equity=initial)]+[
            dict(date=d['date'], equity=d['closing_capital']) for d in days],
        assumptions=[
            f'One {direction} trade per eligible day; whole shares = floor(opening capital × 5 / entry price). Net P&L compounds daily; no overnight positions.',
            'Entry is the 09:30 one-minute candle open; target fills at exactly entry × '+('0.995 when a subsequent or entry-minute low reaches it.' if short else '1.005 when a subsequent or entry-minute high reaches it.')+' Exit times identify a minute, not an exact tick.',
            'Target is active until the 15:15 manual exit. Target failure is independent of P&L: a failure can still close with a profit.',
            'Zerodha NSE resident-individual intraday fees use trade-date rates, including brokerage, STT, exchange, IPFT, SEBI, stamp duty and GST. Trade estimates exclude contract-note rounding.',
            'Assumes 5× margin is always available. No slippage, spread, tick-size rounding, market impact, margin liquidation, auto-square-off fees, AMC or income tax. Fees are deducted after exit.',
            'Uses observed minute OHLC, no overnight price comparisons or split-crossing positions. Special sessions without 09:30 are skipped explicitly.'
        ])


def build_report(direction='long'):
    from core.research import store
    from scripts.pull_nifty_minute_history import expected_calendar, persisted_sessions
    from scripts.backfill_nifty50_stock_minutes import valid_session
    start, end = date(2024, 11, 4), date(2026, 11, 3)
    sessions = persisted_sessions(start, end, 'INE040A01034')
    expected = expected_calendar(start, end)
    for day in expected:
        if not valid_session(day, sessions.get(day), 'INE040A01034'):
            raise ValueError(f'Unverified HDFCBANK minute data: {day}')
    report = simulate(sessions, expected, start=str(start), end=str(end), direction=direction)
    report.update(generated_at=store.now(), data_source='Upstox historical one-minute candles; shared PostgreSQL, local namespace')
    return report

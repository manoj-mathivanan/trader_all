"""Daily long/short at 09:30, target or 15:15 exit, compounded net of fees."""
from datetime import date
import hashlib
import json
import math
import re
from core.execution.zerodha import equity_charges, SOURCES
from core.research import intraday_data

STOCKS = {
    'HDFCBANK': dict(symbol='HDFCBANK', name='HDFC Bank Ltd.', isin='INE040A01034'),
    'RELIANCE': dict(symbol='RELIANCE', name='Reliance Industries Ltd.', isin='INE002A01018'),
}
ARCHIVE = 'market_archives/nifty50_stocks_1m/2024-10-01_2026-11-03'


def instruments():
    """Frozen stock identities matching the audited two-year minute archive."""
    from core.research import store
    saved = store.read(ARCHIVE+'/universe', {}).get('instruments', [])
    return {item['symbol']: item for item in saved} if saved else STOCKS.copy()


def validate_entry_time(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{2}:\d{2}', value):
        raise ValueError('Entry time must use HH:MM in IST.')
    hour, minute = map(int, value.split(':'))
    if hour > 23 or minute > 59 or not '09:15' <= value < '15:15':
        raise ValueError('Choose an entry time from 09:15 through 15:14 IST.')
    return value


def stop_activation(entry_time, enabled, delay_minutes, percentage):
    validate_entry_time(entry_time)
    if not isinstance(enabled, bool):
        raise ValueError('Stop loss must be enabled or disabled.')
    if not isinstance(delay_minutes, int) or isinstance(delay_minutes, bool) or not 0 <= delay_minutes <= 359:
        raise ValueError('Stop-loss delay must be a whole number from 0 to 359 minutes.')
    if not math.isfinite(percentage) or not 0 < percentage < 100:
        raise ValueError('Stop-loss percent must be between zero and 100.')
    if not enabled:
        return None
    hour, minute = map(int, entry_time.split(':'))
    activation = hour*60+minute+delay_minutes
    if activation >= 15*60+15:
        raise ValueError('The stop loss must activate before the 15:15 session exit.')
    return f'{activation//60:02d}:{activation%60:02d}'


def trade_exit(bars, entry_time, target, short, stop=None, active_from=None):
    """Respect known opening prints; resolve unknown intrabar ordering stop first."""
    for bar in bars:
        time = bar['time']
        if not entry_time <= time <= '15:15':
            continue
        target_open = bar['open'] <= target if short else bar['open'] >= target
        active = stop is not None and time >= active_from
        stop_open = active and (bar['open'] >= stop if short else bar['open'] <= stop)
        if target_open:
            return target, time, 'Target reached', False
        if stop_open:
            return bar['open'], time, 'Stop loss', False
        if time == '15:15':
            return bar['open'], time, 'Session exit', False
        target_hit = bar['low'] <= target if short else bar['high'] >= target
        stop_hit = active and (bar['high'] >= stop if short else bar['low'] <= stop)
        if stop_hit:
            return stop, time, 'Stop loss', bool(target_hit)
        if target_hit:
            return target, time, 'Target reached', False
    raise ValueError('No valid session exit candle.')


def simulate(sessions, expected, *, start='2024-11-04', end='2026-11-03', capital=500000, direction='long', target_pct=.5, stock='HDFCBANK', entry_time='09:30', instrument=None, stop_loss_enabled=False, stop_loss_delay_minutes=30, stop_loss_pct=.2):
    if instrument is None and stock not in STOCKS:
        raise ValueError('Unsupported backtest stock.')
    instrument = instrument or STOCKS[stock]
    if instrument.get('symbol') != stock or not instrument.get('isin'):
        raise ValueError('Stock identity does not match the requested instrument.')
    validate_entry_time(entry_time)
    active_from = stop_activation(entry_time, stop_loss_enabled, stop_loss_delay_minutes, stop_loss_pct)
    if direction not in ('long', 'short'):
        raise ValueError('Direction must be long or short.')
    short = direction == 'short'
    if not math.isfinite(target_pct) or not 0 < target_pct < 100:
        raise ValueError('Target percent must be between zero and 100.')
    factor = 1 + (-1 if short else 1) * target_pct / 100
    target_label = f'{target_pct:g}'
    initial = capital
    days, skipped = [], []
    digest = hashlib.sha256()
    for day in expected:
        record = sessions.get(day)
        if not record:
            raise ValueError(f'Missing session: {day}')
        bars = intraday_data.cached_bars(record, day, 1)
        from scripts.backfill_nifty50_stock_minutes import stock_audit, stock_times
        audit = stock_audit(day, bars, instrument['isin'])
        if audit['missing_minutes'] or audit['extra_minutes'] or audit['duplicate_minutes']:
            raise ValueError(f'Incomplete session: {day}')
        digest.update(json.dumps([day, bars], sort_keys=True, separators=(',', ':')).encode())
        if entry_time not in stock_times(day, instrument['isin']):
            skipped.append(dict(date=day, reason=f'Special session has no {entry_time} entry'))
            continue
        by_time = {b['time']: b for b in bars}
        if '15:15' not in by_time:
            skipped.append(dict(date=day, reason='Special session closes before the 15:15 exit'))
            continue
        entry = by_time[entry_time]['open']
        quantity = max(0, int(capital * 5 // entry))
        if not quantity:
            skipped.append(dict(date=day, reason='Insufficient capital for one share'))
            continue
        target = entry * factor
        stop = entry*(1+(1 if short else -1)*stop_loss_pct/100) if stop_loss_enabled else None
        exit_price, exit_time, exit_reason, ambiguous = trade_exit(bars, entry_time, target, short, stop, active_from)
        buy = equity_charges(exit_price if short else entry, quantity, 'buy', day, intraday=True)
        sell = equity_charges(entry if short else exit_price, quantity, 'sell', day, intraday=True)
        fees = {k: buy[k] + sell[k] for k in buy if k != 'total'}
        charges = sum(fees.values())
        gross = (entry-exit_price if short else exit_price-entry)*quantity
        net = gross-charges
        opening = capital
        capital += net
        days.append(dict(date=day, entry_price=entry, target_price=target, exit_price=exit_price,
            entry_time=entry_time, exit_time=exit_time, quantity=quantity,
            outcome='success' if exit_reason=='Target reached' else 'failure', gross_pnl=gross, charges=charges,
            stop_price=stop, stop_active_from=active_from, exit_reason=exit_reason, ambiguous_exit=ambiguous,
            fees=fees, net_pnl=net, opening_capital=opening, closing_capital=capital))
    gross = sum(d['gross_pnl'] for d in days)
    charges = sum(d['charges'] for d in days)
    return dict(id=stock.lower()+'-'+entry_time.replace(':','')+'-'+('short-' if short else '')+'target'+target_label.replace('.','')+'-2y', direction=direction, stock=stock, stock_name=instrument['name'], isin=instrument['isin'], entry_time=entry_time,
        strategy=(f'Sell at {entry_time} IST; buy back at −{target_label}%' if short else f'Buy at {entry_time} IST; sell at +{target_label}%')+(f'; stop loss {stop_loss_pct:g}% against entry after {stop_loss_delay_minutes} min' if stop_loss_enabled else '')+', otherwise exit at 15:15 IST. Compound daily at 5× leverage.',
        start=start, end=end, starting_capital=initial, leverage=5, target_pct=target_pct,
        stop_loss_enabled=stop_loss_enabled, stop_loss_delay_minutes=stop_loss_delay_minutes,
        stop_loss_pct=stop_loss_pct, stop_active_from=active_from,
        stop_loss_days=sum(d['exit_reason']=='Stop loss' for d in days),
        ambiguous_days=sum(d['ambiguous_exit'] for d in days),
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
            f'Entry is the {entry_time} one-minute candle open; target fills at exactly entry × {factor:g} when a subsequent or entry-minute '+('low' if short else 'high')+' reaches it. Exit times identify a minute, not an exact tick.',
            'Target is active until the 15:15 manual exit. Target failure is independent of P&L: a failure can still close with a profit.',
            'Zerodha NSE resident-individual intraday fees use trade-date rates, including brokerage, STT, exchange, IPFT, SEBI, stamp duty and GST. Trade estimates exclude contract-note rounding.',
            'Assumes 5× margin is always available. No slippage, spread, tick-size rounding, market impact, margin liquidation, auto-square-off fees, AMC or income tax. Fees are deducted after exit.',
            f'Uses observed minute OHLC, no overnight price comparisons or split-crossing positions. Special sessions without {entry_time} or a 15:15 exit are skipped explicitly.'
        ]+([f'Stop loss activates at {active_from} IST, {stop_loss_delay_minutes} minutes after entry, if the trade is still open. The fixed stop is {stop_loss_pct:g}% against entry: below a buy entry and above a sell entry. Earlier adverse moves do not trigger it.',
             'Once active, stop-loss checks continue each minute. If a minute opens beyond the stop, exit at that opening price. A stop can therefore lose more than the chosen percentage.',
             'Opening prints are checked before intrabar extremes. If both target and stop are touched within the same minute and their order is unknown, count the stop first; these trades are flagged. No intrabar extremes after 15:15 are used.'] if stop_loss_enabled else ['Delayed stop loss is disabled.']))


def build_report(direction='long', target_pct=.5, stock='HDFCBANK', entry_time='09:30', log=lambda message: None, stop_loss_enabled=False, stop_loss_delay_minutes=30, stop_loss_pct=.2):
    from core.research import store
    from scripts.pull_nifty_minute_history import expected_calendar, persisted_sessions
    from scripts.backfill_nifty50_stock_minutes import valid_session
    available = instruments()
    if stock not in available:
        raise ValueError('Unsupported backtest stock.')
    instrument = available[stock]
    validate_entry_time(entry_time)
    active_from = stop_activation(entry_time, stop_loss_enabled, stop_loss_delay_minutes, stop_loss_pct)
    start, end = date(2024, 11, 4), date(2026, 11, 3)
    log(f'{stock} {direction} · entry {entry_time} IST · target {target_pct:g}% · '+
        (f'stop {stop_loss_pct:g}% active from {active_from} IST ({stop_loss_delay_minutes} min delay).' if stop_loss_enabled else 'stop loss disabled.'))
    log(f'Loading audited one-minute history for {stock}.')
    sessions = persisted_sessions(start, end, instrument['isin'])
    expected = expected_calendar(start, end)
    for count, day in enumerate(expected, 1):
        if not valid_session(day, sessions.get(day), instrument['isin']):
            raise ValueError(f'Unverified {stock} minute data: {day}')
        if sessions[day].get('instrument', {}).get('isin') != instrument['isin']:
            raise ValueError(f'Incorrect instrument identity for {stock}: {day}')
        if count % 100 == 0:
            log(f'Validated {count}/{len(expected)} stock sessions.')
    report = simulate(sessions, expected, start=str(start), end=str(end), direction=direction, target_pct=target_pct, stock=stock, entry_time=entry_time, instrument=instrument, stop_loss_enabled=stop_loss_enabled, stop_loss_delay_minutes=stop_loss_delay_minutes, stop_loss_pct=stop_loss_pct)
    report.update(generated_at=store.now(), data_source='Upstox historical one-minute candles; shared PostgreSQL, local namespace')
    return report

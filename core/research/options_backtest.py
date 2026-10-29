"""Completed-bar signal audit and strict long-options replay for research.

Every fill uses the exact next-minute option open. Partial option universes and
missing marks produce explicit exclusions; unresolved exposure suppresses metrics.
"""
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
import hashlib
import gzip
import json
import math
from pathlib import Path

from core.research import options_history as history, options_strategy
from core.research.intraday_data import SPECIAL_SESSIONS

MINUTE = 60000


@dataclass(frozen=True)
class ReplayConfig:
    timeframe: int = 3
    premium_variant: str = 'fixed_250'
    capital: float = 100000
    brokerage_per_order: float = 30
    buy_charge_bps: float = 0
    sell_charge_bps: float = 0
    slippage_bps: float = 0
    fee_model: str = 'upstox_options'
    chain_policy: str = 'strict'

    def __post_init__(self):
        if self.timeframe not in (3, 5) or self.premium_variant not in ('fixed_250', 'underlying_1pct') or self.fee_model not in ('custom_bps', 'upstox_options'):
            raise ValueError('Unsupported timeframe or premium-selection variant.')
        if self.chain_policy not in ('strict', 'observed_traded'):
            raise ValueError('Unsupported chain coverage policy.')
        values = (self.capital, self.brokerage_per_order, self.buy_charge_bps, self.sell_charge_bps, self.slippage_bps)
        if not all(math.isfinite(v) for v in values) or self.capital <= 0 or min(values[1:]) < 0 or self.slippage_bps >= 10000:
            raise ValueError('Invalid capital or cost assumptions.')
        object.__setattr__(self, 'fee_model', 'upstox_options')
        object.__setattr__(self, 'brokerage_per_order', 30)


def transaction_fee(price, quantity, side, day, config):
    from core.research.options_costs import fees
    return fees(price, quantity, side, day)['total']


def read_evidence(directory, record):
    directory = Path(directory).resolve()
    path = (directory/record['file']).resolve()
    if path.parent != directory or not path.is_file():
        raise ValueError('Archive evidence must be a direct file in the bundle directory.')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != record['sha256']:
        raise ValueError(f'Archive checksum mismatch: {path.name}.')
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def load_underlying(directory):
    directory = Path(directory)
    manifest = json.loads((directory/'underlying-manifest.json').read_text(encoding='utf-8'))
    if manifest.get('status') != 'underlying_downloaded' or manifest.get('underlying_key') != history.UNDERLYING:
        raise ValueError('No completed NIFTY underlying archive.')
    start, end = date.fromisoformat(manifest['start']), date.fromisoformat(manifest['end'])
    raw_minutes, daily = [], None
    from core.research.upstox import validate_candles
    for record in manifest['files']:
        evidence = read_evidence(directory, record)
        candles = evidence['raw_response']['data']['candles']
        if record.get('interval') == 'day':
            if daily is not None:
                raise ValueError('Duplicate daily archive.')
            daily = validate_candles(candles, start-timedelta(days=7), end)
        else:
            raw_minutes.extend(candles)
    if daily is None:
        raise ValueError('Previous-session daily history is required.')
    minutes = history.normalize_candles(raw_minutes, start-timedelta(days=7), end)
    return manifest, minutes, daily


def load_option_sample(directory):
    """Validate downloaded contract identities and every candle-file checksum."""
    directory = Path(directory)
    research = directory/'research-manifest.json'
    if research.exists():
        manifest = json.loads(research.read_text(encoding='utf-8'))
        if manifest.get('status') not in ('research_downloaded', 'research_downloaded_with_warnings') or manifest.get('underlying_key') != history.UNDERLYING:
            raise ValueError('Research options download is incomplete or has a wrong underlying.')
        catalogs = {r['expiry']: history.validate_contracts(read_evidence(directory,r),r['expiry']) for r in manifest['catalogs']}
        identities = {c['instrument_key']:c for catalog in catalogs.values() for c in catalog}
        option_bars = {}
        for record in manifest['files']:
            item = record['instrument']
            key = item['instrument_key']
            if key in option_bars or identities.get(key) != item:
                raise ValueError('Duplicate or inconsistent archived option identity.')
            evidence = read_evidence(directory, record)
            bars = history.normalize_candles(evidence['raw_response']['data']['candles'],
                date.fromisoformat(record['start']), date.fromisoformat(record['end']))
            option_bars[key] = {b['timestamp']:b for b in bars}
        return option_bars, catalogs, manifest['discovered_expiries']
    path = directory/'manifest.json'
    if not path.exists():
        raise ValueError('No option-candle sample is available. Expired-options access is required.')
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if manifest.get('status') not in ('sample_downloaded', 'sample_downloaded_with_warnings'):
        raise ValueError('Option download has not completed.')
    if manifest.get('underlying_key') != history.UNDERLYING or 'catalog_evidence' not in manifest:
        raise ValueError('Missing verified NIFTY contract-catalog evidence.')
    expiry = manifest['expiry']
    catalog = history.validate_contracts(read_evidence(directory, manifest['catalog_evidence']), expiry)
    by_key = {c['instrument_key']: c for c in catalog}
    option_bars = {}
    for record in manifest['files']:
        item = record.get('instrument')
        if item is None:
            continue
        key = item['instrument_key']
        if key in option_bars or by_key.get(key) != item:
            raise ValueError('Duplicate or inconsistent archived option identity.')
        evidence = read_evidence(directory, record)
        bars = history.normalize_candles(evidence['raw_response']['data']['candles'],
            date.fromisoformat(manifest['start']), date.fromisoformat(manifest['end']))
        option_bars[key] = {b['timestamp']: b for b in bars}
    expiries = manifest.get('discovered_expiries', [])
    if expiry not in expiries:
        raise ValueError('Option expiry is absent from discovery evidence.')
    return option_bars, {expiry: catalog}, expiries


def prepare_signals(minutes, daily, *, start, end, timeframe=3):
    """Reset indicator warmup after bad sessions instead of bridging missing data."""
    if timeframe not in (3, 5) or start > end:
        raise ValueError('Invalid signal-audit range or timeframe.')
    by_day = {}
    seen = set()
    for bar in minutes:
        if bar['timestamp'] in seen:
            raise ValueError('Duplicate underlying timestamp.')
        seen.add(bar['timestamp'])
        instant = datetime.fromtimestamp(bar['timestamp']/1000, history.IST)
        if instant.date().isoformat() != bar['date'] or instant.strftime('%H:%M') != bar['time']:
            raise ValueError('Underlying timestamp identity mismatch.')
        by_day.setdefault(bar['date'], []).append(bar)
    days = sorted(daily, key=lambda b: b['date'])
    if len({b['date'] for b in days}) != len(days):
        raise ValueError('Duplicate daily session.')
    daily_dates = {b['date'] for b in days}
    excluded, events, segment, previous = [], [], [], {}
    for extra in sorted(set(by_day)-daily_dates):
        if str(start) <= extra <= str(end):
            excluded.append(dict(date=extra, reason='Minute session missing from daily history.'))
    for index, day in enumerate(days):
        day_key = day['date']
        day_date = date.fromisoformat(day_key)
        if day_date > end:
            continue
        anchor = datetime.combine(day_date, datetime.min.time(), history.IST).replace(hour=9, minute=15)
        expected = [int((anchor+timedelta(minutes=i)).timestamp()*1000) for i in range(375)]
        observed = sorted(by_day.get(day_key, []), key=lambda b: b['timestamp'])
        reason = None
        if day_key in SPECIAL_SESSIONS or day_date.weekday() >= 5:
            reason = 'Special/weekend session excluded pending calendar verification.'
        elif [b['timestamp'] for b in observed] != expected:
            reason = 'Incomplete regular session: require all 375 minute candles.'
        elif any(abs(day[k]-value) > max(.1, abs(value)*.00001) for k, value in (
                ('open', observed[0]['open']), ('high', max(b['high'] for b in observed)),
                ('low', min(b['low'] for b in observed)))):
            # Official daily close can be weighted differently from the last
            # minute close. It is still the prior close used by daily pivots.
            reason = 'Daily and minute OHLC range disagree.'
        if reason:
            segment = []
            if start <= day_date <= end:
                excluded.append(dict(date=day_key, reason=reason, observed_minutes=len(observed)))
            continue
        if index:
            previous[day_key] = days[index-1]
        offset = len(segment)
        for i in range(0, 375, timeframe):
            chunk = observed[i:i+timeframe]
            segment.append(dict(date=day_key, timestamp=chunk[0]['timestamp'], time=chunk[0]['time'],
                open=chunk[0]['open'], high=max(b['high'] for b in chunk), low=min(b['low'] for b in chunk),
                close=chunk[-1]['close'], volume=sum(b['volume'] for b in chunk)))
        calculated = options_strategy.signals(segment, previous)
        if start <= day_date <= end:
            for bar, signal in zip(segment[offset:], calculated[offset:]):
                close_stamp = bar['timestamp']+timeframe*MINUTE
                instant = datetime.fromtimestamp(close_stamp/1000, history.IST)
                events.append(dict(**signal, timestamp=close_stamp, date=day_key,
                    time=instant.strftime('%H:%M'), underlying_close=bar['close'],
                    entry_window='09:30' <= instant.strftime('%H:%M') < '15:00'))
    return dict(events=events, excluded_sessions=excluded, timeframe_minutes=timeframe,
                session_count=len({e['date'] for e in events}),
                call_signal_bars=sum(e['ready'] and e['call'] and e['entry_window'] for e in events),
                put_signal_bars=sum(e['ready'] and e['put'] and e['entry_window'] for e in events))


def choose_contract(catalogs, option_bars, expiries, event, direction, variant, chain_policy='strict'):
    """Strict chain coverage: a missing candidate cannot silently change ranking."""
    eligible = sorted(e for e in expiries if e >= event['date'])
    if not eligible or eligible[0] not in catalogs:
        return None, 'Nearest expiry catalog unavailable.'
    expiry = eligible[0]
    catalog = history.validate_contracts(catalogs[expiry], expiry)
    kind = 'CE' if direction == 'call' else 'PE'
    candidates = [c for c in catalog if c['instrument_type'] == kind]
    if not candidates:
        return None, 'No contracts in the required direction.'
    target = 250 if variant == 'fixed_250' else .01*event['underlying_close']
    ranked = []
    for contract in candidates:
        candle = option_bars.get(contract['instrument_key'], {}).get(event['timestamp']-MINUTE)
        if candle is None:
            if chain_policy == 'strict':
                return None, 'Incomplete candidate-chain candles at signal time.'
            continue
        if candle['volume'] > 0:
            ranked.append((abs(candle['close']-target), contract['strike_price'], contract['instrument_key'], contract))
    if not ranked:
        return None, 'No traded candidate at signal time.'
    return min(ranked, key=lambda x: x[:3])[-1], None


def selection_coverage(catalogs, option_bars, expiries, event, side):
    eligible = sorted(e for e in expiries if e >= event['date'])
    catalog = catalogs.get(eligible[0], []) if eligible else []
    candidates = [c for c in catalog if c['instrument_type'] == ('CE' if side == 'call' else 'PE')]
    observed = [option_bars.get(c['instrument_key'], {}).get(event['timestamp']-MINUTE) for c in candidates]
    return dict(timestamp=event['timestamp'], direction=side, catalog_candidates=len(candidates),
                missing_candidate_minutes=sum(b is None for b in observed),
                traded_candidates=sum(b is not None and b['volume'] > 0 for b in observed))


def replay(audit, option_bars, catalogs, expiries, config):
    """Replay a caller-audited catalog/price set; no fabricated fills or expiry rolls.

    option_bars maps key -> timestamp -> normalized candle. Costs are illustrative
    input assumptions and are not a verified historical statutory fee schedule.
    """
    if audit.get('timeframe_minutes', config.timeframe) != config.timeframe:
        raise ValueError('Replay timeframe differs from its underlying signal audit.')
    cash = config.capital
    trades, skips, errors, curve, coverage = [], [], [], [], []
    armed = dict(call=True, put=True)
    position = None
    events = {e['timestamp']: e for e in audit['events']}
    if len(events) != len(audit['events']):
        raise ValueError('Duplicate signal event timestamp.')
    times = set(events)
    for day in {e['date'] for e in audit['events']}:
        instant = datetime.fromisoformat(day+'T15:20:00+05:30')
        times.add(int(instant.timestamp()*1000))
    for stamp in sorted(times):
        instant = datetime.fromtimestamp(stamp/1000, history.IST)
        event = events.get(stamp)
        clock = instant.strftime('%H:%M')
        if event and event['ready']:
            for side in armed:
                if not event[side]:
                    armed[side] = True
        exit_reason = None
        if position:
            if position['entry_date'] != instant.date().isoformat():
                errors.append('Position crossed a session without a valid scheduled exit.')
                break
            if clock == '15:20':
                exit_reason = 'scheduled_intraday_exit'
            elif event and event['ready'] and event['exit_'+position['direction']]:
                exit_reason = 'supertrend_close_reversal'
        if exit_reason:
            bar = option_bars.get(position['key'], {}).get(stamp)
            if not bar or bar['volume'] <= 0:
                errors.append('Exact exit minute missing or has zero volume; position unresolved.')
                break
            fill = bar['open']*(1-config.slippage_bps/10000)
            gross = fill*position['quantity']
            fee = transaction_fee(fill, position['quantity'], 'sell', instant.date(), config)
            cash += gross-fee
            trades.append(dict(position, exit_timestamp=stamp, exit=fill, exit_fee=fee, reason=exit_reason,
                pnl=gross-fee-position['entry_notional']-position['entry_fee']))
            armed[position['direction']] = False
            position = None
            curve.append(dict(timestamp=stamp, cash=cash, equity=cash))
            continue  # No same-minute reversal/re-entry after an exit.
        if position or not event or not event['ready'] or not event['entry_window']:
            continue
        side = 'call' if event['call'] else 'put' if event['put'] else None
        if side is None or not armed[side]:
            continue
        coverage.append(selection_coverage(catalogs, option_bars, expiries, event, side))
        contract, reason = choose_contract(catalogs, option_bars, expiries, event, side, config.premium_variant, config.chain_policy)
        if reason:
            skips.append(dict(timestamp=stamp, direction=side, reason=reason))
            continue
        key = contract['instrument_key']
        bar = option_bars.get(key, {}).get(stamp)
        if not bar or bar['volume'] <= 0:
            skips.append(dict(timestamp=stamp, direction=side, reason='Exact entry minute missing or has zero volume.'))
            continue
        fill = bar['open']*(1+config.slippage_bps/10000)
        quantity = int(contract['lot_size'])
        notional = fill*quantity
        fee = transaction_fee(fill, quantity, 'buy', instant.date(), config)
        if notional+fee > cash:
            skips.append(dict(timestamp=stamp, direction=side, reason='Insufficient cash for one historical lot and fees.'))
            continue
        position = dict(key=key, direction=side, expiry=contract['expiry'], strike=contract['strike_price'],
            quantity=quantity, entry_date=event['date'], entry_timestamp=stamp, entry=fill,
            signal_timestamp=stamp, selection_timestamp=stamp-MINUTE, entry_notional=notional, entry_fee=fee)
        cash -= notional+fee
    if position and not errors:
        errors.append('Position unresolved at end of input; no terminal fill invented.')
    # Only full-chain coverage permits aggregation. Daily exclusions also invalidate
    # the nominal date-range performance, even if the remaining trades are known.
    resolved = not errors and position is None
    valid = resolved and not skips and not audit['excluded_sessions'] and not any(r['missing_candidate_minutes'] for r in coverage)
    status = 'replay_complete' if valid else ('diagnostic_replay_complete' if resolved and not skips and not audit['excluded_sessions'] and config.chain_policy == 'observed_traded' else 'incomplete_inputs')
    return dict(status=status, config=asdict(config), selection_coverage=coverage,
        costs_verified=False, limitations=['Upstox Plus brokerage is applied to every replay date with date-dependent NSE taxes; contract-note rounding, exercise and assignment are excluded.',
                                          'Minute OHLC lacks bid/ask spread and cannot establish executable liquidity.',
                                          'No intratrade mark-to-market drawdown is calculated.',
                                          'Observed-traded policy omits unavailable candidate prices; its results are diagnostic only.'],
        trades=trades, skipped_entries=skips, errors=errors, unresolved_position=position,
        diagnostic_summary=(dict(completed_trades=len(trades), net_pnl_completed_trades=sum(t['pnl'] for t in trades),
            total_fees=sum(t['entry_fee']+t['exit_fee'] for t in trades),
            winning_trades=sum(t['pnl']>0 for t in trades),
            worst_trade_pnl=min((t['pnl'] for t in trades), default=0),
            pnl_without_largest_two_trades=sum(sorted(t['pnl'] for t in trades)[:-2])) if resolved else None),
        realized_cash_curve=curve, performance_summary=(dict(trade_count=len(trades),
            net_realized_pnl=sum(t['pnl'] for t in trades), final_cash=cash) if valid else None))

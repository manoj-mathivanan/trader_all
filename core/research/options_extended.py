"""Continuous-cash period comparisons over checksum-verified monthly archives."""
from datetime import date
import hashlib
from html import escape
import json
from pathlib import Path
import sqlite3

from core.research import options_backtest as bt, options_history as history


class MinutePrices:
    def __init__(self, connection, key):
        self.connection, self.key = connection, key

    def get(self, timestamp, default=None):
        row = self.connection.execute('SELECT open,close,volume FROM prices WHERE instrument=? AND timestamp=?',
                                      (self.key,timestamp)).fetchone()
        return dict(zip(('open','close','volume'),row)) if row else default


class DiskPrices:
    def __init__(self, connection):
        self.connection=connection

    def get(self, key, default=None):
        return MinutePrices(self.connection,key)


def merge_unique(target, values, key):
    for value in values:
        identity=value[key]
        if identity in target and target[identity] != value:
            raise ValueError(f'Conflicting archived observations for {identity}.')
        target[identity]=value


def compare_period(root, name, months, start, end):
    """Replay one continuous account per scenario; monthly cash never resets."""
    path=root/f'{name}-prices.sqlite3'
    # This is a disposable index of archived source data, not application storage.
    if path.exists():
        path.unlink()
    connection=sqlite3.connect(path)
    connection.execute('CREATE TABLE prices(instrument TEXT,timestamp INTEGER,open REAL,close REAL,volume REAL,PRIMARY KEY(instrument,timestamp)) WITHOUT ROWID')
    minute_map,daily_map,catalogs={},{},{}
    source_records=[]
    try:
        for month in months:
            directory=root/month
            underlying,minutes,daily=bt.load_underlying(directory)
            merge_unique(minute_map,minutes,'timestamp')
            merge_unique(daily_map,daily,'date')
            manifest=json.loads((directory/'research-manifest.json').read_text())
            if manifest['status'] != 'research_downloaded' or manifest['failures']:
                raise ValueError(f'{month} options archive is incomplete.')
            for record in manifest['catalogs']:
                contracts=history.validate_contracts(bt.read_evidence(directory,record),record['expiry'])
                if record['expiry'] in catalogs and {c['instrument_key']:c for c in catalogs[record['expiry']]} != {c['instrument_key']:c for c in contracts}:
                    raise ValueError('Contract catalog differs between monthly archives.')
                catalogs[record['expiry']]=contracts
            for record in manifest['files']:
                evidence=bt.read_evidence(directory,record)
                bars=history.normalize_candles(evidence['raw_response']['data']['candles'],
                    date.fromisoformat(record['start']),date.fromisoformat(record['end']))
                connection.executemany('INSERT INTO prices VALUES(?,?,?,?,?)',
                    ((record['instrument']['instrument_key'],b['timestamp'],b['open'],b['close'],b['volume']) for b in bars))
            connection.commit()
            source_records.extend(dict(month=month,file=file,sha256=hashlib.sha256((directory/file).read_bytes()).hexdigest())
                                  for file in ('underlying-manifest.json','research-manifest.json'))
        connection.execute('PRAGMA query_only=ON')
        rows=connection.execute('SELECT COUNT(*) FROM prices').fetchone()[0]
        options=DiskPrices(connection)
        results={}
        for timeframe in (3,5):
            audit=bt.prepare_signals(sorted(minute_map.values(),key=lambda b:b['timestamp']),
                sorted(daily_map.values(),key=lambda b:b['date']),start=start,end=end,timeframe=timeframe)
            for variant in ('fixed_250','underlying_1pct'):
                for scenario,overrides in (
                    ('strict_public_10bps',dict(chain_policy='strict',fee_model='upstox_options',brokerage_per_order=30,slippage_bps=10)),
                    ('observed_public_10bps',dict(chain_policy='observed_traded',fee_model='upstox_options',brokerage_per_order=30,slippage_bps=10)),
                    ('observed_public_50bps',dict(chain_policy='observed_traded',fee_model='upstox_options',brokerage_per_order=30,slippage_bps=50))):
                    key=f'{timeframe}m_{variant}_{scenario}'
                    results[key]=bt.replay(audit,options,catalogs,sorted(catalogs),
                        bt.ReplayConfig(timeframe=timeframe,premium_variant=variant,**overrides))
        return dict(period=name,start=str(start),end=str(end),initial_capital_per_scenario=100000,
                    monthly_cash_reset=False,indexed_candles=rows,inputs=source_records,replays=results)
    finally:
        connection.close()


def aggregate(root):
    root=Path(root)
    plan=json.loads((root/'frozen-plan.json').read_text())
    reports=[]
    for name,months in [('development',[f'2026-{m:02d}' for m in range(4,8)]),
                        ('comparison',['2026-08','2026-09'])]:
        bounds=plan[name]
        result=verified_period_cache(root,name,months,bounds,plan['source_hashes'])
        if result is None:
            result=compare_period(root,name,months,*map(date.fromisoformat,bounds))
            result['price_index_sha256']=hashlib.sha256((root/f'{name}-prices.sqlite3').read_bytes()).hexdigest()
            result['strategy_source_hashes']=plan['source_hashes']
        history.save_json(root/f'{name}-results.json',result)
        reports.append(result)
    report=dict(status='diagnostic_extended_research_complete',frozen_plan=plan,periods=reports,
        limitations=['Retrospective comparison only; not a prospective trading validation.',
                     'Each period starts with INR 100000 and carries cash continuously across its months.',
                     'Observed-traded results exclude unavailable candidate prices and remain diagnostic.',
                     'No intratrade drawdown or bid/ask execution validation.',
                     'Public fee hypothesis does not reconstruct the account historical tariff.'])
    history.save_json(root/'extended-results.json',report)
    html='<!doctype html><meta charset="utf-8"><title>Extended NIFTY options study</title><style>body{font:15px system-ui;margin:32px;color:#172033}td,th{padding:10px;border:1px solid #ccd3df}table{border-collapse:collapse}th{background:#edf2f7}</style><h1>April–September 2026: frozen-rule options study</h1><p><strong>Diagnostic results only. Missing chain observations prevent validated strategy returns.</strong></p>'
    html+='<p>'+escape('; '.join(report['limitations']))+'</p>'
    for period in reports:
        html+='<h2>'+escape(period['period'])+': '+period['start']+' to '+period['end']+'</h2><table><tr><th>Experiment</th><th>Status</th><th>Closed trades</th><th>Net P&amp;L (INR)</th><th>Worst trade (INR)</th><th>Without two largest winners (INR)</th></tr>'
        for key,value in period['replays'].items():
            stats=value['diagnostic_summary'] or {}
            cells=[key,value['status'],len(value['trades'])]+[stats.get(k) for k in
                ('net_pnl_completed_trades','worst_trade_pnl','pnl_without_largest_two_trades')]
            html+='<tr>'+''.join('<td>'+escape(f'{v:,.2f}' if isinstance(v,float) else str(v))+'</td>' for v in cells)+'</tr>'
        html+='</table>'
    (root/'extended-report.html').write_text(html,encoding='utf-8')
    return report


def verified_period_cache(root,name,months,bounds,strategy_hashes):
    """Reuse a completed period only with matching rules, inputs and price index."""
    try:
        result=json.loads((root/f'{name}-results.json').read_text())
        if result['period']!=name or [result['start'],result['end']]!=bounds or result.get('strategy_source_hashes')!=strategy_hashes:
            return None
        required={(month,file) for month in months for file in ('underlying-manifest.json','research-manifest.json')}
        if {(r['month'],r['file']) for r in result['inputs']}!=required:
            return None
        if any(hashlib.sha256((root/r['month']/r['file']).read_bytes()).hexdigest()!=r['sha256'] for r in result['inputs']):
            return None
        if hashlib.sha256((root/f'{name}-prices.sqlite3').read_bytes()).hexdigest()!=result['price_index_sha256']:
            return None
        return result
    except (OSError,KeyError,ValueError):
        return None

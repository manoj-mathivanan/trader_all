"""Read-only post-study diagnosis; does not tune rules or overwrite replays."""
import csv
from datetime import date, datetime, timezone
import hashlib
from html import escape
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research.options_costs import fees
from core.research.options_history import IST

PRIMARY = '3m_fixed_250_observed_public_10bps'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def drawdown(values):
    peak = values[0]
    worst, pct = 0., 0.
    for value in values:
        peak = max(peak, value)
        worst = max(worst, peak-value)
        pct = max(pct, (peak-value)/peak*100)
    return dict(rupees=worst, percent=pct)


def stats(trades):
    pnl = [t['pnl'] for t in trades]
    wins, losses = [p for p in pnl if p > 0], [p for p in pnl if p < 0]
    return dict(trades=len(pnl), net_pnl=sum(pnl), winning_trades=len(wins),
                average_win=sum(wins)/len(wins) if wins else None,
                average_loss=sum(losses)/len(losses) if losses else None,
                profit_factor=sum(wins)/-sum(losses) if losses else None,
                without_top_two=sum(sorted(pnl)[:-2]))


def group(trades, key):
    return {str(value): stats([t for t in trades if t[key] == value])
            for value in sorted({t[key] for t in trades})}


def trade_marks(trade, rows, slippage):
    """Rows span entry minute through minute before the exit open (exclusive)."""
    expected = (trade['exit_timestamp']-trade['entry_timestamp'])//60000
    marks = []
    for stamp, close, volume in rows:
        if volume <= 0:
            continue
        fill = close*(1-slippage/10000)
        day = datetime.fromtimestamp(stamp/1000, IST).date()
        pnl = (fill-trade['entry'])*trade['quantity']-trade['entry_fee']-fees(
            fill, trade['quantity'], 'sell', day)['total']
        marks.append((stamp+60000, pnl))
    values = [p for _, p in marks]+[trade['pnl']]
    return dict(expected_minutes=expected, observed_traded_minutes=len(marks),
                missing_or_zero_volume_minutes=expected-len(marks),
                adverse_excursion_net=min(0, *values), favorable_excursion_net=max(0, *values),
                peak_profit_given_back=max(0, *values)-trade['pnl']), marks


def analyse(root):
    output = root/'risk-diagnosis-v1'
    output.mkdir(exist_ok=True)
    report = dict(created_at=datetime.now(timezone.utc).isoformat(), periods={},
        methodology=[
            'Original saved fills and rules retained. Updated shared fee code checked against all saved scenarios.',
            'Primary risk analysis: 3-minute fixed INR250 observed-traded scenario, one historical lot.',
            'Minute closes from entry minute through the minute before exit; exit uses saved next-minute open.',
            'Liquidation marks deduct entry fee, estimated exit fee and scenario sell slippage. Excursions include terminal P&L.',
            'Drawdown uses initial INR100000 and chronological marked equity; each period starts independently.',
            'Missing or zero-volume minutes are not filled forward. Observed drawdown is a lower bound when marks are absent.',
            'Minute-close excursions omit intraminute extremes. No bid/ask liquidity verification.',
            'Missing candidate prices cannot establish whether another contract was closer to target.',
            'Premium changes cannot be attributed to theta without Greeks/IV and underlying attribution.',
            'All breakdowns are retrospective diagnostics, not evidence for selecting profitable filters.'],
        provenance={'current_source_hashes': {str(p): digest(p) for p in map(Path, [
            'core/research/options_backtest.py', 'core/research/options_costs.py',
            'core/execution/upstox.py', 'scripts/analyse_options_risk.py'])}},
        fee_checks=0, fee_mismatches=[])
    exported=[]
    for name in ('development', 'comparison'):
        source=root/f'{name}-results.json'
        original=json.loads(source.read_text())
        db=root/f'{name}-prices.sqlite3'
        if digest(db) != original['price_index_sha256']:
            raise ValueError('Price index checksum mismatch: '+name)
        for scenario, replay in original['replays'].items():
            for t in replay['trades']:
                for side in ('entry','exit'):
                    day=datetime.fromtimestamp(t[side+'_timestamp']/1000,IST).date()
                    actual=fees(t[side],t['quantity'],'buy' if side=='entry' else 'sell',day)['total']
                    report['fee_checks']+=1
                    if abs(actual-t[side+'_fee'])>1e-8:
                        report['fee_mismatches'].append(dict(period=name, scenario=scenario,
                            key=t['key'],side=side,saved=t[side+'_fee'],current=actual))
        replay=original['replays'][PRIMARY]
        connection=sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True)
        trades=[]
        cash=100000.
        equity=[cash]
        realized=[cash]
        coverage={r['timestamp']:r for r in replay['selection_coverage']}
        try:
            for saved in replay['trades']:
                t=dict(saved)
                rows=connection.execute('SELECT timestamp,close,volume FROM prices WHERE instrument=? AND timestamp>=? AND timestamp<? ORDER BY timestamp',
                    (t['key'],t['entry_timestamp'],t['exit_timestamp'])).fetchall()
                metrics, marks=trade_marks(t,rows,replay['config']['slippage_bps'])
                t.update(metrics)
                equity.extend(cash+p for _,p in marks)
                cash+=t['pnl']
                equity.append(cash)
                realized.append(cash)
                instant=datetime.fromtimestamp(t['entry_timestamp']/1000,IST)
                t['entry_time_ist']=instant.strftime('%H:%M')
                t['entry_bucket']='before_11' if instant.hour<11 else '11_to_13' if instant.hour<13 else '13_onward'
                t['calendar_days_to_expiry']=(date.fromisoformat(t['expiry'])-instant.date()).days
                t['expiry_bucket']='expiry_day' if t['calendar_days_to_expiry']==0 else '1_2_days' if t['calendar_days_to_expiry']<=2 else '3_plus_days'
                t['holding_minutes']=(t['exit_timestamp']-t['entry_timestamp'])//60000
                t['month']=instant.strftime('%Y-%m')
                t['missing_candidates_at_entry']=coverage[t['entry_timestamp']]['missing_candidate_minutes']
                t['period']=name
                trades.append(t)
        finally:
            connection.close()
        report['periods'][name]=dict(summary=stats(trades),
            observed_minute_close_drawdown=drawdown(equity), realized_drawdown=drawdown(realized),
            missing_or_zero_volume_mark_minutes=sum(t['missing_or_zero_volume_minutes'] for t in trades),
            total_holding_minutes=sum(t['expected_minutes'] for t in trades),
            worst_observed_trade_excursion=min(t['adverse_excursion_net'] for t in trades),
            losing_trades_previously_in_net_profit=sum(t['pnl']<0 and t['favorable_excursion_net']>0 for t in trades),
            gross_fill_pnl=sum(t['pnl']+t['entry_fee']+t['exit_fee'] for t in trades),
            fees=sum(t['entry_fee']+t['exit_fee'] for t in trades),
            entries_with_unknown_candidate_prices=sum(t['missing_candidates_at_entry']>0 for t in trades),
            by_direction=group(trades,'direction'), by_month=group(trades,'month'),
            by_entry_time=group(trades,'entry_bucket'), by_expiry=group(trades,'expiry_bucket'),
            by_exit_reason=group(trades,'reason'), trades=trades,
            input_sha256={source.name:digest(source),db.name:original['price_index_sha256']})
        exported.extend(trades)
    report['provenance']['saved_public_scenario_fees_compatible']=not report['fee_mismatches']
    report['provenance']['scope']='Fee equivalence only; original frozen source identity remains distinct. No full strategy replay performed.'
    if report['fee_mismatches']:
        raise ValueError('Updated fee model differs from saved fees; investigate before reporting risk.')
    (output/'risk-results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    with (output/'trade-risk.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(exported[0]))
        writer.writeheader()
        writer.writerows(exported)
    sections=[]
    for name,p in report['periods'].items():
        summary=p['summary']
        sections.append(f'<h2>{name.title()}</h2><p>{summary["trades"]} trades; net INR {summary["net_pnl"]:,.2f}; '
            f'observed minute-close drawdown INR {p["observed_minute_close_drawdown"]["rupees"]:,.2f} '
            f'({p["observed_minute_close_drawdown"]["percent"]:.2f}%); '
            f'without two largest winners INR {summary["without_top_two"]:,.2f}.</p>'
            f'<p>Missing/zero-volume holding minutes: {p["missing_or_zero_volume_mark_minutes"]}/{p["total_holding_minutes"]}. '
            f'Entries with unknown candidate prices: {p["entries_with_unknown_candidate_prices"]}/{summary["trades"]}.</p>')
        sections.append(f'<p>Average winner INR {summary["average_win"]:,.2f}; average loser INR {summary["average_loss"]:,.2f}. '
            f'Fill P&amp;L before fees (including slippage) INR {p["gross_fill_pnl"]:,.2f}; fees INR {p["fees"]:,.2f}. '
            f'{p["losing_trades_previously_in_net_profit"]} losing trades had an earlier positive net liquidation mark. '
            'This describes profit giveback; it does not establish that a trailing exit would improve results.</p>')
        for label,key in [('Direction','by_direction'),('Month','by_month'),('Entry time (IST)','by_entry_time'),('Days to expiry','by_expiry'),('Exit reason','by_exit_reason')]:
            rows=''.join(f'<tr><td>{escape(k)}</td><td>{v["trades"]}</td><td>{v["net_pnl"]:,.2f}</td><td>{v["winning_trades"]}</td></tr>' for k,v in p[key].items())
            sections.append(f'<h3>{label}</h3><table><tr><th>Group</th><th>Trades</th><th>Net INR</th><th>Wins</th></tr>{rows}</table>')
        worst=sorted(p['trades'],key=lambda t:t['pnl'])[:5]
        rows=''.join(f'<tr><td>{t["entry_date"]} {t["entry_time_ist"]}</td><td>{t["direction"]}</td><td>{t["pnl"]:,.2f}</td><td>{t["adverse_excursion_net"]:,.2f}</td><td>{t["favorable_excursion_net"]:,.2f}</td></tr>' for t in worst)
        sections.append('<h3>Five largest losses</h3><table><tr><th>Entry IST</th><th>Side</th><th>Net INR</th><th>Adverse net excursion</th><th>Favorable net excursion</th></tr>'+rows+'</table>')
    html='<!doctype html><meta charset="utf-8"><title>Options loss and risk diagnosis</title><style>body{font:16px system-ui;max-width:1050px;margin:40px auto;padding:20px;color:#243247;background:#fafbfc}table{border-collapse:collapse;width:100%}th,td{padding:9px;border-bottom:1px solid #ccd;text-align:left}h2{margin-top:45px}</style><h1>Options loss and risk diagnosis</h1><p>Retrospective diagnostic study. Original strategy results preserved. Shared fee model matches '+str(report['fee_checks'])+' saved order fees.</p><p>The comparison period remains unprofitable. These breakdowns identify questions for future testing; they do not validate new filters.</p>'+''.join(sections)+'<h2>Method and limitations</h2><ul>'+''.join('<li>'+escape(s)+'</li>' for s in report['methodology'])+'</ul><p><a href="trade-risk.csv">Trade-level CSV</a> · <a href="risk-results.json">Full results and provenance</a></p>'
    (output/'risk-report.html').write_text(html,encoding='utf-8')
    print(json.dumps({k:{x:v for x,v in p.items() if x not in ('trades','input_sha256')} for k,p in report['periods'].items()},indent=2))
    print('Fee checks:',report['fee_checks'],'Report:',output/'risk-report.html')


if __name__=='__main__':
    analyse(Path('artifacts/options_extended_2026').resolve())

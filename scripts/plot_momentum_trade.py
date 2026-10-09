"""Plot one recorded momentum trade from its frozen five-minute inputs.

Requires matplotlib. No provider calls or new trading signals are generated.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from core.research import store


def minute(clock):
    h, m = map(int, clock.split(':'))
    return h * 60 + m - 555


def plot(run_id, trade_index, output):
    report = store.read('runs/' + run_id)
    trade = report['trades'][trade_index]
    cfg = report['config']
    bars = store.read('run_intraday/' + run_id)[trade['symbol']][trade['entry_date']]
    bars = [b for b in bars if b['time'] <= cfg['square_off_time']]
    opening_bars = bars[:cfg['opening_minutes']//5]
    opening = dict(open=opening_bars[0]['open'], close=opening_bars[-1]['close'],
                   volume=sum(b['volume'] for b in opening_bars))
    entry_x, exit_x = minute(trade['entry_time']), minute(trade['exit_time'])
    signal_end = minute(trade['signal_time']) + 5
    selection = next(s for s in report['selections'] if s['date'] == trade['entry_date'])
    rank = next(i + 1 for i, s in enumerate(selection['selected']) if s['symbol'] == trade['symbol'])
    long = trade['direction'] == 'long'
    buy_label, sell_label = ('BUY', 'SELL / EXIT') if long else ('SELL / SHORT', 'BUY / COVER')
    blue, green, red = '#2563a6', '#178261', '#bd443d'
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
                         'axes.spines.top': False, 'axes.spines.right': False})
    fig = plt.figure(figsize=(15, 9), facecolor='#f7f9fc')
    grid = fig.add_gridspec(2, 2, height_ratios=[4, 1], width_ratios=[3.7, 1.65],
                            left=.065, right=.97, bottom=.14, top=.86, wspace=.15, hspace=.07)
    ax = fig.add_subplot(grid[0, 0])
    volume = fig.add_subplot(grid[1, 0], sharex=ax)
    notes = fig.add_subplot(grid[:, 1]); notes.axis('off')
    ax.set_facecolor('white'); volume.set_facecolor('white')
    for b in bars:
        x = minute(b['time']) + 2.5
        color = green if b['close'] >= b['open'] else red
        ax.vlines(x, b['low'], b['high'], color=color, linewidth=1)
        ax.add_patch(Rectangle((x - 1.7, min(b['open'], b['close'])), 3.4,
                              max(abs(b['close'] - b['open']), .15), facecolor=color, edgecolor=color))
        volume.bar(x, b['volume'] / 1000, width=3.4, color=color, alpha=.75)
    ax.axvspan(0, cfg['opening_minutes'], color=blue, alpha=.18)
    ax.axvspan(entry_x, exit_x, color=green if long else red, alpha=.045)
    ax.hlines(trade['trigger'], cfg['opening_minutes'], signal_end, color=blue,
              linestyles='--', linewidth=1.5, label=f"Opening breakout level: Rs {trade['trigger']:,.2f}")
    ax.hlines(trade['opening_low'] if long else trade['opening_high'], 0, signal_end,
              color='#91a2b8', linestyles=':', linewidth=1, label='Other opening-range boundary')
    ax.hlines(trade['initial_stop'], entry_x, exit_x + 5, color=red,
              linestyles='--', linewidth=1.5, label=f"Protective stop: Rs {trade['initial_stop']:,.2f}")
    ax.axvline(signal_end, color=blue, alpha=.5, linestyle=':')
    ax.scatter(signal_end, trade['signal_close'], color=blue, s=45, zorder=6)
    ax.scatter(entry_x, trade['entry'], color=green if long else red, marker='^' if long else 'v', s=120, zorder=7)
    ax.scatter(exit_x + 2.5, trade['exit'], color=red if long else green, marker='v' if long else '^', s=120, zorder=7)
    ax.annotate(f"{buy_label} {trade['entry_time']}\nRs {trade['entry']:,.2f}",
                (entry_x, trade['entry']), xytext=(entry_x + 35, trade['entry'] + 7),
                arrowprops={'arrowstyle':'->', 'color':green if long else red}, color=green if long else red,
                fontweight='bold', bbox={'facecolor':'white', 'edgecolor':'none', 'alpha':.9})
    ax.annotate(f"{sell_label}\n{trade['exit_time']} candle · Rs {trade['exit']:,.2f}",
                (exit_x + 2.5, trade['exit']), xytext=(exit_x - 105, trade['exit'] - 7),
                arrowprops={'arrowstyle':'->', 'color':red if long else green}, color=red if long else green,
                fontweight='bold', bbox={'facecolor':'white', 'edgecolor':'none', 'alpha':.9})
    ax.legend(loc='upper right', fontsize=8, framealpha=.95)
    ax.set_ylabel('Price (INR)'); ax.grid(axis='y', color='#e6ebf1')
    ax.margins(y=.22); ax.set_xlim(-5, 350); ax.tick_params(labelbottom=False)
    ticks = [0, 60, 120, 180, 240, 300, 345]
    volume.set_xticks(ticks, ['09:15','10:15','11:15','12:15','13:15','14:15','15:00'])
    volume.set_xlabel('India time (IST) · each candle represents five minutes')
    volume.set_ylabel('Volume\n(thousands)', fontsize=9)
    fig.text(.065, .94, f"{trade['symbol']}  |  {trade['entry_date']}  |  Why the backtest entered and exited",
             fontsize=20, fontweight='bold', color='#20344e')
    fig.text(.065, .895, f"Recorded simulation · {cfg['opening_minutes']}-minute opening range · "
             f"{cfg.get('confirmation_minutes',5)}-minute close confirmation · frozen Upstox five-minute OHLCV",
             fontsize=11, color='#52657e')
    sections = [
        ('1  QUALIFIED AT THE OPEN',
         f"Opening volume: {opening['volume']:,.0f} shares\nRelative volume: {trade['relative_volume']:.2f}x\n"
         f"Required: >= {cfg['min_relative_volume']:.2f}x\nSelected RV rank: {rank} of {cfg['max_positions']}\n"
         f"Opening open / close:\nRs {opening['open']:,.2f} / {opening['close']:,.2f}"),
        ('2  COMPLETED-CLOSE SIGNAL',
         f"At {trade['entry_time']}, the confirmation\nclose was Rs {trade['signal_close']:,.2f}.\n"
         f"{'Above' if long else 'Below'} opening {'high' if long else 'low'}: Rs {trade['trigger']:,.2f}\n"
         f"Next five-minute open + slippage:\n{buy_label} at Rs {trade['entry']:,.2f}"),
        ('3  PROTECTION AND EXIT',
         f"Prior daily ATR: Rs {trade['atr']:,.2f}\nStop distance: {cfg['stop_atr']} x daily ATR\n"
         f"Initial stop: Rs {trade['initial_stop']:,.2f}\nExit: {trade['reason']}\n"
         f"{trade['exit_time']}–{(exit_x+560)//60:02d}:{(exit_x+560)%60:02d} interval; slipped fill\n"
         f"{trade['quantity']} shares · net P&L: Rs {trade['pnl']:+,.2f}"),
    ]
    for y, (title, body) in zip([.97,.64,.33], sections):
        notes.text(0, y, title, transform=notes.transAxes, fontsize=11, fontweight='bold', color='#20344e', va='top')
        notes.text(0, y-.045, body, transform=notes.transAxes, fontsize=10.5, color='#40546c', va='top', linespacing=1.55)
    fig.text(.065,.065, ('SELL closes the long position; it is not a new short signal. ' if long else
                        'BUY covers the short position; it is not a new long signal. ') +
             'VWAP / EMA / RSI / ADX were not entry requirements.', fontsize=10, color='#52657e')
    fig.text(.065,.035, f"Recorded run {run_id}, trade index {trade_index}. "
             'Stop execution is known only within its five-minute candle; markers do not imply tick-level timing.',
             fontsize=9, color='#697d96')
    output = Path(output); output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=170, facecolor=fig.get_facecolor())
    fig.savefig(output.with_suffix('.svg'), facecolor=fig.get_facecolor())
    plt.close(fig)
    return output.resolve()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    parser.add_argument('--trade', required=True, type=int)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(plot(args.run, args.trade, args.output))

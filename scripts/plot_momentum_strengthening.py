"""Render the recorded stronger-entry decision and frozen-run comparisons."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.ticker import MaxNLocator
from core.research import store, momentum

OUT = Path(__file__).resolve().parents[1] / 'artifacts'
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,
                     'axes.spines.top':False,'axes.spines.right':False})
COLORS = ['#8a98ac','#2563a6','#168466']


def tcs_decision():
    r=store.read('runs/a3d9ef4bbaab'); t=r['trades'][33]
    assert t['symbol']=='TCS' and t['entry_date']=='2026-03-30'
    bars=store.read('run_intraday/'+r['id'])['TCS'][t['entry_date']][:12]
    q=momentum.confirmation_quality(bars,11,60,1,t['atr'])
    vwap=momentum.session_vwap(bars)
    threshold=t['opening_high']+.1*t['atr']
    comparison=store.read('momentum_comparisons/e9723b9dbb6f')
    stronger=store.read('runs/'+comparison['trials'][-1]['run_id'])
    assert not any(x['symbol']=='TCS' and x['entry_date']==t['entry_date'] for x in stronger['trades'])
    fig,(ax,notes)=plt.subplots(1,2,figsize=(14,6.8),gridspec_kw={'width_ratios':[1.6,1]},facecolor='#f7f9fc')
    fig.subplots_adjust(left=.065,right=.975,top=.81,bottom=.20,wspace=.15)
    ax.set_facecolor('white'); notes.axis('off')
    for i,b in enumerate(bars):
        x=i*5+2.5; color='#168466' if b['close']>=b['open'] else '#bd443d'
        ax.vlines(x,b['low'],b['high'],color=color)
        ax.add_patch(Rectangle((x-1.7,min(b['open'],b['close'])),3.4,max(abs(b['close']-b['open']),.15),color=color))
    ax.axvspan(0,5,color='#2563a6',alpha=.13)
    ax.hlines(t['opening_high'],5,60,color='#8a98ac',linestyle='--',label=f"Old trigger: Rs {t['opening_high']:,.2f}")
    ax.hlines(threshold,5,60,color='#9256a2',linestyle='--',label=f"Buffered trigger: Rs {threshold:,.2f}")
    ax.plot([(i+1)*5 for i in range(12)],vwap,color='#2563a6',linewidth=1.7,label='Completed-bar session VWAP')
    ax.scatter(60,q['close'],s=70,color='#bd443d',zorder=8)
    ax.annotate(f"Hourly close: Rs {q['close']:,.2f}\nStricter entry: REJECTED",(60,q['close']),
                xytext=(26,2362),color='#bd443d',fontweight='bold',
                arrowprops={'arrowstyle':'->','color':'#bd443d'},
                bbox={'facecolor':'white','edgecolor':'none','alpha':.9})
    ax.set_xlim(-2,64);ax.set_ylim(2352,2405)
    ax.set_xticks([0,15,30,45,60],['09:15','09:30','09:45','10:00','10:15'])
    ax.set_ylabel('Price (INR)');ax.set_xlabel('India time · five-minute candles; hour closes at 10:15')
    ax.grid(axis='y',color='#e6ebf1');ax.legend(loc='upper left',fontsize=9)
    notes.text(0,1,'FOUR NEW CHECKS AT 10:15',transform=notes.transAxes,fontsize=13,fontweight='bold',color='#20344e')
    rows=[['Breakout close',f"{q['close']:,.2f}",f"> {threshold:,.2f}",'FAIL'],
          ['Close vs VWAP',f"{q['close']:,.2f}",f"> {vwap[-1]:,.2f}",'FAIL'],
          ['Close position',f"{q['close_strength']*100:.1f}%",'>= 70%','FAIL'],
          ['Directional body',f"{q['body_atr']:.3f} ATR",'>= 0.1 ATR','FAIL']]
    table=notes.table(cellText=rows,colLabels=['Check','Observed','Required','Result'],cellLoc='left',colLoc='left',
                      bbox=[0,.48,1,.44],colWidths=[.31,.24,.27,.18])
    table.auto_set_font_size(False);table.set_fontsize(9)
    for (row,col),cell in table.get_celld().items():
        cell.set_edgecolor('#e0e6ef')
        if row==0:cell.set_facecolor('#e9eef6');cell.set_text_props(weight='bold',color='#20344e')
        elif col==3:cell.set_facecolor('#fcebea');cell.set_text_props(color='#bd443d',weight='bold')
    notes.text(0,.38,'EARLIER HOURLY VARIANT: BUY',transform=notes.transAxes,fontweight='bold',color='#697d96',va='top')
    notes.text(0,.31,'Close exceeded the unbuffered opening high.\nThat recorded trade later lost Rs 2,439.',transform=notes.transAxes,color='#52657e',linespacing=1.5,va='top')
    notes.text(0,.16,'STRICTER VARIANT: NO TRADE',transform=notes.transAxes,fontweight='bold',color='#168466',va='top')
    notes.text(0,.09,'This entry is rejected. No later TCS entry\nqualified that day in the saved stronger run.',transform=notes.transAxes,color='#52657e',linespacing=1.5,va='top')
    fig.text(.065,.93,'TCS | 30 March 2026 | Why the stronger rules stayed out',fontsize=20,fontweight='bold',color='#20344e')
    fig.text(.065,.865,'Same frozen five-minute prices. Stronger checks use only the completed hour and prior daily ATR.',fontsize=11,color='#52657e')
    fig.text(.065,.10,'Close position = (close - hourly low) / (hourly high - hourly low). Directional body = (close - hourly open) / prior ATR.',fontsize=10,color='#52657e')
    fig.text(.065,.055,'Avoiding this loss does not establish an edge: the same rules also remove other trades. All portfolio trials remain negative.',fontsize=10,color='#697d96')
    fig.savefig(OUT/'tcs-stronger-entry-review.png',dpi=170,facecolor=fig.get_facecolor());plt.close(fig)


def comparisons():
    labels=['Baseline replay','Hourly + 0.1 ATR buffer','Stronger hourly confirmation']
    display=['Original baseline','Hourly + buffer','Full stricter rules']
    fig,axes=plt.subplots(1,2,figsize=(14,6.5),facecolor='#f7f9fc')
    fig.subplots_adjust(left=.065,right=.98,top=.78,bottom=.24,wspace=.18)
    for ax,cid,title in zip(axes,['e9723b9dbb6f','aeb6eab8c0cf'],['March 2026 · 19 sessions','26 Aug–4 Sep 2026 · 8 sessions']):
        c=store.read('momentum_comparisons/'+cid)
        ax.set_facecolor('white')
        for label,name,color in zip(labels,display,COLORS):
            trial=next(t for t in c['trials'] if t['label']==label)
            r=store.read('runs/'+trial['run_id']);cap=r['metrics']['initial_capital']
            values=[0]+[(row['equity']/cap-1)*100 for row in r['curve']]
            ax.plot(range(len(values)),values,color=color,linewidth=2.2,
                    label=f"{name}: {r['metrics']['return_pct']:.2f}% ({r['metrics']['trade_count']} trades)")
        ax.axhline(0,color='#c8d2df',linewidth=1);ax.grid(axis='y',color='#e6ebf1')
        ax.set_title(title,loc='left',fontsize=13,fontweight='bold',pad=16)
        ax.set_xlabel('Completed sessions (0 = starting capital)');ax.set_ylabel('Cumulative net return (%)')
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.legend(loc='lower left',fontsize=9,framealpha=.95)
    fig.text(.065,.93,'Stricter entries reduced losses — profitability is still unproven',fontsize=20,fontweight='bold',color='#20344e')
    fig.text(.065,.86,'Matched frozen inputs, capital and modeled costs within each window. Lines show session-end portfolio equity.',fontsize=11,color='#52657e')
    fig.text(.065,.135,'Hourly + buffer performed better than the full filter stack in both windows. Fewer trades also means less exposure.',fontsize=11,color='#52657e')
    fig.text(.065,.075,'These are two short exploratory periods using current constituents. Intraday drawdown is not shown. Defaults remain unchanged.',fontsize=10,color='#697d96')
    fig.savefig(OUT/'momentum-stronger-comparison.png',dpi=170,facecolor=fig.get_facecolor());plt.close(fig)


if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    tcs_decision();comparisons()
    print(OUT/'tcs-stronger-entry-review.png')
    print(OUT/'momentum-stronger-comparison.png')

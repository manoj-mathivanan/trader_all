"""Plot retained indicator comparisons, using saved real backtest results."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.research import store
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--comparisons',nargs='+',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    reports=[store.read('momentum_comparisons/'+i) for i in args.comparisons]
    labels=[t['label'] for t in reports[0]['trials']]
    if any([t['label'] for t in r['trials']]!=labels for r in reports):
        raise ValueError('Comparisons must have identical trial labels.')
    values=np.array([[r['trials'][i]['metrics']['return_pct'] for r in reports] for i in range(len(labels))],dtype=float)
    fig,ax=plt.subplots(figsize=(12,7.5))
    limit=max(1,float(np.nanmax(np.abs(values))))
    ax.imshow(values,cmap='RdYlGn',vmin=-limit,vmax=limit,aspect='auto')
    ax.set_xticks(range(len(reports)),[r['start'][:7] for r in reports],fontsize=11)
    ax.set_yticks(range(len(labels)),labels,fontsize=10)
    ax.xaxis.tick_top()
    ax.tick_params(length=0,pad=12)
    for i in range(len(labels)):
        for j,r in enumerate(reports):
            count=r['trials'][i]['metrics']['trade_count']
            ax.text(j,i,f'{values[i,j]:+.2f}%\n{count} trades',ha='center',va='center',fontsize=11,
                    color='white' if values[i,j]<-.55*limit else '#202020')
    ax.set_xticks(np.arange(-.5,len(reports),1),minor=True)
    ax.set_yticks(np.arange(-.5,len(labels),1),minor=True)
    ax.grid(which='minor',color='white',linewidth=3)
    ax.tick_params(which='minor',length=0)
    for spine in ax.spines.values():spine.set_visible(False)
    fig.suptitle('Momentum indicators: all 28 trials lost after modeled costs',fontsize=16,x=.04,ha='left',y=.98)
    fig.text(.04,.025,'Fixed rules; four exploratory windows. Upstox five-minute inputs aggregated into completed 10-minute/hourly candles.\nNet returns include assumed charges and slippage. These are development results, not untouched validation.',fontsize=9,color='#444444')
    fig.subplots_adjust(left=.32,right=.98,top=.86,bottom=.12)
    destination=Path(args.output);destination.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(destination,dpi=170,facecolor='white')
    print(destination.resolve())

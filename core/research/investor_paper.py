"""Isolated composite-score paper portfolio; no broker/order gateway imports."""
import hashlib,json,math
from datetime import datetime,timedelta
from core.research import store,investor_scores as scores,investor_intelligence as intel

NAME='investor/assessments/composite-paper-state'
POLICY=dict(version='composite-paper-v1',initial_cash=100000,max_positions=10,max_position_pct=10,risk_pct=.5,
            cash_reserve_pct=10,fee_bps_per_side=10,slippage_bps_per_side=15,max_entries_per_session=3,max_hold_sessions=20)


def state():
    return store.read(NAME,dict(as_of=store.now(),activated_at=store.now(),policy=POLICY,cash=POLICY['initial_cash'],positions={},pending={},trades=[],decisions=[],processed=[],equity=POLICY['initial_cash'],realized_pnl=0))


def plan(row,technical):
    close=scores.num(technical.get('close'));atr=scores.num(technical.get('atr14'));base=scores.num(row.get('invalidation_reference'))
    stop=scores.num(row.get('stop_price'))
    if stop is None and close:
        choices=[x for x in [base,close-2*atr if atr and atr>0 else None] if x is not None and 0<x<close]
        stop=min(choices) if choices else None
    target=scores.num(row.get('target_price'))
    if target is None and close and stop and stop<close:target=close+3*(close-stop)
    return dict(stop_price=stop,target_price=target,plan_source='Recorded override or base/2Ã—ATR invalidation; target 3R is a risk plan, not a price forecast.')


def completed_bars(isin):
    t=store.read('investor/stock_details/'+isin,{}).get('technical',{})
    clock=intel.company.utcnow().astimezone(intel.company.IST)
    cutoff=clock.date() if clock.hour>=16 else clock.date()-timedelta(days=1)
    if t.get('status')!='available':return []
    return sorted([b for b in t.get('audited_bars',[]) if b['date']<=min(cutoff.isoformat(),t.get('price_date',cutoff.isoformat()))],key=lambda b:b['date'])


def record_portfolio(value):
    value['as_of']=store.now()
    store.write(NAME,value)
    identity=hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
    store.write('investor/assessments/composite-paper-snapshot-'+identity,value)


def run(settings,log=lambda m:None,*,force=False):
    from core.research import investor_workflow as workflow
    with store.LOCK:
        if force:
            store.write('investor/paper_control',dict(enabled=True,at=store.now()))
        elif not store.read('investor/paper_control',{}).get('enabled',True):
            return dict(status='disabled',reason='Create or explicitly run a new paper simulation to resume.')
        p=state();policy=p['policy'];fee=policy['fee_bps_per_side']/10000;slip=policy['slippage_bps_per_side']/10000
        p.setdefault('activated_at',p['as_of'])
        external={r['isin'] for r in workflow.paper_holdings(settings)}
        for row in workflow.score_targets(settings):
            isin=row['isin'];kind=row['kind'];signal=store.read('investor/assessments/score-latest-'+isin+'-'+kind,{})
            if not signal or signal.get('model',{}).get('implementation_sha256')!=scores.MODEL['implementation_sha256'] or signal.get('id') in p['processed']:continue
            p['processed'].append(signal['id'])
            if datetime.fromisoformat(signal['as_of'])<datetime.fromisoformat(p['activated_at']):continue
            if isin in p['pending'] and kind=='candidate' and signal['decision']!='buy_candidate':
                signal_day=datetime.fromisoformat(signal['as_of']).astimezone(intel.company.IST).date().isoformat()
                original_day=datetime.fromisoformat(p['pending'][isin]['signal']['as_of']).astimezone(intel.company.IST).date().isoformat()
                if signal_day==original_day:
                    p['decisions'].append(dict(as_of=store.now(),isin=isin,recommendation_id=p['pending'][isin]['signal']['id'],status='cancelled',reason='A newer same-session assessment revoked the entry.',superseded_by=signal['id']))
                    del p['pending'][isin]
            if isin in p['positions']:
                if kind=='holding' and signal['decision'] in ('exit_candidate','reduce_candidate'):
                    p['positions'][isin]['exit_signal']=dict(id=signal['id'],as_of=signal['as_of'],decision=signal['decision'])
            elif kind=='candidate' and signal['decision']=='buy_candidate' and isin not in p['pending'] and isin not in external:
                p['pending'][isin]=dict(signal=signal,company=row['company'])
        tapes={isin:completed_bars(isin) for isin in set(p['positions'])|set(p['pending'])}
        lookup={isin:{b['date']:b for b in bars} for isin,bars in tapes.items()}
        # Pause positions when adjusted history changes across a split/revision.
        for isin,pos in p['positions'].items():
            original=lookup.get(isin,{}).get(pos['entry_date'])
            if original and any(abs(original[k]-pos['entry_bar'][k])>max(.01,abs(pos['entry_bar'][k])*.001) for k in ('open','close')):
                pos['paused']='Entry prices revised; reconcile corporate action/share quantity before paper execution.'
        dates=sorted({b['date'] for bars in tapes.values() for b in bars if b['date']>p.get('last_session','')})
        def sell(isin,pos,b,raw,reason,quantity=None):
            qty=quantity or pos['quantity'];price=raw*(1-slip);proceeds=qty*price*(1-fee);cost=pos['cost']*qty/pos['quantity'];profit=proceeds-cost
            p['cash']+=proceeds;p['realized_pnl']+=profit
            p['trades'].append(dict(company=pos['company'],isin=isin,quantity=qty,entry_date=pos['entry_date'],exit_date=b['date'],entry_price=pos['entry_price'],exit_price=price,net_pnl=profit,reason=reason,recommendation_id=pos['recommendation_id'],exit_recommendation=pos.get('exit_signal'),price_bar=b))
            if qty==pos['quantity']:del p['positions'][isin]
            else:pos['quantity']-=qty;pos['cost']-=cost;pos.pop('exit_signal',None)
        for date in dates:
            # Open-time exits precede open-time entries; intraday proceeds cannot fund entries.
            for isin,pos in list(p['positions'].items()):
                b=lookup.get(isin,{}).get(date)
                if not b or pos.get('paused') or date<=pos['last_bar_date']:continue
                signal=pos.get('exit_signal');day=datetime.fromisoformat(signal['as_of']).astimezone(intel.company.IST).date().isoformat() if signal else None
                if day and date>day:sell(isin,pos,b,b['open'],signal['decision'],max(1,pos['quantity']//2) if signal['decision']=='reduce_candidate' else None)
                elif b['open']<=pos['stop']:sell(isin,pos,b,b['open'],'stop_gap')
                elif b['open']>=pos['target']:sell(isin,pos,b,b['open'],'target_gap')
            equity=p['cash']+sum(x['quantity']*lookup.get(isin,{}).get(date,{}).get('open',x['mark']) for isin,x in p['positions'].items())
            entered=0
            for isin,item in sorted(list(p['pending'].items()),key=lambda pair:(-pair[1]['signal']['score'],pair[0])):
                signal=item['signal'];day=datetime.fromisoformat(signal['as_of']).astimezone(intel.company.IST).date().isoformat();bars=tapes.get(isin,[])
                future=[b for b in bars if b['date']>day]
                if not future or future[0]['date']!=date:continue
                b=future[0];reason=None;entry=b['open']*(1+slip);stop=signal['entry_plan'].get('stop');target=signal['entry_plan'].get('target')
                risk=(entry-stop)/entry if stop and entry>stop else None
                if bars[0]['date']>day:reason='Signal entry period no longer present in validated history.'
                if risk is None or risk<=0 or risk>.08 or not target or target<=entry or (target-entry)/(entry-stop)<2:reason='Opening gap invalidated planned risk or reward/risk.'
                budget=min(equity*policy['max_position_pct']/100,p['cash']-equity*policy['cash_reserve_pct']/100)
                stop_loss=entry*(1+fee)-stop*(1-slip)*(1-fee) if stop else None
                qty=max(0,math.floor(min(budget/(entry*(1+fee)),equity*policy['risk_pct']/100/stop_loss))) if risk and risk>0 and stop_loss and stop_loss>0 else 0
                if isin in external:reason='Stock already present in the separate holdings portfolio.'
                if len(p['positions'])>=policy['max_positions'] or entered>=policy['max_entries_per_session'] or qty<1:reason='Cash, position-size or session entry limit.'
                del p['pending'][isin]
                if reason:p['decisions'].append(dict(as_of=store.now(),isin=isin,recommendation_id=signal['id'],status='cancelled',reason=reason));continue
                cost=qty*entry*(1+fee);p['cash']-=cost;entered+=1
                p['positions'][isin]=dict(company=item['company'],quantity=qty,entry_price=entry,entry_date=date,cost=cost,stop=stop,target=target,mark=b['open'],last_bar_date=day,sessions=0,recommendation_id=signal['id'],entry_bar=b,thesis='Composite score ≥75 and confidence ≥80; complete evidence and confirmed breakout at signal time.',model=signal['model'])
                p['decisions'].append(dict(as_of=store.now(),isin=isin,recommendation_id=signal['id'],status='filled',entry_date=date,quantity=qty,entry_price=entry,cost=cost,source_bar=b))
            for isin,pos in list(p['positions'].items()):
                b=lookup.get(isin,{}).get(date)
                if not b or pos.get('paused') or date<=pos['last_bar_date']:continue
                pos['sessions']+=1;pos['last_bar_date']=date;pos['mark']=b['close']
                if b['low']<=pos['stop']:sell(isin,pos,b,pos['stop'],'stop')
                elif b['high']>=pos['target']:sell(isin,pos,b,pos['target'],'target')
                elif pos['sessions']>=policy['max_hold_sessions']:sell(isin,pos,b,b['close'],'time_exit')
            p['last_session']=date
            daily_equity=p['cash']+sum(x['quantity']*x['mark'] for x in p['positions'].values())
            p['peak_equity']=max(p.get('peak_equity',policy['initial_cash']),daily_equity)
            p['max_drawdown_pct']=max(p.get('max_drawdown_pct',0),(1-daily_equity/p['peak_equity'])*100)
            p.setdefault('equity_history',[]).append(dict(date=date,equity=daily_equity,cash=p['cash']))
        # No retroactive fills when a late-imported signal misses an already processed open.
        for isin,item in list(p['pending'].items()):
            day=datetime.fromisoformat(item['signal']['as_of']).astimezone(intel.company.IST).date().isoformat()
            eligible=[b for b in tapes.get(isin,[]) if b['date']>day]
            if eligible and eligible[0]['date']<=p.get('last_session',''):
                p['decisions'].append(dict(as_of=store.now(),isin=isin,recommendation_id=item['signal']['id'],status='cancelled',reason='Signal arrived after its eligible session had been processed.'))
                del p['pending'][isin]
        p['equity']=p['cash']+sum(x['quantity']*x['mark'] for x in p['positions'].values())
        p['peak_equity']=max(p.get('peak_equity',policy['initial_cash']),p['equity'])
        p['max_drawdown_pct']=max(p.get('max_drawdown_pct',0),(1-p['equity']/p['peak_equity'])*100)
        p['return_pct']=(p['equity']/policy['initial_cash']-1)*100
        p['win_rate_pct']=sum(t['net_pnl']>0 for t in p['trades'])/len(p['trades'])*100 if p['trades'] else None
        today=intel.company.utcnow().astimezone(intel.company.IST)
        cutoff=today.date() if today.hour>=16 else today.date()-timedelta(days=1)
        benchmark=[b for b in store.read('bars/NIFTY50',{}).get('bars',[]) if b.get('date','9999')<=cutoff.isoformat() and scores.num(b.get('close')) and b['close']>0]
        if benchmark:
            last=max(benchmark,key=lambda b:b['date'])
            activation_day=datetime.fromisoformat(p['activated_at']).astimezone(intel.company.IST).date().isoformat()
            if p.get('benchmark_base',{}).get('date','9999')<activation_day:p.pop('benchmark_base',None)
            eligible=sorted([b for b in benchmark if b['date']>=activation_day],key=lambda b:b['date'])
            if eligible:
                first=eligible[0];p.setdefault('benchmark_base',dict(date=first['date'],close=first['close'],recorded_at=store.now()))
                base=p['benchmark_base'];p['benchmark']=dict(name='Nifty 50 price return',base=base,latest=last,return_pct=(last['close']/base['close']-1)*100,notice='Price index comparison from first completed close on/after activation; excludes dividends. Check portfolio and index observation dates before comparing.')
            else:p['benchmark']=dict(name='Nifty 50 price return',return_pct=None,status='awaiting_activation_session',notice='No completed Nifty close on/after portfolio activation; earlier returns must not be attributed to this paper strategy.')
        p['notice']='Daily-bar paper simulation, not live orders. Rs 1 lakh capital; fees 10 bps and slippage 15 bps each side. Next-session open entries; stop first if both barriers touch. Adjusted-price revisions pause positions; dividends/tax changes require separate accounting. Starting now; no historical signals imported.'
        record_portfolio(p)
    log('Composite paper portfolio: '+str(len(p['positions']))+' positions, '+str(len(p['pending']))+' pending, '+str(len(p['trades']))+' completed trades.')
    return dict(positions=len(p['positions']),pending=len(p['pending']),trades=len(p['trades']),equity=p['equity'],cash=p['cash'])

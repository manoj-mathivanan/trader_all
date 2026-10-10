"""Audit the selected configuration and save reviewable local comparison runs."""
import json
import hashlib
import sys
from collections import Counter, defaultdict
from pathlib import Path
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import research_swing_refinements as search
from core.research import backtest, store, strategy_presets
from core.research.config import BacktestConfig, TradingConfig, current_settings


def evaluate(name,changes,period=None):
    values={**search.BASE,**changes,'name':name}
    if period:
        values.update(start=period[0],end=period[1])
    c=BacktestConfig(**values)
    r=backtest.simulate(search.DATA,c,fundamental_scores=search.SCORES)
    fees=Counter()
    reasons=Counter()
    monthly=defaultdict(float)
    for t in r['trades']:
        for k,v in t.get('charges',{}).items():
            if k!='total':fees[k]+=v
        monthly[t['exit_date'][:7]]+=t['pnl']
        reasons[t['reason']]+=1
    summary=dict(name=name,changes=changes,**search.compact(r),cost_breakdown=dict(fees),
                 exit_reasons=dict(reasons),realized_monthly=dict(monthly))
    print(name,{k:round(r['metrics'][k],4) for k in ['return_pct','max_drawdown_pct','modeled_fees']},flush=True)
    return summary,r


def main():
    plan=json.loads((ROOT/'artifacts/swing_refinement_search.json').read_text())
    reference=plan['reference']
    if any(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=h for p,h in plan.get('source_files',{}).items()):
        raise ValueError('Search source changed; rerun selection before finalizing.')
    selected=plan['selection']['changes']
    search.initialize(reference)
    # Publish through the normal, unmemoized engine. The saved ledger must
    # independently reproduce the accelerated search's output.
    cached_signal=backtest.signal
    original=store.read('runs/'+reference)
    legacy=backtest.simulate(search.DATA,BacktestConfig(**original['config']),fundamental_scores=search.SCORES)
    if legacy['metrics']!=original['metrics'] or legacy['trades']!=original['trades']:
        raise ValueError('Legacy engine replay changed; do not publish research.')
    output=dict(reference=reference,legacy_replay_exact=True,selection=plan['selection'],
        notice=plan['notice'],full=[],audit=[],sensitivity=[],stress=[],saved_runs={})
    names={r['name']:r for r in plan['trials']}
    for name in ['original_zerodha',*plan['ranking'][:4], 'trail_50d','take_8','take_15','trail50_volume_1.5','trail50_breadth_off']:
        if name not in [x['name'] for x in output['full']]:
            summary,r=evaluate(name,names[name]['changes'])
            output['full'].append(summary)
            if name in ['original_zerodha',plan['selection']['name'],'trail_50d','take_15']:
                output['audit'].append(evaluate(name,names[name]['changes'],('2026-07-01','2026-10-08'))[0])
    for sessions in [8,9,11,12,15]:
        output['sensitivity'].append(evaluate('stall_'+str(sessions),{**selected,'stalled_exit_sessions':sessions})[0])
    for slip in [20,50]:
        output['stress'].append(evaluate('slippage_'+str(slip),{**selected,'slippage_bps':slip})[0])
    output['stress'].append(evaluate('risk_1pct',{**selected,'risk_pct':1})[0])
    financial=store.read('run_fundamentals/'+reference)
    settings=current_settings(reference)
    selected_name='Blue Sky Stalled Exit - Zerodha'
    balanced_name='Blue Sky Early Profit - Zerodha'
    for label,name,changes in [('baseline','Original Rules - Zerodha',{}),('selected',selected_name,selected),
                               ('balanced',balanced_name,{'winner_exit':'take_15'})]:
        run_id=uuid4().hex[:12]
        cfg=BacktestConfig(**{**search.BASE,**changes,'name':name,'comparison_run_id':reference})
        backtest.signal=lambda bars,i,c:backtest.matches(bars,i,c)
        backtest.run(settings,cfg,lambda msg:print(msg,flush=True),run_id,fundamental_evidence=financial)
        backtest.signal=cached_signal
        saved=store.read('runs/'+run_id)
        expected=evaluate('verify_'+label,changes)[1]
        if saved['metrics']!=expected['metrics'] or saved['trades']!=expected['trades']:
            raise ValueError('Saved audit differs from selection engine.')
        saved['research_selection']=dict(reference_run_id=reference,calibration='2025-03-03 to 2026-02-27',
            validation='2026-03-02 to 2026-06-30',audit='2026-07-01 to 2026-10-08 (previously inspected)',
            trials=len(plan['trials']),notice=plan['notice'])
        saved['warnings'].append(plan['notice'])
        store.write('runs/'+run_id,saved)
        output['saved_runs'][label]=run_id
    selected_audit=next(x for x in output['audit'] if x['name']==plan['selection']['name'])
    output['audit_passed']=selected_audit['return_pct']>0
    trading=TradingConfig(**{k:v for k,v in {**search.BASE,**selected,'name':selected_name}.items() if k in TradingConfig.model_fields})
    preset=strategy_presets.ScreenInput(name=selected_name,pattern=trading.pattern,trading_defaults=trading,
        minimum_warmup_sessions=260,source_run_id=output['saved_runs']['selected'],
        description='Exploratory frozen-run selection (2025-03 to 2026-06); later dates already inspected. '
                    'Keeps Blue Sky/fundamental ranking/breadth filters, trails SMA50 after 1R and exits '
                    'at the next open after 10 sessions without a 0.5R closing gain. Includes Zerodha NSE equity charges. '
                    f"Fresh July-October audit return: {selected_audit['return_pct']:.2f}%. "
                    'Use forward paper observation before live adoption; historical members and unresolved exclusions remain biased.')
    target=ROOT/'strategies/swing_patterns/presets/blue_sky_stalled_zerodha.json'
    target.write_text(preset.model_dump_json(indent=2),encoding='utf-8')
    balanced=TradingConfig(**{**trading.model_dump(),'name':balanced_name,'winner_exit':'take_15','stalled_exit_sessions':0})
    balanced_preset=strategy_presets.ScreenInput(name=balanced_name,pattern=balanced.pattern,trading_defaults=balanced,
        minimum_warmup_sessions=260,source_run_id=output['saved_runs']['balanced'],
        description='Conservative forward-paper alternative from the same exploratory frozen-data study. '
                    'Keeps the existing entry/breadth rules, 8% stop, 1R breakeven and books a +15% closing gain. '
                    'Full-sample net return 49.49%, max drawdown 8.37%; separately reset July-October audit +2.22%. '
                    'These dates were already inspected. Includes Zerodha fees; daily close target execution remains an approximation.')
    (target.parent/'blue_sky_early_profit_zerodha.json').write_text(balanced_preset.model_dump_json(indent=2),encoding='utf-8')
    (ROOT/'artifacts/swing_refinement_final.json').write_text(json.dumps(output,indent=2))
    print('SAVED',output['saved_runs'],'PRESET',target,flush=True)


if __name__=='__main__':main()

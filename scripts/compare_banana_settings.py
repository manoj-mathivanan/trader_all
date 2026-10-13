"""Controlled frozen-input comparison; results are printed, never reported to files."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research import backtest, data_quality, fundamental_history, market_history, sector, store, strategy_presets
from core.research.config import BacktestConfig

VARIANTS = {
    'old': {},
    'stop8': {'stop_pct': 8},
    'sma50': {'winner_exit': 'trail_50d'},
    'rs': {'candidate_rank': 'rs_126'},
    'no_gates': {'sector_filter': 'off', 'skip_weak_markets': False},
    'ten_positions': {'max_positions': 10},
    'reference': {},
    'reference_fundamentals': {},
    'reference_next_open': {'entry_mode':'next_open'},
    'reference_conservative': {'reference_same_day':'conservative'},
    'reference_slippage': {'slippage_bps':10},
    'reference_paper': {'slippage_bps':10,'reference_same_day':'conservative'},
}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('variants', nargs='+', choices=VARIANTS)
    parser.add_argument('--fundamental-coverage',type=float,default=80)
    args = parser.parse_args()
    original = store.read('runs/6abcabe9224a')
    frozen = store.read('runs/b4584ee01955')
    data = store.read('run_data/b4584ee01955')
    hashes = {m['symbol']: m['sha256'] for m in frozen['manifest']}
    assert all(market_history.digest(bs) == hashes[s] for s, bs in data.items())
    quality = data_quality.audit(data, end='2026-09-30')
    data = data_quality.exclude_anomalies(data, quality, lambda _: None)
    prices = store.read('run_sector/6abcabe9224a')
    sector.verify(prices, original['sector_reference']['sha256'])
    financials = store.read('run_fundamentals/6abcabe9224a')
    assert financials['sha256'] == original['fundamental_reference']['sha256']
    for name in args.variants:
        if name.startswith('reference'):
            preset=next(p for p in strategy_presets.available() if p['name']=='Banana reference - Blue sky')
            cfg=BacktestConfig(**{**preset['backtest_defaults'],**VARIANTS[name]},start='2020-01-01',end='2026-09-30',acknowledge_limitations=True)
            scores=fundamental_history.Scores(financials,cfg.entry_mode)
            checks={'allowed':0,'blocked':0}
            def gate(symbol,day):
                score=scores(symbol,day)
                allowed=(score['score'] is not None and score['score']>=60 and score['coverage_pct']>=args.fundamental_coverage
                         and score.get('period_age_days') is not None and score['period_age_days']<=180
                         and not score['flags'])
                checks['allowed' if allowed else 'blocked']+=1
                return allowed
            result=backtest.simulate(data,cfg,entry_check=gate if name=='reference_fundamentals' else None)
            m=result['metrics']
            m['xirr_pct']=((m['final_equity']/cfg.capital)**(365/(cfg.end-cfg.start).days)-1)*100
            print(json.dumps({'variant':name,'stocks':len(data),'metrics':m,'financial_checks':checks,
                              'fundamental_min_coverage_pct':args.fundamental_coverage}),flush=True)
            continue
        values = {**original['config'], 'start': '2020-01-01', 'end': '2026-09-30',
                  'capital': 1000000, 'fee_model': 'custom_bps', 'buy_cost_bps': 25,
                  'sell_cost_bps': 25, 'slippage_bps': 0, 'comparison_run_id': None,
                  **VARIANTS[name]}
        cfg = BacktestConfig(**values)
        scores = fundamental_history.Scores(financials, cfg.entry_mode)
        result = backtest.simulate(data, cfg, liquidate=False,
            fundamental_scores=scores if cfg.candidate_rank == 'fundamental_score' else None,
            sector_gate=sector.Gate(prices, cfg.sector_filter) if cfg.sector_filter != 'off' else None,
            sector_instruments=frozen['universe_snapshot']['instruments'])
        m = result['metrics']
        m['xirr_pct'] = ((m['final_equity']/cfg.capital)**(365/(cfg.end-cfg.start).days)-1)*100
        print(json.dumps({'variant': name, 'stocks': len(data), 'metrics': m,
                          'rejections': result['entry_filter_rejections']}), flush=True)

if __name__ == '__main__':
    main()

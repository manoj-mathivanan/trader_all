"""Register saved combined strategy and four independent midday scenarios."""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.portfolio import manager, paper
from core.research import fundamentals, market_history, store, strategy_presets
from core.research.config import Settings, TradingConfig

SCENARIOS = {
    'sector_control_midday': ('Sector Control - Midday', 0, 0),
    'sector_rs70_midday': ('Sector RS70 - Midday', 70, 0),
    'sector_cap2_midday': ('Sector Cap2 - Midday', 0, 2),
    'sector_rs70_cap2_midday': ('Sector RS70 + Cap2 - Midday', 70, 2),
}


def main():
    original = store.read('runs/5cafe09b6cdc')
    frozen = store.read('run_data/5cafe09b6cdc')
    assert all(market_history.digest(frozen[m['symbol']]) == m['sha256'] for m in original['manifest'])
    values = {k: v for k, v in original['config'].items() if k in TradingConfig.model_fields}
    name = 'Blue Sky RS70 + Sector Cap2 - Zerodha'
    trading = TradingConfig(**{**values, 'name': name, 'min_short_rs_rating': 70, 'max_sector_positions': 2})
    screen = strategy_presets.ScreenInput(name=name, pattern='blue_sky', trading_defaults=trading,
        minimum_warmup_sessions=260, source_run_id=original['id'],
        description='Blue Sky with 63-session RS percentile >=70, sector breadth >=60% with >=80% history coverage, and at most two positions per sector. Original 8% stop, +15% closing target, +10% breakeven, 1.5% risk, five positions, Zerodha fees and 10 bps slippage retained. Exploratory inspected-period backtest returned 35.74% with 10.89% drawdown; not untouched validation. Paper midday execution is a separate quote-based scenario with sampled exits.')
    payload = screen.model_dump(mode='json')
    path = ROOT / 'strategies/swing_patterns/presets/blue_sky_rs70_sector_cap2_zerodha.json'
    path.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    saved = {**payload, 'id': strategy_presets.identity(name), 'created_at': store.now()}
    with store.LOCK:
        screens = [s for s in store.read('screens', []) if s['id'] != saved['id']]
        store.write('screens', [saved, *screens][:100])
    universe = {**original['universe_snapshot'], 'instruments': [i for i in original['universe_snapshot']['instruments'] if i['symbol'] in frozen]}
    settings = Settings(start='2018-10-01', end=paper.local_now().date())
    result = []
    for identity, (label, rs, cap) in SCENARIOS.items():
        existing = manager.get('swing_patterns', identity)
        if not existing:
            cfg = paper.PaperConfig(**{**values, 'name': label, 'min_short_rs_rating': rs, 'max_sector_positions': cap,
                                      'capital': 100000, 'execution_time': 'midday', 'run_hour': 12, 'run_minute': 30,
                                      'auto_run': True, 'sector_observe_only': False, 'acknowledge_limitations': True})
            existing = manager.save('swing_patterns', cfg, settings, create=True, clock=paper.local_now(),
                                     portfolio_id=identity, universe_snapshot=universe)
            existing.update(source_run_id=original['id'], fundamental_screen=fundamentals.buy_screen('swing_patterns').model_dump(),
                            inherited_exclusions=original.get('excluded', []))
            store.write(manager.key('swing_patterns', identity), existing)
        result.append(dict(id=identity, name=existing['config']['name'], start=existing['start_session'],
                           stocks=len(existing['universe_snapshot']['instruments']), capital=existing['config']['capital'],
                           execution=existing['config']['execution_time']))
    print(json.dumps(dict(screen=saved['name'], screen_id=saved['id'], scenarios=result), indent=2))


if __name__ == '__main__':
    main()

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from core.portfolio import manager, paper
from core.research import store, strategy_presets
from core.research.config import BacktestConfig, Settings


class WorkspaceScreenTests(unittest.TestCase):
    def test_retired_choices_are_removed_from_selection_but_replay_definitions_remain(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(store, 'DATA', Path(directory)):
            available = {preset['id'] for preset in strategy_presets.available()}
            selectable = {preset['id'] for preset in strategy_presets.selectable()}
            self.assertTrue(strategy_presets.RETIRED_PRESET_IDS.issubset(available))
            self.assertFalse(strategy_presets.RETIRED_PRESET_IDS & selectable)
            self.assertTrue(selectable)

    def test_screen_identity_round_trips_for_both_execution_models(self):
        for preset in strategy_presets.available():
            if not preset.get('backtest_defaults'):
                continue
            values = {**preset['backtest_defaults'], 'screen_id': preset['id'],
                      'acknowledge_limitations': True, 'start': '2025-01-01', 'end': '2025-12-31'}
            self.assertEqual(BacktestConfig(**values).screen_id, preset['id'])
            config = paper.PaperConfig(**{**preset['paper_defaults'], 'screen_id': preset['id'],
                                          'acknowledge_limitations': True})
            self.assertEqual(config.model_dump()['screen_id'], preset['id'])

    def test_multiple_screen_portfolios_retain_independent_settings_and_status(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(store, 'DATA', Path(directory)):
            settings = Settings(universe='niftytotalmarket', start='2025-01-01', end='2025-12-31')
            store.write('universes/niftytotalmarket', {'instruments': [{'isin': 'TEST'}]})
            store.write('bars/TEST', {'bars': [{'date': '2025-01-01', 'close': 100}]})
            common = dict(capital=100000, acknowledge_limitations=True)
            first = paper.PaperConfig(**common, name='First', screen_id='custom_a', pattern='vcp')
            second = paper.PaperConfig(**common, name='Second', screen_id='custom_b', pattern='blue_sky', risk_pct=1)
            for identity, config in [('first', first), ('second', second)]:
                manager.save('swing_patterns', config, settings, create=True,
                             clock=datetime(2026, 10, 15), portfolio_id=identity)
            manager.set_status('swing_patterns', 'paused', 'first')
            self.assertEqual(manager.get('swing_patterns', 'first')['status'], 'paused')
            other = manager.get('swing_patterns', 'second')
            self.assertEqual(other['status'], 'active')
            self.assertEqual(other['config']['screen_id'], 'custom_b')
            self.assertEqual(other['config']['pattern'], 'blue_sky')
            self.assertEqual(len(manager.list_portfolios('swing_patterns')), 2)


if __name__ == '__main__':
    unittest.main()

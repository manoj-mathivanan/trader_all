import copy
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from scripts import run_sector_forward_test as forward
from core.research import backtest, store
from core.research.config import BacktestConfig


class ForwardTest(unittest.TestCase):
    def test_signal_must_exist_before_open(self):
        capture = {'2026-10-12': {'signals': {'A': {}}, 'captured_at': '2026-10-12T16:45:00+05:30'}}
        self.assertTrue(forward.timely_capture(capture, 'A', '2026-10-12', '2026-10-13'))
        self.assertFalse(forward.timely_capture(capture, 'B', '2026-10-12', '2026-10-13'))
        self.assertFalse(forward.timely_capture(capture, 'A', '2026-10-12', '2026-10-12'))
        capture['2026-10-12']['captured_at'] = '2026-10-13T09:16:00+05:30'
        self.assertFalse(forward.timely_capture(capture, 'A', '2026-10-12', '2026-10-13'))

    def synthetic(self):
        rows = [dict(date=f'2026-10-{d:02}', open=100, high=101, low=99, close=100, volume=1000000) for d in (9, 12, 13)]
        return {s: copy.deepcopy(rows) for s in ('A', 'B', 'C', 'D')}

    def cfg(self):
        return BacktestConfig(start='2026-10-12', end='2026-10-13', capital=100000,
                              skip_weak_markets=False, candidate_rank='alphabetical',
                              max_positions=5, stop_pct=8, risk_pct=1.5, acknowledge_limitations=True)

    def test_instrumented_control_and_cap(self):
        data, cfg = self.synthetic(), self.cfg()
        sectors = {s: 'Finance' for s in data}
        with patch.object(backtest, 'signal', return_value=True):
            original = backtest.simulate(data, cfg, liquidate=False)
            audit = []
            control = forward.engine(0, sectors, audit)(data, cfg, liquidate=False)
            self.assertEqual(original, control)
            audit = []
            capped = forward.engine(2, sectors, audit)(data, cfg, liquidate=False)
        self.assertEqual(len(control['state']['positions']), 4)
        self.assertEqual(len(capped['state']['positions']), 2)
        self.assertTrue(any(a.get('reason') == 'Two positions in sector' for a in audit))

    def test_uncaptured_signals_never_fill(self):
        with patch.object(backtest, 'signal', return_value=True):
            result = forward.engine(0, {}, [])(self.synthetic(), self.cfg(), liquidate=False,
                                               entry_check=lambda s, d: False)
        self.assertEqual(result['state']['orders'], [])

    def test_duplicate_cycle_and_revision_guard(self):
        data = self.synthetic()
        data = {s: rows[:1] for s, rows in data.items()}
        p = {'code': forward.fingerprint(), 'instruments': [], 'history_reference': {}}
        record = {'protocol': p, 'protocol_sha256': forward.market_history.digest(p),
                  'verified_through': '2026-10-09', 'price_hashes': forward.hashes(data, '2026-10-09'),
                  'captures': {}, 'arms': {a: {'cash': 100000} for a in forward.ARMS}}
        p['decision_start'] = '2026-10-12'
        record['protocol_sha256'] = forward.market_history.digest(p)
        with tempfile.TemporaryDirectory() as tmp, patch.object(store, 'DATA', Path(tmp)), patch.object(forward, 'inputs', return_value=data):
            store.write(forward.KEY, record)
            before = (Path(tmp) / (forward.KEY + '.json')).read_bytes()
            now = datetime.fromisoformat('2026-10-11T16:45:00+05:30')
            self.assertEqual(forward.cycle(now)['result'], 'No new completed session')
            self.assertEqual((Path(tmp) / (forward.KEY + '.json')).read_bytes(), before)
            data['A'][0]['close'] = 99.5
            with self.assertRaisesRegex(ValueError, 'prices changed'):
                forward.cycle(now)
            self.assertEqual((Path(tmp) / (forward.KEY + '.json')).read_bytes(), before)

    def test_first_capture_then_next_session_entry(self):
        data = self.synthetic()
        instruments = [dict(symbol=s, isin=s, sector='Finance') for s in data]
        p = dict(code=forward.fingerprint(), instruments=instruments, history_reference={},
                 decision_start='2026-10-12', config=self.cfg().model_dump(mode='json'))
        record = dict(protocol=p, protocol_sha256=forward.market_history.digest(p),
                      verified_through='2026-10-09', price_hashes=forward.hashes(data, '2026-10-09'),
                      captures={}, audits=[], arms={a: {'cash': 100000, 'last_session': '2026-10-09'} for a in forward.ARMS})
        score = lambda s, d: {'score': 50, 'coverage_pct': 100, 'flags': []}
        with tempfile.TemporaryDirectory() as tmp, patch.object(store, 'DATA', Path(tmp)), \
                patch.object(backtest, 'signal', return_value=True), \
                patch.object(forward.fundamental_history, 'capture', return_value={'sha256': 'fixture'}), \
                patch.object(forward.fundamental_history, 'Scores', return_value=score):
            store.write(forward.KEY, record)
            with patch.object(forward, 'inputs', return_value={s: rows[:2] for s, rows in data.items()}):
                forward.cycle(datetime.fromisoformat('2026-10-12T16:45:00+05:30'))
            first = store.read(forward.KEY)
            self.assertEqual(len(first['captures']), 1)
            self.assertTrue(all(not s.get('orders') for s in first['arms'].values()))
            with patch.object(forward, 'inputs', return_value=data):
                forward.cycle(datetime.fromisoformat('2026-10-13T16:45:00+05:30'))
            second = store.read(forward.KEY)
            self.assertEqual(len(second['arms']['control']['positions']), 4)
            self.assertEqual(len(second['arms']['sector_cap2']['positions']), 2)


if __name__ == '__main__':
    unittest.main()

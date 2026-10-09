"""Downside predicates, completed-session cross-sectional gates and API validation."""
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from core.research import bearish, store, corporate_actions
from core.research.config import Settings
from core.research.config import BearishBacktestConfig
from dashboard.api.main import app


def history(count=281, rising=False):
    rows = []
    for i in range(count):
        price = 100 + i*.1 if rising else 200 - i*.1
        rows.append(dict(date=(date(2024, 1, 1)+timedelta(days=i)).isoformat(),
                         open=price, high=price+1, low=price-1, close=price, volume=1000000))
    rows[-1].update(open=160, high=161, low=158, close=159, volume=2000000)
    return rows


class BearishScreenTests(unittest.TestCase):
    def cfg(self, **values):
        return bearish.BearishConfig(min_turnover=0, **values)

    def test_new_low_and_multiyear_break_support_in_falling_trend(self):
        bars = history()
        for pattern in ('new_lows', 'multiyear_breakdown'):
            result = bearish.evaluate(bars, self.cfg(pattern=pattern))
            self.assertIsNotNone(result)
            self.assertLess(result['close'], result['breakdown_level'])
        bars[-1]['close'] = 200
        self.assertIsNone(bearish.evaluate(bars, self.cfg(pattern='new_lows')))

    def test_falling_long_trend_and_volume_are_required(self):
        bars = history(rising=True)
        bars[-1].update(open=90, high=91, low=88, close=89)
        self.assertIsNone(bearish.evaluate(bars, self.cfg(pattern='new_lows')))
        self.assertIsNotNone(bearish.evaluate(bars, self.cfg(pattern='new_lows', require_falling_long_trend=False)))
        bars = history()
        bars[-1]['volume'] = 100
        self.assertIsNone(bearish.evaluate(bars, self.cfg(pattern='new_lows')))

    def test_vcp_contracts_before_downside_break(self):
        bars = history()
        for start, spread, volume in ((250, 8, 1200000), (260, 4, 800000), (270, 2, 400000)):
            for row in bars[start:start+10]:
                row.update(open=170, close=170, high=170+spread, low=170-spread, volume=volume)
        self.assertIsNotNone(bearish.evaluate(bars, self.cfg()))
        bars[-1]['close'] = 171
        self.assertIsNone(bearish.evaluate(bars, self.cfg()))

    def test_ipo_metadata_age_and_base_depth(self):
        bars = history()
        cfg = self.cfg(pattern='ipo_breakdown')
        self.assertIsNone(bearish.evaluate(bars, cfg))
        bars[0]['listing_metadata'] = dict(verified=True, source='fixture', ipo_verified=True,
                                          listing_date='2024-01-01', ipo_date='2024-01-01')
        self.assertIsNotNone(bearish.evaluate(bars, cfg))
        self.assertIsNone(bearish.evaluate(bars, self.cfg(pattern='ipo_breakdown', ipo_max_age_days=30)))
        self.assertIsNone(bearish.evaluate(bars, self.cfg(pattern='ipo_breakdown', max_depth_pct=.1)))

    def test_scan_ranks_weak_symbols_and_rejects_low_coverage(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(store, 'DATA', Path(folder)):
            items = [dict(symbol=s, name=s, isin=s) for s in ('WEAK', 'LESS_WEAK', 'STALE', 'MISSING')]
            store.write('universes/niftytotalmarket', dict(instruments=items))
            weak = history()
            less_weak = history()
            less_weak[-1].update(close=165, low=164, high=166, open=165)
            for s, bars in [('WEAK', weak), ('LESS_WEAK', less_weak), ('STALE', weak[:-1])]:
                store.write('bars/'+s, dict(bars=bars))
            # Exercise the production scan and adjustment path; only metadata sourcing is isolated.
            with patch.object(bearish.market_history, 'evidence', return_value=dict(local_metadata_frozen=True)):
                result = bearish.scan(Settings(), self.cfg(pattern='new_lows'))
                self.assertFalse(result['market_gate_passed'])
                self.assertEqual(result['market_coverage_pct'], 50)
                self.assertEqual(result['matches'], [])
                result = bearish.scan(Settings(), self.cfg(pattern='new_lows', market_min_coverage_pct=50))
            self.assertEqual([x['symbol'] for x in result['matches']], ['WEAK'])
            self.assertEqual(result['matches'][0]['rs_rating'], 0)
            self.assertEqual({x['symbol'] for x in result['excluded']}, {'STALE', 'MISSING'})
            self.assertEqual(store.read('bars/WEAK')['bars'], weak)

    def test_api_validates_bearish_pattern_and_does_not_queue_trades(self):
        client = TestClient(app)
        headers = {'X-Trader-Request': 'local-ui'}
        self.assertEqual(client.post('/api/bearish/scan', json=dict(pattern='vcp'), headers=headers).status_code, 422)
        with patch.object(bearish, 'scan', return_value=dict(matches=[], as_of='2024-10-07')) as scan:
            response = client.post('/api/bearish/scan', json=dict(pattern='new_lows'), headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(scan.call_args.args[1].pattern, 'new_lows')

    def test_backtest_endpoint_accepts_bearish_config_as_short_research(self):
        client = TestClient(app)
        with patch('dashboard.api.main.backtest.prepare') as prepare, patch('dashboard.api.main.jobs.submit', return_value=dict(id='123456abcdef',status='queued')):
            response = client.post('/api/jobs/backtest', headers={'X-Trader-Request':'local-ui'},
                                   json=dict(pattern='new_lows',start='2025-02-01',end='2026-10-01',acknowledge_limitations=True))
        self.assertEqual(response.status_code,200)
        self.assertIsInstance(prepare.call_args.args[1],BearishBacktestConfig)

    def test_today_and_future_bars_do_not_enter_scan(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(store, 'DATA', Path(folder)):
            store.write('universes/niftytotalmarket', dict(instruments=[dict(symbol='A', name='A', isin='A')]))
            bars = history()
            expected = bars[-1]['date']
            bars += [dict(date='2024-10-08', open=300, high=301, low=299, close=300, volume=1000000),
                     dict(date='2024-10-09', open=400, high=401, low=399, close=400, volume=1000000)]
            store.write('bars/A', dict(bars=bars))
            with patch.object(bearish.market_history, 'evidence', return_value=dict(local_metadata_frozen=True)), patch.object(bearish, 'datetime') as clock:
                clock.now.return_value = datetime(2024, 10, 8, 12, tzinfo=timezone(timedelta(hours=5, minutes=30)))
                result = bearish.scan(Settings(), self.cfg(pattern='new_lows'))
            self.assertEqual(result['as_of'], expected)
            self.assertEqual(result['matches'][0]['close'], 159)

    def test_verified_split_is_not_a_false_breakdown(self):
        bars = history()
        bars[-1].update(open=86, high=87, low=85, close=86)
        cfg = self.cfg(pattern='new_lows')
        self.assertIsNotNone(bearish.evaluate(bars, cfg))
        bars = corporate_actions.attach(bars, [dict(id='split', kind='split', ex_date=bars[-1]['date'],
                                                   share_factor=2, price_basis='raw', volume_basis='raw',
                                                   verified=True, source='fixture', basis_source='fixture')])
        adjusted = corporate_actions.adjusted_bars(bars, bars[-1]['date'])
        self.assertIsNone(bearish.evaluate(adjusted, cfg))


if __name__ == '__main__':
    unittest.main()

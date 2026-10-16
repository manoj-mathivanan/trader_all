import unittest
from datetime import date, timedelta
from core.research import scalping, scalping_selection


def daily_rows(scale=1):
    return [dict(date=str(date(2025, 1, 1)+timedelta(days=i)), open=100+i*scale,
                 high=102+i*scale, low=98+i*scale, close=100+i*scale, volume=1000000)
            for i in range(30)]


class SelectionTests(unittest.TestCase):
    def test_score_bounds_and_prior_context(self):
        rows = daily_rows()
        score = scalping_selection.score(rows[:25], 1e8, 5e7)
        self.assertGreaterEqual(score['total'], 0)
        self.assertLessEqual(score['total'], 100)
        self.assertEqual(score['as_of'], rows[24]['date'])
        self.assertAlmostEqual(score['total'], sum(score['components'].values()), places=5)

    def test_current_and_future_prices_cannot_change_selection(self):
        rows = daily_rows()
        day = rows[25]['date']
        cfg = scalping.ScalpingConfig(start=day, end='2025-02-01', stock_selection='score',
                                    liquid_universe_size=1, max_positions=1, acknowledge_limitations=True)
        original, _ = scalping.entry_plan({'A': rows}, cfg, days=[day])
        modified = [dict(b) for b in rows]
        for b in modified[25:]:
            b.update(close=1e6, high=1e6, low=1, volume=1e12)
        revised, _ = scalping.entry_plan({'A': modified}, cfg, days=[day])
        self.assertEqual(original, revised)
        threshold = cfg.model_copy(update={'min_stock_score': 100})
        rejected, _ = scalping.entry_plan({'A': rows}, threshold, days=[day])
        self.assertEqual(rejected[day], [])

    def test_rank_limit_and_deterministic_ties(self):
        rows = daily_rows()
        day = rows[25]['date']
        cfg = scalping.ScalpingConfig(start=day, end='2025-02-01', stock_selection='score',
                                    liquid_universe_size=1, max_positions=1, acknowledge_limitations=True)
        plan, _ = scalping.entry_plan({'B': rows, 'A': rows}, cfg, days=[day])
        self.assertEqual([c['symbol'] for c in plan[day]], ['A'])


if __name__ == '__main__':
    unittest.main()

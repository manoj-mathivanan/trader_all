from contextlib import nullcontext, redirect_stdout
from datetime import date
import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.pull_niftybees_history import compare
from scripts.pull_nifty_minute_history import persisted_sessions


class NiftyBeesTests(unittest.TestCase):
    def test_persisted_sessions_queries_requested_isin(self):
        with patch('scripts.pull_nifty_minute_history.pg.connection') as connection:
            connection.return_value.execute.return_value.fetchall.return_value = []
            persisted_sessions(date(2024,10,1),date(2024,10,2),'ETF_ISIN')
            parameters = connection.return_value.execute.call_args.args[1]
            self.assertEqual(parameters[1], 'ETF_ISIN')

    def test_comparison_distinguishes_price_scale_and_excludes_overnight_returns(self):
        instrument = dict(isin='ETF_ISIN',symbol='NIFTYBEES')
        def record(stamps, values):
            return {'bars':[dict(timestamp=s,close=v,time='15:29') for s,v in zip(stamps,values)]}
        etf = {'2024-10-01':record([0,60000,120000],[100,101,103]),
               '2024-10-02':record([86400000,86460000],[102,104])}
        index = {'2024-10-01':record([0,60000,120000],[10000,10100,10300]),
                 '2024-10-02':record([86400000,86460000],[10200,10400])}
        with TemporaryDirectory() as directory, \
                patch('scripts.pull_niftybees_history.persisted_sessions',side_effect=[etf,index]), \
                patch('scripts.pull_niftybees_history.pg.transaction',return_value=nullcontext()), \
                patch('scripts.pull_niftybees_history.store.write') as write, \
                redirect_stdout(io.StringIO()):
            report = compare(date(2024,10,1),date(2024,10,2),instrument,Path(directory)/'comparison.json')
        self.assertFalse(report['same_price'])
        self.assertEqual(report['matched_minute_candles'],5)
        self.assertEqual(report['consecutive_within_session_return_pairs'],3)
        self.assertEqual(report['index_to_etf_price_ratio'],dict(min=100,median=100,max=100))
        self.assertAlmostEqual(report['one_minute_return_correlation'],1)
        self.assertTrue(write.called)


if __name__ == '__main__':
    unittest.main()

import unittest

from core.research import candle_rejection, candle_continuation
from scripts.diagnose_candle_strategies import attribution, zero_replay, select_samples
from tests import test_candle_continuation as fixtures


class DiagnosticTests(unittest.TestCase):
    def test_fixed_ledger_attribution_is_exact(self):
        raw_entry,entry,raw_exit,exit,qty,fees=100,100.05,101,100.9495,100,5
        slip=(entry-raw_entry+raw_exit-exit)*qty
        pnl=(exit-entry)*qty-fees
        result=dict(metrics=dict(initial_capital=10000),trades=[dict(direction='long',raw_entry=raw_entry,entry=entry,
                    raw_exit=raw_exit,exit=exit,quantity=qty,fees=fees,slippage=slip,pnl=pnl,
                    reason='target',entry_timestamp=0,exit_timestamp=300000)])
        row=attribution(result)
        self.assertAlmostEqual(row['raw_price_pnl'],100)
        self.assertAlmostEqual(row['net_pnl']+row['fees']+row['slippage'],100)

    def test_zero_replay_overrides_both_fee_boundaries_and_restores(self):
        fixture=fixtures.ContinuationTests()
        fixture.setUp()
        fixture.bars[4].update(low=100.9)
        inputs=dict(sessions={'A':{'2025-01-02':fixture.bars}},plan={'2025-01-02':[fixture.context]})
        original_first=candle_rejection.upstox_cash_fees
        original_second=candle_continuation.upstox_cash_fees
        original_fill=candle_continuation.limit_fill
        for family,variant in [('rejection','level'),('continuation','gap_retest')]:
            result=zero_replay(inputs,family,variant,1,fixture.rules)
            self.assertEqual(result['metrics']['fees'],0)
            self.assertEqual(result['metrics']['slippage'],0)
        self.assertIs(candle_rejection.upstox_cash_fees,original_first)
        self.assertIs(candle_continuation.upstox_cash_fees,original_second)
        self.assertIs(candle_continuation.limit_fill,original_fill)

    def test_zero_replay_preserves_limit_penetration(self):
        fixture=fixtures.ContinuationTests()
        fixture.setUp()
        # Touching the limit is insufficient under the retained 5bps rule.
        fixture.bars[4].update(low=101)
        inputs=dict(sessions={'A':{'2025-01-02':fixture.bars}},plan={'2025-01-02':[fixture.context]})
        result=zero_replay(inputs,'continuation','gap_retest',1,fixture.rules)
        self.assertEqual(result['trades'],[])

    def test_sample_selection_independent_of_trade_order(self):
        records=[]
        for variant in ('level','rejection','confirmation','weak_pullback','gap_retest'):
            for direction in ('long','short'):
                trades=[dict(symbol=s,date='2025-01-02',entry_timestamp=i,pnl=p) for i,(s,p) in enumerate([('A',1),('B',2),('C',-1),('D',-2)])]
                records.append(dict(variant=variant,direction=direction,window='full',result=dict(trades=trades,order_ledger=[])))
        first=select_samples(records)
        for row in records:
            row['result']['trades'].reverse()
        self.assertEqual(first,select_samples(records))
        self.assertEqual(len(first),20)


if __name__=='__main__':
    unittest.main()

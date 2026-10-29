import unittest

from core.research import candle_continuation, candle_rejection
from scripts.research_candle_passive import provider,run,verify_control
from tests import test_candle_rejection as fixtures


class PassiveTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.CandleRejectionTests()
        fixture.setUp()
        self.bars=[dict(b,open=200-b['open'],close=200-b['close'],high=200-b['low'],low=200-b['high']) for b in fixture.bars]
        self.context=dict(fixture.context,previous_high=100,previous_low=95)
        self.inputs=dict(sessions={'A':{'2025-01-02':self.bars}},plan={'2025-01-02':[self.context]})

    def test_original_control_reproduces(self):
        expected=candle_rejection.simulate(self.inputs['sessions'],self.inputs['plan'],'rejection',-1,5)
        control=run(self.inputs,'market',5)
        verify_control(expected,control)

    def test_passive_price_and_lifetime_known_at_submission(self):
        orders=provider('passive')(self.bars,self.context,'ignored',-1,candle_rejection.Rules())
        setup=orders[3]
        self.assertEqual(setup['limit'],self.bars[2]['close'])
        self.assertEqual(setup['active_index'],3)
        self.assertEqual(setup['expires_index'],5)
        self.bars[40].update(high=500)
        self.assertEqual(orders[3],provider('passive')(self.bars,self.context,'ignored',-1,candle_rejection.Rules())[3])

    def test_provider_restored_after_run(self):
        original=candle_continuation.orders
        result=run(self.inputs,'passive',5)
        self.assertIs(candle_continuation.orders,original)
        for trade in result['trades']:
            self.assertEqual(trade['entry'],trade['limit'])
            self.assertGreater(trade['fees'],0)

    def test_control_tolerates_roundoff_but_rejects_changed_quantity(self):
        import copy
        expected=candle_rejection.simulate(self.inputs['sessions'],self.inputs['plan'],'rejection',-1,5)
        changed=copy.deepcopy(expected)
        changed['trades'][0]['pnl']+=1e-12
        verify_control(expected,changed)
        changed['trades'][0]['quantity']+=1
        with self.assertRaises(ValueError):
            verify_control(expected,changed)


if __name__=='__main__':
    unittest.main()

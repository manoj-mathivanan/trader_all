import copy
from datetime import date
import unittest

from core.research import four_indicator_swing as fs
from scripts.research_four_indicator_selection import Plan, SelectionFeatures, simulate
from tests.test_four_indicator_swing import rows


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.rows = rows()
        self.data = {'A':copy.deepcopy(self.rows),'B':copy.deepcopy(self.rows)}
        self.items = [dict(symbol=s,sector='IT') for s in self.data]
        self.index = [dict(b,close=100+i*.1) for i,b in enumerate(self.rows)]
        self.cfg = fs.SwingConfig(start=self.rows[100]['date'],end=self.rows[-1]['date'],capital=100000,max_positions=2)
        self.signals = {s:[dict(close=b['close'],exit=False,checks=[dict(passed=i == 100,value=100) for _ in range(4)])
                           for i,b in enumerate(self.rows)] for s in self.data}

    def features(self):
        return SelectionFeatures(self.data,self.index,self.items,self.cfg)

    def test_baseline_matches_shared_engine_fees_exits_and_cash(self):
        for cfg in (self.cfg,self.cfg.model_copy(update={'end':date.fromisoformat(self.rows[105]['date'])}),
                    self.cfg.model_copy(update={'start':date.fromisoformat(self.rows[101]['date'])})):
            expected = fs.simulate(self.data,self.signals,cfg,fs.RULES[3],instruments=self.items)
            actual = simulate(self.data,self.signals,cfg,self.features(),Plan())
            self.assertEqual(actual['curve'],expected['curve'])
            self.assertEqual(actual['metrics'],expected['metrics'])

    def test_relative_strength_same_dates_and_future_data_does_not_change_it(self):
        feature = self.features()
        expected = ((self.rows[100]['close']/self.rows[37]['close'])/(self.index[100]['close']/self.index[37]['close'])-1)*100
        self.assertEqual(feature.values['A'][100]['rs63'],expected)
        self.data['A'][-1]['close'] *= 20
        self.index[-1]['close'] *= 20
        self.assertEqual(feature.values['A'][100],self.features().values['A'][100])
        self.assertIsNone(feature.values['A'][100]['rs126'])

    def test_paper_marked_equity_and_open_positions_match_engine(self):
        expected = fs.simulate(self.data,self.signals,self.cfg,fs.RULES[3],instruments=self.items,liquidate=False)
        actual = simulate(self.data,self.signals,self.cfg,self.features(),Plan(),liquidate=False)
        self.assertEqual(actual['curve'],expected['curve'])
        self.assertEqual(actual['metrics'],expected['metrics'])
        self.assertEqual(actual['ledger']['cash'],expected['ledger']['cash'])
        self.assertEqual(set(actual['ledger']['positions']),set(expected['ledger']['positions']))
        self.assertEqual(len(actual['trades']),0)

    def test_lower_slot_scale_reduces_exposure_without_changing_entry_rules(self):
        full = simulate(self.data,self.signals,self.cfg,self.features(),Plan(),liquidate=False)
        reduced = simulate(self.data,self.signals,self.cfg,self.features(),Plan(),liquidate=False,slot_scale=.75)
        self.assertEqual(set(full['ledger']['positions']),set(reduced['ledger']['positions']))
        self.assertLess(reduced['metrics']['average_exposure_pct'],full['metrics']['average_exposure_pct'])
        self.assertGreater(reduced['ledger']['cash'],full['ledger']['cash'])

    def test_mixed_recorded_fee_schedule_keeps_old_entries_and_new_exit_fees(self):
        from core.execution.upstox import equity_charges
        for s in self.signals: self.signals[s][103]['exit']=True
        schedule=[dict(start=self.rows[100]['date'],end=self.rows[102]['date'],mode='legacy_bps'),
                  dict(start=self.rows[103]['date'],end=self.rows[-1]['date'],mode='upstox_plus')]
        result=simulate(self.data,self.signals,self.cfg,self.features(),Plan(),fee_schedule=schedule)
        for o in result['orders']:
            expected=(o['price']*o['quantity']*.001 if o['side']=='BUY' else
                      equity_charges(o['price'],o['quantity'],'sell',o['date'])['total'])
            self.assertEqual(o['fees'],expected)
        self.assertEqual(result['metrics']['modeled_fees'],sum(o['fees'] for o in result['orders']))

    def test_incomplete_fee_schedule_does_not_silently_use_other_costs(self):
        schedule=[dict(start=self.rows[102]['date'],end=self.rows[-1]['date'],mode='legacy_bps')]
        with self.assertRaisesRegex(ValueError,'fee schedule'):
            simulate(self.data,self.signals,self.cfg,self.features(),Plan(),fee_schedule=schedule)

    def test_missing_benchmark_endpoint_is_unknown_not_forward_filled(self):
        self.index.pop(37)
        feature = self.features()
        self.assertIsNone(feature.values['A'][100]['rs63'])
        reason,_ = feature.assess('A',100,self.rows[101]['open'],self.signals['A'][100],{},Plan(require_rs63=True))
        self.assertEqual(reason,'rs63_not_positive_or_unknown')

    def test_extension_and_positive_opening_gap_use_signal_atr_only(self):
        feature = self.features()
        signal = self.signals['A'][100]
        atr = feature.values['A'][100]['atr']
        close = self.rows[100]['close']
        signal['checks'][0]['value'] = close-3.1*atr
        reason,evidence = feature.assess('A',100,close,signal,{},Plan(extension_atr=3))
        self.assertEqual(reason,'extension_exceeded_or_unknown')
        self.assertAlmostEqual(evidence['extension_atr'],3.1)
        reason,_ = feature.assess('A',100,close+atr*1.1,signal,{},Plan(gap_atr=1))
        self.assertEqual(reason,'opening_gap_exceeded_or_unknown')
        reason,_ = feature.assess('A',100,close-atr*2,signal,{},Plan(gap_atr=1))
        self.assertIsNone(reason)

    def test_correlation_blocks_same_open_selection_and_ignores_future_returns(self):
        feature = self.features()
        self.assertAlmostEqual(feature.correlation('A','B',self.rows[100]['date']),1)
        result = simulate(self.data,self.signals,self.cfg,feature,Plan(correlation_limit=.8))
        self.assertEqual(len(result['trades']),1)
        self.assertEqual(result['rejections']['correlation_limit'],1)
        self.data['B'][-1]['close'] *= 10
        self.assertEqual(feature.correlation('A','B',self.rows[100]['date']),
                         self.features().correlation('A','B',self.rows[100]['date']))

    def test_missing_returns_reject_new_entry_with_holdings(self):
        self.data['B'].pop(70)
        feature = self.features()
        self.assertIsNone(feature.correlation('A','B',self.rows[100]['date']))
        reason,_ = feature.assess('A',100,self.rows[101]['open'],self.signals['A'][100],{'B':{}},Plan(correlation_limit=.8))
        self.assertEqual(reason,'correlation_unknown')

    def test_sector_proxy_excludes_candidate_and_requires_peer_coverage(self):
        for s in ('C','D'):
            self.data[s] = copy.deepcopy(self.rows)
            self.items.append(dict(symbol=s,sector='IT'))
        feature = self.features()
        value = feature.sector_strength('A',self.rows[100]['date'])
        self.assertEqual(value['eligible'],3)
        self.assertAlmostEqual(value['excess_return_pct'],feature.values['B'][100]['rs63'])
        for b in self.data['A'][:101]: b['close'] *= 2
        self.assertEqual(value,self.features().sector_strength('A',self.rows[100]['date']))
        self.data.pop('D')
        self.assertIsNone(self.features().sector_strength('A',self.rows[100]['date'])['excess_return_pct'])

    def test_rs_ranking_orders_known_values_first(self):
        for i,b in enumerate(self.data['B']): b['close'] += i
        feature = self.features()
        self.assertLess(feature.rank('B',100,Plan(rank_sessions=63)),feature.rank('A',100,Plan(rank_sessions=63)))
        self.assertEqual(feature.rank('A',100,Plan(rank_sessions=126))[0],True)


if __name__ == '__main__':
    unittest.main()

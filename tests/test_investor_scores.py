import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
import httpx
from core.research import investor_scores as scores,investor_details as details,investor_intelligence as intel,investor_workflow as workflow,store


class ScoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.data=patch.object(store,'DATA',Path(self.temp.name));self.data.start()
        self.now=intel.company.utcnow()
        self.item=dict(isin='INE000A01001',symbol='EXAMPLE',name='Example Industries')
        day=(self.now.astimezone(intel.company.IST).date()-timedelta(days=1)).isoformat()
        self.row=dict(company=self.item,isin=self.item['isin'],kind='candidate',stage='early_breakout',pivot=100,price_date=day,stop_price=98,target_price=114)
        f=dict(sector='Manufacturing',statement_basis='consolidated',metrics=dict(revenue=dict(value=1000,period='Mar 2026',annual_yoy_pct=25),net_profit=dict(value=100,period='Mar 2026',quarterly=dict(value=20,period='Jun 2026')),operating_cash_flow=dict(value=150,period='Mar 2026')),ratios={'P/E':dict(company=15,sector=20),'Debt/Equity':dict(company=.4)})
        t=dict(status='available',close=102,price_date=day,trend='bullish',rsi14=60,volume_ratio=2,moving_averages={'50':100},price_behaviour=dict(relative_strength60_pp=15,max_drawdown60_pct=-3,volatility20_annual_pct=22,turnover20_rupees=1e8))
        self.snapshot=dict(as_of=self.now.isoformat(),fundamentals=f,technical=t,quote=dict(last_trade_time=self.now.timestamp()*1000,last_price=102))
        a=dict(id='a',text='Company order announcement',published_at=self.now.isoformat(),sha256='headline')
        review=dict(id='r',full_text=True,as_of=self.now.isoformat(),articles=[dict(a,full_document_sha256='body')],article_summaries=[dict(article_id='a')],news_input_sha256=workflow.news_digest([a]),events=[dict(direction='positive',materiality='high',citations=[dict(article_id='a',excerpt='Company order announcement')])])
        self.evidence=dict(articles=[a],review=review)
        store.write('investor/full_articles/a',dict(status='available',response_sha256='body'))

    def tearDown(self):self.data.stop();self.temp.cleanup()
    def evaluate(self):return scores.evaluate(self.row,self.evidence,self.snapshot)

    def test_weights_complete_buy_and_observation_only(self):
        r=self.evaluate()
        self.assertEqual(scores.WEIGHTS,dict(fundamentals=40,price_behaviour=20,technicals=20,news=20))
        self.assertEqual(r['decision'],'buy_candidate');self.assertGreater(r['score'],75)
        self.assertEqual(r['confidence'],100);self.assertFalse(r['model']['validated'])
        self.assertTrue(r['advisory_only']);self.assertEqual(r['model']['execution_mode'],'paper_observation')

    def test_nonpositive_equity_is_hard_veto(self):
        self.snapshot['fundamentals']['metrics']['balance_equity']=dict(value=-1,period='Mar 2026')
        self.assertEqual(self.evaluate()['decision'],'avoid')
        self.row['kind']='holding'
        self.assertEqual(self.evaluate()['decision'],'exit_candidate')

    def test_unknown_retains_weight_and_cannot_buy(self):
        self.snapshot['fundamentals']['ratios'].pop('Debt/Equity')
        r=self.evaluate();self.assertIsNone(r['score']);self.assertEqual(r['decision'],'insufficient_evidence')
        self.assertAlmostEqual(r['range'][1]-r['range'][0],8,places=2)
        self.assertEqual(r['components']['fundamentals']['confidence'],80)

    def test_quiet_stock_neutral_but_failed_coverage_unknown(self):
        self.evidence=dict(articles=[],news_coverage=dict(status='no_relevant_news_found'))
        r=self.evaluate();self.assertEqual(r['components']['news']['score'],50);self.assertEqual(r['decision'],'buy_candidate')
        self.evidence['news_coverage']['status']='coverage_incomplete'
        r=self.evaluate();self.assertIsNone(r['components']['news']['score']);self.assertNotEqual(r['decision'],'buy_candidate')

    def test_material_adverse_overrides_high_other_scores_only_with_full_body(self):
        self.evidence['review']['events'][0]['direction']='negative'
        self.assertEqual(self.evaluate()['decision'],'avoid')
        store.write('investor/full_articles/a',dict(status='paywalled'))
        self.assertEqual(self.evaluate()['decision'],'insufficient_evidence')

    def test_risk_plan_quote_and_unconfirmed_entry_cannot_buy(self):
        self.row['target_price']=None;self.assertEqual(self.evaluate()['decision'],'wait')
        self.row['target_price']=114;self.snapshot['quote']['last_trade_time']-=600_000
        self.assertEqual(self.evaluate()['decision'],'wait')
        self.snapshot['quote']['last_trade_time']=self.now.timestamp()*1000
        self.row['stage']='approaching_breakout';self.assertEqual(self.evaluate()['decision'],'wait')
        self.row['stage']='early_breakout';self.snapshot['quote']['last_price']=130
        self.assertEqual(self.evaluate()['decision'],'wait')

    def test_known_cash_flow_failure_is_not_averaged_away(self):
        self.snapshot['fundamentals']['metrics']['operating_cash_flow']['value']=-1
        self.assertEqual(self.evaluate()['decision'],'wait')

    def test_holding_does_not_require_new_entry_and_context_must_match(self):
        self.row.update(kind='holding',thesis='Profitable growth',entry_date='2026-10-01',stage=None)
        self.assertEqual(self.evaluate()['decision'],'hold')
        self.evidence['review'].update(thesis_assessment=dict(status='challenged',citations=[dict(article_id='a')]),context=dict(thesis='Different thesis',entry_date='2026-10-01'))
        self.assertEqual(self.evaluate()['decision'],'hold')
        self.evidence['review']['context']['thesis']='Profitable growth'
        self.assertEqual(self.evaluate()['decision'],'exit_candidate')

    def test_stale_financial_period_blocks_even_with_recent_retrieval(self):
        self.snapshot['fundamentals']['metrics']['net_profit']['quarterly']['period']='Mar 2016'
        r=self.evaluate();self.assertIsNone(r['components']['fundamentals']['score']);self.assertEqual(r['decision'],'insufficient_evidence')

    def test_forward_observation_starts_after_recording_and_includes_costs(self):
        record=dict(as_of='2026-10-01T16:00:00+05:30',observation=dict(cost_bps=50))
        t=dict(status='available',observation_bars=[dict(date='2026-10-01',open=1,close=1)])
        self.assertEqual(scores.outcomes(record,t)['status'],'pending')
        t['observation_bars'] += [dict(date=f'2026-10-{d:02}',open=100,close=100+d) for d in range(2,7)]
        r=scores.outcomes(record,t)
        self.assertEqual(r['entry_date'],'2026-10-02');self.assertEqual(r['entry_price'],100)
        self.assertAlmostEqual(r['returns']['5']['net_return_pct'],5.5)
        t['observation_bars']=t['observation_bars'][1:]
        self.assertEqual(scores.outcomes(record,t)['status'],'unavailable')

    def test_save_preserves_version_evidence_and_no_trading_state(self):
        store.write('paper/positions',dict(unchanged=True))
        r=scores.save(self.row,self.evaluate(),self.snapshot)
        self.assertEqual(scores.history(self.item['isin'])[0]['id'],r['id'])
        self.assertTrue(r['details_sha256']);self.assertEqual(store.read('paper/positions'),dict(unchanged=True))
        from scripts.sync_investor_data import bundle
        self.assertTrue(any(d['kind']=='assessments' and d['id'].startswith('score-history-') for d in bundle(store.DATA)['documents']))

    def test_completed_outcome_survives_rolling_history_expiry(self):
        record=dict(id='completed',as_of='2026-09-01T16:00:00+05:30',observation=dict(cost_bps=50))
        bars=[dict(date=f'2026-09-{d:02}',open=100,close=100+d) for d in range(1,22)]
        result=scores.outcomes(record,dict(status='available',price_date='2026-09-21',observation_bars=bars))
        self.assertEqual(result['status'],'complete')
        store.write('investor/assessments/score-outcome-completed',dict(result,recommendation_id='completed'))
        self.assertEqual(scores.outcomes(record,{})['returns'],result['returns'])

    def test_future_bars_cannot_create_forward_results(self):
        day=self.now.astimezone(intel.company.IST).date()
        record=dict(as_of=self.now.isoformat())
        bars=[dict(date=(day+timedelta(days=d)).isoformat(),open=100,close=110) for d in range(22)]
        self.assertEqual(scores.outcomes(record,dict(status='available',observation_bars=bars))['status'],'pending')


    def test_nonpositive_sector_pe_uses_explicit_ev_ebitda(self):
        self.snapshot['fundamentals']['ratios']['P/E']['sector']=-10
        self.snapshot['fundamentals']['ratios']['EV/EBITDA']=dict(company=10,sector=12)
        r=self.evaluate()
        self.assertIsNotNone(r['components']['fundamentals']['score'])
        self.assertTrue(any('EV/EBITDA' in reason for reason in r['reasons']))
    def test_stale_supplement_does_not_become_fresh_on_snapshot_refresh(self):
        self.snapshot['fundamentals']['ratios']['Debt/Equity']['source']='https://www.screener.in/company/EXAMPLE/'
        self.snapshot['sections']={'financial_supplement':dict(status='available',as_of=(self.now-timedelta(days=2)).isoformat())}
        r=self.evaluate()
        self.assertIsNone(r['components']['fundamentals']['score'])
        self.assertNotEqual(r['decision'],'buy_candidate')


class StatementFallbackTests(unittest.TestCase):
    setUp=ScoreTests.setUp
    tearDown=ScoreTests.tearDown
    def test_standalone_uses_entire_family_and_preserves_consolidated(self):
        def handler(r):
            standalone=r.url.params.get('type')=='standalone'
            value={}
            if r.url.path.endswith('income-statement'):
                period='Jun 2026' if r.url.params.get('time_period')=='quarterly' else 'Mar 2026'
                value=dict(type='standalone' if standalone else 'consolidated',income_statement=[dict(category=c,history=[dict(value=100 if c=='revenue' else 10,period=period),dict(value=90 if c=='revenue' else 9,period='Mar 2025')]) for c in ('revenue','net_profit','operating_profit')] if standalone else [])
            elif r.url.path.endswith('cash-flow'):value=dict(type='standalone',cash_flow=[dict(category='operating',history=[dict(value=15,period='Mar 2026')])]) if standalone else {}
            elif r.url.path.endswith('balance-sheet'):value=dict(type='standalone',history=[dict(period='Mar 2026')]) if standalone else {}
            elif r.url.path.endswith(('key-ratios','share-holdings','corporate-actions','competitors')):value=[]
            return httpx.Response(200,json=dict(status='success',data=value))
        with patch.object(store,'token',return_value='fixture-secret'),patch.object(details,'technical',return_value={}):
            details.refresh([self.item],transport=httpx.MockTransport(handler))
        r=store.read('investor/stock_details/'+self.item['isin'])
        self.assertEqual(r['statement_basis'],'standalone');self.assertEqual(r['fundamentals']['statement_basis'],'standalone')
        self.assertTrue(all(r['sections'][k]['statement_basis']=='standalone' for k in ('annual_income','quarterly_income','cash_flow','balance_sheet')))
        self.assertEqual(r['statement_alternatives']['consolidated']['annual_income']['data']['income_statement'],[])
        self.assertAlmostEqual(r['fundamentals']['metrics']['revenue']['annual_yoy_pct'],100/90*100-100)

    def test_growth_requires_same_basis_adjacent_years(self):
        rows=[dict(value=100,period='Mar 2026'),dict(value=50,period='Mar 2024')]
        r=details.financial_summary(dict(annual_income=dict(data=dict(type='standalone',income_statement=[dict(category='revenue',history=rows)]))))
        self.assertIsNone(r['metrics']['revenue']['annual_yoy_pct'])



if __name__=='__main__':unittest.main()

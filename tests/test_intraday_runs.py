import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import ValidationError
from core.research import intraday_runs, intraday_target, store
from dashboard.api.intraday_backtests import router
from dashboard.shared import create_app
import httpx
from tests.test_intraday_target import session


class IntradayRunTests(unittest.TestCase):
    def test_submit_creates_a_readable_jobs_screen_entry(self):
        request=intraday_runs.TargetRequest(stock='RELIANCE',target_pct=.3,entry_time='09:45',direction='short')
        with patch.object(intraday_target,'instruments',return_value=intraday_target.STOCKS), \
             patch.object(intraday_runs.jobs,'submit',return_value={'id':'abcdef123456'}) as submit:
            self.assertEqual(intraday_runs.submit(request)['id'],'abcdef123456')
            self.assertEqual(submit.call_args.args[0],'Intraday backtest · RELIANCE · Sell')
            self.assertEqual(submit.call_args.args[2]['entry_time'],'09:45')

    def test_config_rejects_invalid_values_and_normalizes_symbol(self):
        self.assertEqual(intraday_runs.TargetRequest(stock=' reliance ', target_pct=.2).stock, 'RELIANCE')
        for change in ({'target_pct':0},{'target_pct':100},{'target_pct':float('nan')},
                       {'entry_time':'15:15'},{'entry_time':'09:14'}, {'entry_time':'09:60'},
                       {'entry_time':'9:30'},{'direction':'buy'}, {'stock':'../../secret'}, {'capital':1}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                intraday_runs.TargetRequest(**{'stock':'HDFCBANK','target_pct':.2,**change})

    def test_entry_time_excludes_earlier_target_and_uses_selected_open(self):
        day='2024-11-04'
        data={day:session(day, {'09:30':[100,110,90,100], '10:00':[200,200,200,200],
                               '10:01':[200,200.5,199.5,200]})}
        for direction, expected in [('long',200.4), ('short',199.6)]:
            r=intraday_target.simulate(data,[day],entry_time='10:00',target_pct=.2,direction=direction)
            self.assertEqual(r['days'][0]['entry_price'],200)
            self.assertEqual(r['days'][0]['entry_time'],'10:00')
            self.assertEqual(r['days'][0]['exit_time'],'10:01')
            self.assertAlmostEqual(r['days'][0]['exit_price'],expected)
            self.assertIn('10:00',r['strategy'])

    def test_stock_specific_special_open_and_early_close_are_skipped(self):
        day='2025-01-06'
        record=session(day)
        record['bars']=[b for b in record['bars'] if b['time']>='10:00']
        instrument=dict(symbol='ITC',name='ITC Ltd.',isin='INE154A01025')
        r=intraday_target.simulate({day:record},[day],stock='ITC',instrument=instrument)
        self.assertEqual(len(r['skipped']),1)
        day='2025-10-21'
        r=intraday_target.simulate({day:session(day)},[day],entry_time='13:50')
        self.assertEqual(len(r['skipped']),1)
        self.assertIn('15:15',r['skipped'][0]['reason'])

    def test_execute_saves_immutable_result_and_lightweight_catalog(self):
        original=json.loads((Path(__file__).resolve().parents[1]/'dashboard/reports/reliance-target02.json').read_text())
        config=dict(stock='RELIANCE',target_pct=.2,entry_time='09:30',direction='long')
        with tempfile.TemporaryDirectory() as folder, patch.object(store,'DATA',Path(folder)), \
             patch.dict('os.environ',{'TRADER_STORAGE':'json'}), \
             patch.object(intraday_target,'build_report',return_value=original) as build:
            result=intraday_runs.execute(config,lambda message:None,'abcdef123456','manoj')
            saved=store.read(intraday_runs.report_key(result['report_id']))
            self.assertEqual(saved['config'],config)
            self.assertEqual(saved['created_by'],'manoj')
            self.assertEqual(len(saved['days']),494)
            self.assertEqual(build.call_args.kwargs['entry_time'],'09:30')
            summary=intraday_runs.summaries()[0]
            self.assertEqual(summary['trade_count'],494)
            self.assertNotIn('days',summary)
            with self.assertRaisesRegex(ValueError,'already saved'):
                intraday_runs.execute(config,lambda message:None,'abcdef123456','manoj')

    def test_api_queue_and_validation(self):
        app=FastAPI();app.include_router(router)
        @app.exception_handler(ValueError)
        async def invalid(request,error):
            return JSONResponse({'detail':str(error)},status_code=400)
        client=TestClient(app)
        values=dict(stock='RELIANCE',target_pct=.2,entry_time='11:45',direction='short')
        with patch.object(intraday_runs,'submit',return_value={'id':'abcdef123456'}) as submit:
            result=client.post('/api/intraday/backtests',json=values)
            self.assertEqual(result.status_code,202)
            self.assertEqual(submit.call_args.args[0].entry_time,'11:45')
            self.assertEqual(client.post('/api/intraday/backtests',json={**values,'entry_time':'15:30'}).status_code,422)
        with patch.object(intraday_runs,'submit',side_effect=ValueError('Another job is active.')):
            self.assertEqual(client.post('/api/intraday/backtests',json=values).status_code,400)
        self.assertEqual(client.get('/api/intraday/backtests/custom-../../invalid').status_code,404)

    def test_local_frontend_proxies_custom_results_with_authentication(self):
        requested=[]
        def handler(request):
            requested.append((request.method,request.url.path,request.headers.get('cookie')))
            return httpx.Response(200,json={'id':'custom-abcdef123456'})
        with TestClient(create_app(transport=httpx.MockTransport(handler))) as client:
            response=client.get('/api/intraday/backtests/custom-abcdef123456',headers={'cookie':'session=test'})
            self.assertEqual(response.status_code,200)
            self.assertEqual(requested,[('GET','/api/intraday/backtests/custom-abcdef123456','session=test')])


if __name__=='__main__':
    unittest.main()

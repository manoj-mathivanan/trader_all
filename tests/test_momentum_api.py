import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from core.research import store
from dashboard.api.main import app
from tests import test_momentum as fixtures


class MomentumApiTests(unittest.TestCase):
    def test_chart_uses_frozen_momentum_inputs(self):
        fixture=fixtures.MomentumTests();fixture.setUp()
        report=fixture.simulate()
        report.update(id='abcdef123456',strategy_id='intraday_momentum',config=fixture.cfg.model_dump(mode='json'))
        with tempfile.TemporaryDirectory() as folder, patch.object(store,'DATA',Path(folder)):
            store.write('runs/abcdef123456',report)
            store.write('run_intraday/abcdef123456',fixture.minutes)
            client=TestClient(app)
            with patch('core.research.trade_chart.explain_trade') as swing:
                response=client.get('/api/runs/abcdef123456/trades/0/chart')
                self.assertEqual(response.status_code,200,response.text)
                data=response.json()
                self.assertEqual(data['interval_minutes'],5)
                self.assertEqual(data['explanation']['pattern'],'Opening-range momentum')
                swing.assert_not_called()
            store.write('run_intraday/abcdef123456',{})
            self.assertEqual(client.get('/api/runs/abcdef123456/trades/0/chart').status_code,404)

    def test_job_uses_momentum_model_and_engine(self):
        fixture=fixtures.MomentumTests();fixture.setUp()
        with patch('dashboard.api.main.momentum.prepare') as prepare, patch('dashboard.api.main.jobs.submit',return_value={'id':'abcdef123456'}) as submit:
            response=TestClient(app).post('/api/jobs/momentum',json=fixture.cfg.model_dump(mode='json'),headers={'X-Trader-Request':'local-ui'})
            self.assertEqual(response.status_code,200)
            self.assertEqual(submit.call_args.args[0],'Momentum backtest')
            self.assertEqual(prepare.call_args.args[1].strategy_id,'intraday_momentum')

    def test_invalid_times_and_incomplete_session_rejected_before_job(self):
        fixture=fixtures.MomentumTests();fixture.setUp()
        cfg=fixture.cfg.model_dump(mode='json');cfg['square_off_time']='15:99'
        with patch('dashboard.api.main.jobs.submit') as submit:
            response=TestClient(app).post('/api/jobs/momentum',json=cfg,headers={'X-Trader-Request':'local-ui'})
            self.assertEqual(response.status_code,422)
            submit.assert_not_called()

    def test_rerun_uses_frozen_universe_while_workspace_stays_total_market(self):
        fixture=fixtures.MomentumTests();fixture.setUp()
        config={**fixture.cfg.model_dump(mode='json'), 'comparison_run_id':'abcdef123456'}
        with tempfile.TemporaryDirectory() as folder, patch.object(store,'DATA',Path(folder)):
            store.write('settings', {'universe':'niftytotalmarket'})
            store.write('runs/abcdef123456', {'universe':'nifty500'})
            with patch('dashboard.api.main.momentum.prepare') as prepare, \
                 patch('dashboard.api.main.jobs.submit',return_value={'id':'123456abcdef'}):
                response=TestClient(app).post('/api/jobs/momentum',json=config,headers={'X-Trader-Request':'local-ui'})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(prepare.call_args.args[0].universe,'nifty500')
            self.assertEqual(store.read('settings')['universe'],'niftytotalmarket')

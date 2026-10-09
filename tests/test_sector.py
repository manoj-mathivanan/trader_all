"""Sector fixtures are isolated from application data and provider credentials."""
import copy
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock
from pydantic import ValidationError
from fastapi.testclient import TestClient
from core.research import sector, store, backtest, market_history
from core.research.config import BacktestConfig, BearishBacktestConfig, Settings


def candles(count=85, slope=1):
    result = []
    for i in range(count):
        price = 200+slope*i
        result.append(dict(date=str(date(2025,1,1)+timedelta(days=i)),
                           open=price, high=price+1, low=price-1, close=price, volume=0))
    return result


def snapshot(rows=None, benchmark=None):
    value = dict(version=sector.VERSION, captured_at='fixture', mapping_captured_at='fixture', notice=sector.NOTICE,
        mappings={'TEST':dict(isin='TESTISIN', index='it', method='official_isin_membership')},
        prices={'it':dict(bars=rows if rows is not None else candles()),
                'benchmark':dict(bars=benchmark if benchmark is not None else candles(slope=.1))})
    value['sha256'] = market_history.digest(value)
    return value


def cfg(**values):
    return BacktestConfig(**dict(start='2025-03-16', end='2025-03-20', pattern='vcp',
        entry_mode='next_open', acknowledge_limitations=True, **values))


class SectorTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = patch.object(store, 'DATA', Path(folder.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_trend_rs_and_future_independence(self):
        rows = candles()
        day = rows[74]['date']
        original = sector.Gate(snapshot(rows), 'trend_rs').decision('TEST', day)
        changed = copy.deepcopy(rows)
        changed[75:] = candles(10, slope=10)
        # Keep valid ordered dates while changing only future prices.
        for i in range(75,len(rows)):
            changed[i]['date'] = rows[i]['date']
        future = sector.Gate(snapshot(changed), 'trend_rs').decision('TEST', day)
        self.assertTrue(original['allowed'])
        self.assertEqual(original, future)
        self.assertAlmostEqual(original['sma50'], sum(b['close'] for b in rows[25:75])/50)
        self.assertAlmostEqual(original['previous_sma50'], sum(b['close'] for b in rows[5:55])/50)

    def test_missing_stale_warmup_and_unknown_block(self):
        gate = sector.Gate(snapshot(), 'trend')
        self.assertEqual(gate.decision('UNKNOWN','2025-03-16')['reason'],'unmapped_sector')
        self.assertEqual(gate.decision('TEST','2025-04-01')['reason'],'missing_or_stale_sector_session')
        self.assertEqual(gate.decision('TEST','2025-01-20')['reason'],'insufficient_sector_warmup')
        self.assertTrue(gate.decision('TEST',candles()[69]['date'])['allowed'])

    def test_weak_trend_and_outperformance_are_separate(self):
        day = candles()[74]['date']
        self.assertEqual(sector.Gate(snapshot(candles(slope=-1)), 'trend').decision('TEST',day)['reason'],'sector_trend_weak')
        value = snapshot(benchmark=candles(slope=2))
        self.assertTrue(sector.Gate(value,'trend').decision('TEST',day)['allowed'])
        self.assertEqual(sector.Gate(value,'trend_rs').decision('TEST',day)['reason'],'sector_underperforming')

    def test_benchmark_sessions_must_match(self):
        rows = candles()
        benchmark = candles()
        del benchmark[50]
        result = sector.Gate(snapshot(rows,benchmark),'trend_rs').decision('TEST',rows[74]['date'])
        self.assertEqual(result['reason'],'mismatched_index_sessions')
        self.assertFalse(result['allowed'])

    def test_hash_and_invalid_candles_rejected(self):
        value = snapshot()
        value['mappings']['TEST']['index'] = 'bank'
        with self.assertRaisesRegex(ValueError,'missing or changed'):
            sector.Gate(value,'trend')
        rows = candles()
        rows[0]['high'] = 1
        with self.assertRaisesRegex(ValueError,'Invalid OHLCV'):
            sector.Gate(snapshot(rows),'trend')

    def test_mapping_precise_membership_and_ambiguous_industries(self):
        def member(isin,industry):
            return {'ISIN Code':isin,'Industry':industry}
        records = {'bank':{'rows':[member('BANK','Financial Services')]},
                   'financial':{'rows':[member('BANK','Financial Services'),member('INSURANCE','Financial Services')]},
                   'it':{'rows':[member('IT','Information Technology')]}}
        instruments = [dict(symbol=isin,isin=isin,sector=industry) for isin,industry in
                       [('BANK','Financial Services'),('INSURANCE','Financial Services'),
                        ('OTHER_FIN','Financial Services'),('OTHER_IT','Information Technology')]]
        result = sector.build_mapping(instruments,records)
        self.assertEqual(result['BANK']['index'],'bank')
        self.assertEqual(result['INSURANCE']['index'],'financial')
        self.assertIsNone(result['OTHER_FIN']['index'])
        self.assertEqual(result['OTHER_IT']['index'],'it')
        self.assertEqual(result['OTHER_IT']['method'],'unique_industry_label')

    def test_schema_rejects_unsupported_execution(self):
        self.assertEqual(cfg().sector_filter,'off')
        for changes in [dict(entry_mode='pivot'),dict(execution_horizon='intraday')]:
            with self.assertRaises(ValidationError):
                BacktestConfig(**{**cfg().model_dump(),'sector_filter':'trend',**changes})
        with self.assertRaises(ValidationError):
            BearishBacktestConfig(**{**cfg().model_dump(),'pattern':'new_lows','sector_filter':'trend'})

    def test_engine_uses_signal_day_and_keeps_trade_evidence(self):
        rows = candles()
        with patch.object(backtest,'signal',side_effect=lambda bars,i,config:i==74):
            result = backtest.simulate({'TEST':rows},cfg(sector_filter='trend_rs'),
                                      sector_gate=sector.Gate(snapshot(),'trend_rs'))
        self.assertEqual(result['trades'][0]['entry_date'],rows[75]['date'])
        self.assertEqual(result['trades'][0]['sector']['date'],rows[74]['date'])
        self.assertTrue(result['sector_checks'][0]['allowed'])

    def test_blocked_sector_does_not_block_existing_stop_exit(self):
        rows = candles()
        first_cfg = cfg(sector_filter='trend')
        first_cfg.end = date.fromisoformat(rows[75]['date'])
        with patch.object(backtest,'signal',side_effect=lambda bars,i,config:i==74):
            first = backtest.simulate({'TEST':rows},first_cfg,liquidate=False,
                                     sector_gate=sector.Gate(snapshot(),'trend'))
        self.assertIn('TEST',first['state']['positions'])
        changed = copy.deepcopy(rows)
        changed[76].update(open=100,high=101,low=99,close=100)
        second = backtest.simulate({'TEST':changed},cfg(sector_filter='trend'),state=first['state'],
                                  liquidate=False,sector_gate=sector.Gate(snapshot(candles(slope=-1)),'trend'))
        self.assertEqual(second['trades'][0]['reason'],'Gap through stop')

    def test_observation_records_weak_sector_without_blocking(self):
        rows = candles()
        with patch.object(backtest,'signal',side_effect=lambda bars,i,config:i==74):
            result = backtest.simulate({'TEST':rows},cfg(sector_filter='trend'),
                sector_gate=sector.Gate(snapshot(candles(slope=-1)),'trend'),sector_observe_only=True)
        self.assertEqual(len(result['trades']),1)
        self.assertFalse(result['sector_checks'][0]['allowed'])
        self.assertFalse(result['sector_checks'][0]['enforced'])

    def test_paper_cycle_freezes_mapping_and_detects_sector_revisions(self):
        from core.portfolio import paper
        rows = candles()
        universe = {'instruments':[dict(symbol='TEST',isin='INE000000001',sector='IT')]}
        store.write('universes/niftytotalmarket',universe)
        store.write('bars/INE000000001',dict(bars=rows,source='fixture',requested_start=rows[0]['date'],requested_end=rows[-1]['date']))
        value = snapshot()
        value['mappings']['TEST']['isin'] = 'INE000000001'
        store.write('sector/mapping',dict(mappings=value['mappings'],captured_at='fixture'))
        for identifier,record in value['prices'].items():store.write('sector/prices/'+identifier,record)
        config = paper.PaperConfig(capital=100000,sector_filter='trend',acknowledge_limitations=True)
        settings = Settings(universe='niftytotalmarket',start=rows[0]['date'],end=rows[-1]['date'])
        with patch.object(paper,'local_now',return_value=datetime(2025,3,15,17,tzinfo=paper.IST)):
            paper.save(config,settings,create=True)
        with patch.object(paper,'local_now',return_value=datetime(2025,3,20,17,tzinfo=paper.IST)), \
             patch.object(backtest,'signal',side_effect=lambda bars,i,config:i==74):
            paper.cycle(lambda m:None,'fixture_cycle',ingest=False)
        saved = store.read(paper.KEY)
        self.assertEqual(saved['sector_mapping'],value['mappings'])
        self.assertTrue(saved['cycles'][-1]['sector_checks'])
        self.assertFalse(saved['cycles'][-1]['sector_checks'][0]['enforced'])
        record = store.read('sector/prices/it')
        record['bars'][0]['close'] += .1
        store.write('sector/prices/it',record)
        with patch.object(paper,'local_now',return_value=datetime(2025,3,21,17,tzinfo=paper.IST)):
            with self.assertRaisesRegex(ValueError,'Processed sector index history changed'):
                paper.cycle(lambda m:None,'fixture_retry',ingest=False)
        self.assertEqual(store.read(paper.KEY),saved)

    def test_capture_rejects_wrong_stock_identity(self):
        store.write('sector/mapping', {'mappings':{'TEST':{'isin':'WRONG','index':'it'}}})
        value = sector.capture({'instruments':[{'symbol':'TEST','isin':'TESTISIN'}]})
        self.assertEqual(value['mappings'],{})

    def test_comparison_preserves_one_sector_snapshot_and_replay(self):
        rows = candles()
        universe = {'instruments':[dict(symbol='TEST',isin='TESTISIN')]}
        manifest = [dict(symbol='TEST',sha256=market_history.digest(rows))]
        config = cfg().model_dump(mode='json')
        ref = 'a'*12
        store.write('runs/'+ref,dict(config=config,universe='niftytotalmarket',universe_snapshot=universe,
                                    manifest=manifest,excluded=[]))
        store.write('run_data/'+ref,{'TEST':rows})
        with patch.object(sector,'capture',return_value=snapshot()), patch.object(backtest,'signal',return_value=True):
            backtest.compare_sectors(Settings(universe='niftytotalmarket'),'a'*12,lambda message:None,'b'*12)
        runs = [store.read('runs/'+'b'*12+'_'+mode) for mode in ('off','trend','trend_rs')]
        self.assertEqual(len({r['sector_reference']['sha256'] for r in runs}),1)
        self.assertEqual([r['config']['sector_filter'] for r in runs],['off','trend','trend_rs'])
        self.assertTrue(runs[1]['sector_checks'])
        tampered = snapshot()
        tampered['prices']['it']['bars'][0]['close'] = 5
        store.write('run_sector/'+'b'*12+'_trend',tampered)
        with self.assertRaisesRegex(ValueError,'missing or changed'):
            backtest.run(Settings(universe='niftytotalmarket'),cfg(sector_filter='trend',comparison_run_id='b'*12+'_trend'),lambda m:None,'c'*12)

    def test_api_coverage_and_comparison_validation(self):
        from dashboard.api.main import app
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/sectors').status_code,200)
            response = client.post('/api/jobs/sector-comparison',json={'reference_id':'a'*12},headers={'X-Trader-Request':'local-ui'})
            self.assertEqual(response.status_code,400)

    def test_fetch_aliases_incremental_boundaries_and_failure_retention(self):
        from core.research import market_data
        instrument = dict(symbol='TEST',isin='TESTISIN',sector='Information Technology')
        universe = {'instruments':[instrument]}
        rows = candles(3)
        store.write('sector/prices/it',dict(bars=rows[:2]))
        master = [dict(segment='NSE_INDEX',name=sector.PROVIDER_NAMES.get(k,name),instrument_key='KEY_'+k)
                  for k,(name,filename) in sector.INDICES.items()]
        master.append(dict(segment='NSE_INDEX',name=sector.BENCHMARK,instrument_key='KEY_benchmark'))
        def get(client,url,**kwargs):
            if url == sector.upstox.INSTRUMENTS:
                import json
                return Mock(content=json.dumps(master).encode())
            return Mock(content=b'Company Name,Industry,Symbol,ISIN Code\nTest,Information Technology,TEST,TESTISIN\n')
        def fetch(client,item,token,start,end):
            if item['symbol']=='auto':
                raise ValueError('Provider busy')
            return [b for b in rows if str(start)<=b['date']<=str(end)]
        with patch.object(store,'token',return_value='fixture-token'), patch.object(market_data,'last_traded_day',return_value=date(2025,1,3)), \
             patch.object(sector.upstox,'get',side_effect=get), patch.object(sector.upstox,'fetch_range',side_effect=fetch) as downloaded:
            result = sector.fetch(Settings(),lambda m:None,universe=universe,start=date(2025,1,1))
        call = next(c for c in downloaded.call_args_list if c.args[1]['symbol']=='it')
        self.assertEqual(call.args[-2:],(date(2025,1,2),date(2025,1,3)))
        self.assertEqual(len(store.read('sector/prices/it')['bars']),3)
        self.assertTrue(result['partial'])
        self.assertEqual(result['failures'][0]['index'],'auto')

    def test_year_chunks_cover_requested_dates_without_overlap(self):
        self.assertEqual(list(sector.annual_ranges(date(2018,11,1),date(2020,1,5))),
                         [(date(2018,11,1),date(2018,12,31)),(date(2019,1,1),date(2019,12,31)),
                          (date(2020,1,1),date(2020,1,5))])


if __name__ == '__main__':
    unittest.main()

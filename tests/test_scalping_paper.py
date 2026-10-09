"""Forward paper tests use observed synthetic books, never a broker or user data."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from core.market_data import MarketDataFeed_pb2 as proto, upstox_stream
from core.portfolio import scalping_control, scalping_paper as live, scalping_runner
from core.portfolio.locking import mutex
from core.research import scalping, store
from dashboard.api.main import app
from tests.test_scalping import session, pullback


class StreamingPaperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = patch.object(store, 'DATA', Path(self.tmp.name))
        self.data.start()
        self.addCleanup(self.data.stop)
        self.day = '2025-02-05'
        self.clock = datetime.fromisoformat(self.day+'T09:49:02+05:30')
        self.cfg = live.ScalpingPaperConfig(capital=1e6, liquid_universe_size=3, max_positions=1,
                  slippage_bps=1, buy_cost_bps=1, sell_cost_bps=1, acknowledge_limitations=True)
        self.bars = session(self.day)
        pullback(self.bars)
        self.context = dict(day=self.day, config=self.cfg.model_dump(mode='json'),
                    candidates=[dict(symbol='A',history=['2025-02-03','2025-02-04'],turnover=1e8)],
                    instruments=[dict(symbol='A',isin='TEST',key='NSE_EQ|TEST')],
                    warmup={'A':{'2025-02-03':session('2025-02-03',100,.005),
                                 '2025-02-04':session('2025-02-04',102,.005)}})
        self.context['sha256'] = scalping.digest(self.context)
        self.portfolio = dict(id='scalping',strategy_name='scalping',status='active',mode='paper',
                       start_session=self.day,config=self.cfg.model_dump(mode='json'),ledger={},
                       universe_snapshot={'instruments':self.context['instruments']})
        store.write(live.KEY,self.portfolio)
        self.engine = live.QuoteEngine(self.context,self.clock)
        self.engine.market_open = True

    def saved(self):
        return store.read(live.KEY)

    def arm(self, clock=None):
        self.engine.record_bars('A',self.bars[:34],clock or self.clock)

    def quote(self, clock=None, **changes):
        clock = clock or self.clock+timedelta(seconds=1)
        return {**dict(timestamp=int(clock.timestamp()*1000),price=110.74,bid=110.73,ask=110.75,
                       bid_quantity=1000,ask_quantity=1000),**changes}

    def enter(self):
        self.arm()
        self.assertIn('A',self.saved()['stream_session']['pending'])
        self.assertTrue(self.engine.quote('A',self.quote(),self.clock+timedelta(seconds=1)))
        return self.saved()['ledger']['positions']['A']

    def test_completed_candles_and_observed_quote_cash_accounting(self):
        p = self.enter()
        ledger = self.saved()['ledger']
        self.assertLessEqual(p['quantity'],1000)
        self.assertAlmostEqual(ledger['cash']+p['reserved'],self.cfg.capital)
        self.assertGreater(p['entry'],110.75)
        self.assertEqual(p['signal']['time'],'09:48')
        self.assertEqual(p['entry_time'],'09:49:03')
        self.assertEqual(ledger['orders'][0]['quote']['ask'],110.75)
        now = self.clock+timedelta(seconds=2)
        self.engine.quote('A',self.quote(now,bid=p['target']+.01,ask=p['target']+.03),now)
        ledger = self.saved()['ledger']
        self.assertFalse(ledger['positions'])
        self.assertAlmostEqual(ledger['cash'],self.cfg.capital+sum(t['pnl'] for t in ledger['trades']))
        self.assertAlmostEqual(ledger['total_fees'],sum(t['fees'] for t in ledger['trades']))

    def test_no_historical_entry_and_no_incomplete_candle(self):
        self.arm(self.clock-timedelta(seconds=3))
        self.assertNotIn('A',self.saved()['stream_session']['pending'])
        self.engine = live.QuoteEngine(self.context,self.clock)
        self.arm(self.clock+timedelta(seconds=20))
        self.assertFalse(self.saved()['stream_session']['pending'])
        self.assertFalse(self.saved()['ledger']['orders'])

    def test_closed_stale_future_crossed_or_wide_book_cannot_enter(self):
        self.arm()
        clock = self.clock+timedelta(seconds=1)
        self.engine.market_open = False
        self.assertFalse(self.engine.quote('A',self.quote(clock),clock))
        self.engine.market_open = True
        for changes in [dict(timestamp=int(clock.timestamp()*1000)-4000),
                        dict(timestamp=int(clock.timestamp()*1000)+1),
                        dict(bid=111,ask=110),dict(bid_quantity=0),dict(bid=float('nan')),
                        dict(bid=110,ask=111)]:
            self.assertFalse(self.engine.quote('A',self.quote(clock,**changes),clock))
        self.assertFalse(self.saved()['ledger']['positions'])

    def test_pause_blocks_entries_but_protective_exit_survives_research_job(self):
        p = self.enter()
        store.write('jobs',[dict(status='running')])
        live.set_status('paused')
        clock = self.clock+timedelta(seconds=2)
        self.engine.quote('A',self.quote(clock,bid=p['stop']-.01,ask=p['stop']+.01),clock)
        self.assertFalse(self.saved()['ledger']['positions'])
        self.assertEqual(self.saved()['ledger']['trades'][0]['reason'],'Quote crossed pullback stop')
        # A saved setup cannot bypass a pause.
        portfolio=self.saved()
        portfolio['stream_session']['pending']['A']=dict(ready_at=0,expires_at=10**15)
        store.write(live.KEY,portfolio)
        clock+=timedelta(seconds=1)
        self.assertFalse(self.engine.quote('A',self.quote(clock),clock))

    def test_partial_exit_latches_intent_and_restart_does_not_duplicate(self):
        p=self.enter()
        clock=self.clock+timedelta(seconds=2)
        q=self.quote(clock,bid=p['stop']-.01,ask=p['stop']+.01,bid_quantity=1)
        self.engine.quote('A',q,clock)
        saved=self.saved()
        self.assertTrue(saved['ledger']['trades'][0]['partial_exit'])
        self.assertEqual(saved['ledger']['positions']['A']['quantity'],p['quantity']-1)
        self.engine=live.QuoteEngine(self.context,clock)
        self.engine.market_open=True
        self.assertFalse(self.engine.quote('A',q,clock))
        self.assertEqual(len(self.saved()['ledger']['trades']),1)
        clock+=timedelta(seconds=1)
        # Price recovered, but an already-triggered partial stop must finish.
        self.engine.quote('A',self.quote(clock),clock)
        ledger=self.saved()['ledger']
        self.assertFalse(ledger['positions'])
        self.assertEqual(len(ledger['trades']),2)
        self.assertAlmostEqual(ledger['cash'],self.cfg.capital+sum(t['pnl'] for t in ledger['trades']))

    def test_disconnect_and_restart_discard_unfilled_setup(self):
        self.arm()
        self.engine.disconnect()
        self.assertFalse(self.saved()['stream_session']['pending'])
        self.engine.market_open=True
        self.arm()  # Already-processed bars do not regenerate an old setup.
        self.assertFalse(self.saved()['stream_session']['pending'])
        self.engine=live.QuoteEngine(self.context,self.clock)
        self.assertFalse(self.saved()['ledger']['orders'])

    def test_candle_revision_halts_entries_without_disabling_exits(self):
        p=self.enter()
        rows=copy.deepcopy(self.bars[:35])
        rows[0]['close']+=.001
        clock=self.clock+timedelta(minutes=1)
        self.engine.record_bars('A',rows,clock)
        self.assertIn('A',self.saved()['stream_session']['data_issues'])
        self.engine.stopping=True
        self.engine.quote('A',self.quote(clock),clock)
        self.assertFalse(self.saved()['ledger']['positions'])

    def test_daily_loss_latches_and_cutoff_uses_actual_quote(self):
        p=self.enter()
        clock=self.clock+timedelta(seconds=2)
        self.engine.quote('A',self.quote(clock,bid=100,ask=100.02,price=100.01),clock)
        self.assertTrue(self.saved()['stream_session']['loss_halt'])
        self.assertGreater(self.saved()['ledger']['trades'][0]['exit_timestamp'],p['entry_timestamp'])
        self.setUpFreshPortfolio()
        self.enter()
        clock=datetime.fromisoformat(self.day+'T15:16:04+05:30')
        self.engine.quote('A',self.quote(clock),clock)
        trade=self.saved()['ledger']['trades'][0]
        self.assertEqual(trade['exit_time'],'15:16:04')
        self.assertEqual(trade['reason'],'Mandatory intraday square-off')

    def setUpFreshPortfolio(self):
        store.write(live.KEY,self.portfolio)
        self.engine=live.QuoteEngine(self.context,self.clock)
        self.engine.market_open=True

    def test_short_reserves_notional_and_pays_both_fees(self):
        for rows in [self.bars,*self.context['warmup']['A'].values()]:
            for b in rows:
                o,h,l,c=[b[k] for k in ('open','high','low','close')]
                b.update(open=220-o,high=220-l,low=220-h,close=220-c)
        self.context['config']['direction']='short'
        self.setUpFreshPortfolio()
        self.arm()
        clock=self.clock+timedelta(seconds=1)
        self.engine.quote('A',self.quote(clock,bid=109.25,ask=109.27,price=109.26),clock)
        p=self.saved()['ledger']['positions']['A']
        self.assertEqual(p['sign'],-1)
        self.assertAlmostEqual(self.saved()['ledger']['cash']+p['reserved'],self.cfg.capital)
        clock+=timedelta(seconds=1)
        self.engine.quote('A',self.quote(clock,bid=p['target']-.03,ask=p['target']-.01),clock)
        ledger=self.saved()['ledger']
        self.assertFalse(ledger['positions'])
        self.assertAlmostEqual(ledger['cash'],self.cfg.capital+sum(t['pnl'] for t in ledger['trades']))

    def test_atomic_failure_preserves_ledger_and_restart_preserves_position(self):
        p=self.enter()
        before=self.saved()
        self.engine.stopping=True
        clock=self.clock+timedelta(seconds=2)
        with patch.object(Path,'replace',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                self.engine.quote('A',self.quote(clock),clock)
        self.assertEqual(self.saved(),before)
        self.engine=live.QuoteEngine(self.context,clock)
        self.engine.market_open=True
        self.assertEqual(self.saved()['ledger']['positions']['A']['id'],p['id'])
        self.engine.stopping=True
        self.engine.quote('A',self.quote(clock),clock)
        self.assertEqual(len(self.saved()['ledger']['trades']),1)

    def test_new_day_archives_previous_session_and_flattens_exposure(self):
        self.enter()
        context=copy.deepcopy(self.context)
        context['day']='2025-02-06'
        clock=datetime.fromisoformat(context['day']+'T09:16:00+05:30')
        self.engine=live.QuoteEngine(context,clock)
        self.engine.market_open=True
        self.assertTrue(self.saved()['stream_session']['recovery_flatten'])
        self.assertIsNotNone(store.read('scalping_stream/sessions/'+self.day))
        self.engine.quote('A',self.quote(clock),clock)
        self.assertFalse(self.saved()['ledger']['positions'])
        self.assertFalse(self.saved()['stream_session']['recovery_flatten'])

    def test_context_hash_checked_and_public_payload_omits_large_history(self):
        context=copy.deepcopy(self.context)
        store.write(live.context_key(self.day),context)
        self.assertEqual(live.prepare_session(self.day,lambda _:None),context)
        context['config']['risk_pct']=2
        store.write(live.context_key(self.day),context)
        with self.assertRaisesRegex(ValueError,'context changed'):
            live.prepare_session(self.day,lambda _:None)
        self.arm()
        public=live.public_portfolio()
        self.assertNotIn('bars',public['stream_session'])
        self.assertNotIn('pending',public['stream_session'])
        self.assertIn('bars',self.saved()['stream_session'])

    def test_forward_selection_never_requests_current_day_warmup(self):
        daily=[]
        day=datetime.fromisoformat('2025-01-01')
        while day.date().isoformat()<self.day:
            if day.weekday()<5:
                daily.append(dict(date=day.date().isoformat(),open=100,high=101,low=99,close=100,volume=1e6))
            day+=timedelta(days=1)
        store.write('bars/TEST',{'bars':daily})
        requests=[]
        def load(plan,*_):
            requests.append(plan)
            return {'A':{d:session(d,100,.005) for d in plan}}
        with patch.object(live.market_history,'evidence',return_value={}),patch.object(live.market_history,'prepare',return_value=(daily,{})),patch.object(live.intraday_data,'load_ranges',side_effect=load):
            context=live.prepare_session(self.day,lambda _:None)
        self.assertNotIn(self.day,requests[0])
        self.assertTrue(all(d<self.day for d in requests[0]))
        self.assertEqual(context['latest_daily_session'],'2025-02-04')
        self.assertIsNone(context['candidates'][0]['daily_open'])
        with patch.object(live.intraday_data,'load_ranges',side_effect=AssertionError('Refetch')):
            self.assertEqual(live.prepare_session(self.day,lambda _:None),context)

    def test_cooldown_and_trade_cap_block_reentry(self):
        p=self.enter()
        setup=scalping.signal(self.bars,scalping.features(self.context['warmup']['A'],self.context['candidates'][0],self.day,self.cfg,completed_bars=self.bars[:34])[1],33,self.cfg)
        clock=self.clock+timedelta(seconds=2)
        self.engine.quote('A',self.quote(clock,bid=p['target']+.01,ask=p['target']+.03),clock)
        portfolio=self.saved()
        portfolio['stream_session']['pending']['A']=dict(**setup,signal=self.bars[33],ready_at=0,expires_at=10**15)
        store.write(live.KEY,portfolio)
        clock+=timedelta(seconds=1)
        self.assertFalse(self.engine.quote('A',self.quote(clock),clock))
        portfolio=self.saved()
        portfolio['stream_session']['cooldown']['A']=0
        portfolio['stream_session']['counts']['A']=self.cfg.max_trades_per_symbol
        store.write(live.KEY,portfolio)
        clock+=timedelta(seconds=1)
        self.assertFalse(self.engine.quote('A',self.quote(clock),clock))
        self.assertEqual(len(self.saved()['ledger']['orders']),2)

    def test_daily_scheduler_never_dispatches_streaming_portfolio(self):
        from core.portfolio import scheduler
        portfolio=self.saved()
        portfolio['config']['auto_run']=True
        store.write(live.KEY,portfolio)
        with patch.object(scheduler.paper,'local_now',return_value=self.clock),patch.object(scheduler.jobs,'submit') as submit:
            scheduler.tick()
        submit.assert_not_called()

    def test_creation_requires_explicit_capital_and_acknowledgment(self):
        payload=self.cfg.model_dump(mode='json')
        payload.pop('capital')
        with TestClient(app) as client:
            response=client.post('/api/scalping/paper/portfolio',headers={'X-Trader-Request':'local-ui'},json=payload)
            self.assertEqual(response.status_code,422)
            payload['capital']=1e6
            payload['acknowledge_limitations']=False
            response=client.post('/api/scalping/paper/portfolio',headers={'X-Trader-Request':'local-ui'},json=payload)
            self.assertEqual(response.status_code,422)
        self.assertEqual(self.saved()['ledger']['orders'],[])

    def test_local_scalping_api_available_but_generic_paper_stays_gated(self):
        with patch('dashboard.api.main.PAPER_ENABLED',False),TestClient(app) as client:
            bootstrap=client.get('/api/bootstrap').json()
            self.assertIn('scalping_paper_schema',bootstrap)
            self.assertEqual(client.get('/api/scalping/paper/portfolio').status_code,200)
            self.assertEqual(client.get('/api/scalping/paper/export').json(),self.saved())
            self.assertEqual(client.get('/api/paper/portfolio').status_code,403)
            response=client.put('/api/scalping/paper/status',headers={'X-Trader-Request':'local-ui'},json={'status':'paused'})
            self.assertEqual(response.status_code,200)

    def test_controller_requires_capital_and_is_idempotent(self):
        store.write(live.KEY,None)
        with patch('core.portfolio.scalping_control.subprocess.Popen') as spawn:
            with self.assertRaisesRegex(ValueError,'allocated capital'):
                scalping_control.start()
            spawn.assert_not_called()
        store.write(live.KEY,self.portfolio)
        with patch.object(store,'token',return_value='test-token'),patch('core.portfolio.scalping_control.subprocess.Popen') as spawn:
            scalping_control.start()
            scalping_control.start()
            self.assertEqual(spawn.call_count,1)
            self.assertIn('scalping_runner',spawn.call_args.args[0][-1])
            scalping_control.stop()
            self.assertFalse(store.read(scalping_control.CONTROL)['run_requested'])
        with patch('core.portfolio.scalping_control.subprocess.Popen') as spawn:
            scalping_control.autostart()
            spawn.assert_not_called()

    def test_process_lock_prevents_second_runner(self):
        env={**os.environ,'TRADER_DATA_DIR':self.tmp.name}
        script="from core.portfolio.locking import mutex; import sys;\nwith mutex('scalping_runner'):\n print('ready',flush=True)\n sys.stdin.readline()\n"
        child=subprocess.Popen([sys.executable,'-c',script],cwd=store.ROOT,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(),'ready')
            with self.assertRaises(ValueError):
                with mutex('scalping_runner',timeout=0):
                    self.fail('Second process obtained runner ownership')
            self.assertTrue(scalping_control.running())
        finally:
            # Gracefully release the real interpreter's lock (Windows venv launcher
            # termination alone can leave its child interpreter alive briefly).
            child.communicate(input='\n',timeout=5)

    def test_runner_discards_snapshot_then_fills_fresh_live_quote(self):
        p=self.enter()
        store.write(live.context_key(self.day),self.context)
        store.write(scalping_control.CONTROL,dict(run_requested=False))
        clock=self.clock+timedelta(seconds=2)
        socket=Mock()
        frame=dict(kind='initial_feed',market_status='NORMAL_OPEN',quotes=[dict(key='NSE_EQ|TEST',**self.quote(clock))])
        live_frame={**frame,'kind':'live_feed'}
        observations=[]
        def decode(_):
            observations.append(len(self.saved()['ledger']['trades']))
            return frame if len(observations)==1 else live_frame
        socket.recv.return_value=b'fixture'
        with patch.object(scalping_runner.paper,'local_now',return_value=clock),patch.object(upstox_stream,'connect',return_value=socket),patch.object(upstox_stream,'decode',side_effect=decode),patch.object(upstox_stream,'completed_minutes',return_value=[]):
            scalping_runner.loop()
        self.assertEqual(observations,[0,0])
        self.assertEqual(len(self.saved()['ledger']['trades']),1)
        self.assertEqual(self.saved()['ledger']['trades'][0]['position_id'],p['id'])
        self.assertEqual(store.read(scalping_control.STATE)['status'],'stopped')
        socket.close.assert_called_once()

    def test_runner_recovers_exposure_when_existing_context_is_corrupt(self):
        self.enter()
        context=copy.deepcopy(self.context)
        context['config']['risk_pct']=2
        store.write(live.context_key(self.day),context)
        store.write(scalping_control.CONTROL,dict(run_requested=False))
        clock=self.clock+timedelta(seconds=2)
        socket=Mock()
        socket.recv.return_value=b'fixture'
        frame=dict(kind='live_feed',market_status='NORMAL_OPEN',quotes=[dict(key='NSE_EQ|TEST',**self.quote(clock))])
        with patch.object(scalping_runner.paper,'local_now',return_value=clock),patch.object(upstox_stream,'connect',return_value=socket),patch.object(upstox_stream,'decode',return_value=frame):
            scalping_runner.loop()
        self.assertFalse(self.saved()['ledger']['positions'])
        self.assertTrue(store.read('scalping_stream/recovery/'+self.day)['recovery_only'])

    def test_runner_disconnect_clears_setup_and_retains_exposure(self):
        self.enter()
        self.arm()
        store.write(live.context_key(self.day),self.context)
        store.write(scalping_control.CONTROL,dict(run_requested=True))
        socket=Mock()
        socket.recv.side_effect=upstox_stream.websocket.WebSocketConnectionClosedException()
        class EndTest(Exception):
            pass
        with patch.object(scalping_runner.paper,'local_now',return_value=self.clock),patch.object(upstox_stream,'connect',return_value=socket),patch.object(scalping_runner.time,'sleep',side_effect=EndTest):
            with self.assertRaises(EndTest):
                scalping_runner.loop()
        self.assertIn('A',self.saved()['ledger']['positions'])
        self.assertFalse(self.saved()['stream_session']['pending'])
        self.assertFalse(self.saved()['stream_session']['feed_connected'])


class StreamTransportTests(unittest.TestCase):
    def test_binary_equity_depth_and_market_status(self):
        frame=proto.FeedResponse(type=proto.live_feed,currentTs=123456)
        frame.marketInfo.segmentStatus['NSE_EQ']=proto.NORMAL_OPEN
        market=frame.feeds['NSE_EQ|TEST'].fullFeed.marketFF
        market.ltpc.ltp=100.01
        market.ltpc.ltt=123455
        market.marketLevel.bidAskQuote.add(bidP=100,askP=100.02,bidQ=10,askQ=20)
        result=upstox_stream.decode(frame.SerializeToString())
        self.assertEqual(result['kind'],'live_feed')
        self.assertEqual(result['market_status'],'NORMAL_OPEN')
        self.assertEqual(result['quotes'][0]['bid_quantity'],10)
        market.marketLevel.bidAskQuote[0].askP=99
        self.assertFalse(upstox_stream.decode(frame.SerializeToString())['quotes'])
        with self.assertRaisesRegex(ValueError,'Malformed'):
            upstox_stream.decode(b'\xff')

    def test_subscription_is_binary_and_failures_hide_credentials(self):
        socket=Mock()
        with patch.object(upstox_stream,'authorized_url',return_value='wss://test.upstox.com/?secret=abc'),patch.object(upstox_stream.websocket,'create_connection',return_value=socket):
            self.assertIs(upstox_stream.connect(['NSE_EQ|TEST'],'token'),socket)
            payload=json.loads(socket.send_binary.call_args.args[0])
            self.assertEqual(payload['data'],dict(mode='full',instrumentKeys=['NSE_EQ|TEST']))
            socket.send_binary.side_effect=RuntimeError('secret=abc')
            with self.assertRaisesRegex(ValueError,'no credentials') as error:
                upstox_stream.connect(['NSE_EQ|TEST'],'token')
            self.assertNotIn('abc',str(error.exception))
            socket.close.assert_called_once()

    def test_completed_rest_candles_exclude_unfinished_and_wrong_date(self):
        clock=datetime.fromisoformat('2025-02-05T09:17:02+05:30')
        rows=[[b['date']+'T'+b['time']+':00+05:30',b['open'],b['high'],b['low'],b['close'],b['volume'],0]
              for b in session('2025-02-05')[:3]]
        client=Mock()
        client.get.return_value.json.return_value={'status':'success','data':{'candles':rows}}
        with patch.object(store,'token',return_value='test-token'):
            result=upstox_stream.completed_minutes({'symbol':'A','key':'NSE_EQ|TEST'},'2025-02-05',clock,client=client)
            self.assertEqual([b['time'] for b in result],['09:15','09:16'])
            rows[0][0]='2025-02-04T09:15:00+05:30'
            with self.assertRaisesRegex(ValueError,'entries remain blocked'):
                upstox_stream.completed_minutes({'symbol':'A','key':'NSE_EQ|TEST'},'2025-02-05',clock,client=client)


if __name__=='__main__':
    unittest.main()

"""Independent market-hours process. Quote exits continue through candle/API failures."""
import os
import time
from concurrent.futures import ThreadPoolExecutor

import websocket
from core.market_data import upstox_stream
from core.portfolio import paper, scalping_control, scalping_paper
from core.portfolio.locking import mutex
from core.research import scalping, store


def report(status, message, **fields):
    store.write(scalping_control.STATE,dict(status=status,message=message,pid=os.getpid(),heartbeat_at=store.now(),**fields))


def recovery_context(portfolio, day):
    symbols = set(portfolio['ledger'].get('positions',{}))
    context = dict(day=day,config=portfolio['config'],candidates=[],warmup={},recovery_only=True,
                   instruments=[i for i in portfolio['universe_snapshot']['instruments'] if i['symbol'] in symbols])
    context['sha256'] = scalping.digest(context)
    store.write('scalping_stream/recovery/'+day,context)
    return context


def loop():
    engine, socket, day, retry_at = None,None,None,0
    delay, last_checkpoint, candle_minute = 2,0,None
    pending = {}
    snapshot_seen = False
    pool = ThreadPoolExecutor(max_workers=4,thread_name_prefix='scalping-candles')
    try:
        while True:
            clock = paper.local_now()
            today = clock.date().isoformat()
            portfolio = store.read(scalping_paper.KEY)
            if not portfolio:
                report('failed','Scalping portfolio is unavailable; no orders were placed.')
                return
            stop = not store.read(scalping_control.CONTROL,{}).get('run_requested',False)
            positions = portfolio.get('ledger',{}).get('positions',{})
            if stop and not positions:
                report('stopped','Runner stopped; the paper ledger is preserved.')
                return
            eligible = clock.weekday()<5 and '09:10'<=clock.strftime('%H:%M')<='15:29' and today>=portfolio['start_session']
            if not eligible:
                if socket:
                    socket.close(); socket=None
                if engine:
                    engine.disconnect(); engine.checkpoint(clock)
                engine=None
                if time.monotonic()-last_checkpoint>=10:
                    last_checkpoint=time.monotonic()
                    report('needs_attention' if positions else 'waiting',
                           'Open paper positions await a fresh regular-session quote for liquidation.' if positions else 'Waiting for the next eligible regular session.',
                           open_positions=len(positions),next_start_session=portfolio['start_session'])
                time.sleep(1)
                continue
            if engine is None or day!=today:
                if socket:
                    socket.close(); socket=None
                pending.clear(); candle_minute=None
                if time.monotonic()<retry_at:
                    time.sleep(1); continue
                try:
                    existing = store.read(scalping_paper.context_key(today))
                    # Old/uncontextualized exposure is flattened before slow history preparation.
                    if positions and not existing:
                        context = recovery_context(portfolio,today)
                        engine = scalping_paper.QuoteEngine(context,clock)
                        engine.stopping = True
                    else:
                        report('preparing','Freezing prior daily selection and completed minute warmup.')
                        context = scalping_paper.prepare_session(today,lambda _:report('preparing','Loading and validating minute warmup.'))
                        engine = scalping_paper.QuoteEngine(context,clock)
                    day=today
                except ValueError:
                    if positions:
                        # A damaged research context may block entries, never protective liquidation.
                        context = recovery_context(portfolio,today)
                        engine = scalping_paper.QuoteEngine(context,clock)
                        engine.stopping = True
                        day=today
                        report('needs_attention','Session preparation failed; recovering saved exposure using fresh quotes only.')
                    else:
                        report('blocked','Session preparation failed. Check daily coverage, warmup and data anomalies; retry after fixing the inputs.')
                        retry_at=time.monotonic()+60
                        time.sleep(1); continue
            engine.stopping = stop or engine.context.get('recovery_only',False)
            portfolio = store.read(scalping_paper.KEY)
            if engine.context.get('recovery_only') and not portfolio['ledger']['positions']:
                engine=None; continue
            if socket is None:
                if time.monotonic()<retry_at:
                    time.sleep(1); continue
                keys = {i['key'] for i in engine.context['instruments']}
                held = set(portfolio['ledger']['positions'])
                keys.update(i['key'] for i in portfolio['universe_snapshot']['instruments'] if i['symbol'] in held)
                report('connecting','Connecting the Upstox V3 full feed.')
                try:
                    socket=upstox_stream.connect(sorted(keys))
                    socket.settimeout(1)
                    snapshot_seen=False
                    delay=2
                except ValueError:
                    engine.disconnect()
                    report('reconnecting','Feed connection failed. Check the Upstox token and permissions; pending entries were discarded.')
                    retry_at=time.monotonic()+delay; delay=min(30,delay*2)
                    continue
            # REST work never blocks quote receipt or protective exits.
            minute=int(clock.timestamp())//60
            if engine.market_open and clock.second>=2 and minute!=candle_minute and not pending:
                candle_minute=minute
                for item in engine.context['instruments']:
                    if item['symbol'] in engine.candidates:
                        pending[pool.submit(upstox_stream.completed_minutes,item,today,clock)]=item['symbol']
            for future,symbol in list(pending.items()):
                if not future.done():
                    continue
                pending.pop(future)
                try:
                    engine.record_bars(symbol,future.result(),paper.local_now())
                except ValueError:
                    report('degraded','Completed candle update failed; quote-based protective exits continue.',symbol=symbol)
            try:
                payload=socket.recv()
                if not payload:
                    raise websocket.WebSocketConnectionClosedException()
                if not isinstance(payload,bytes):
                    raise ValueError('Expected binary feed.')
                frame=upstox_stream.decode(payload)
                if frame['market_status'] is not None:
                    engine.market_open=frame['market_status']=='NORMAL_OPEN'
                # Initial snapshots establish state only; they cannot create paper fills.
                if frame['quotes'] and not snapshot_seen:
                    snapshot_seen=True
                elif frame['kind']=='live_feed':
                    mapping={i['key']:i['symbol'] for i in portfolio['universe_snapshot']['instruments']}
                    for quote in frame['quotes']:
                        symbol=mapping.get(quote['key'])
                        if symbol:
                            engine.quote(symbol,quote,paper.local_now())
            except websocket.WebSocketTimeoutException:
                pass
            except (ValueError,websocket.WebSocketException,OSError):
                engine.disconnect()
                socket.close(); socket=None
                report('reconnecting','Feed interrupted; pending entries cleared. Saved positions await fresh quotes.')
                retry_at=time.monotonic()+delay; delay=min(30,delay*2)
            if time.monotonic()-last_checkpoint>=10:
                last_checkpoint=time.monotonic()
                clock=paper.local_now()
                engine.checkpoint(clock,feed_connected=socket is not None and engine.market_open)
                portfolio=store.read(scalping_paper.KEY)
                stale=[s for s in portfolio['ledger']['positions'] if int(clock.timestamp()*1000)-engine.fresh_quotes.get(s,0)>engine.cfg.quote_max_age_seconds*1000]
                report('needs_attention' if stale else 'stopping' if stop else 'running' if engine.market_open else 'waiting_market',
                       'Fresh quotes unavailable for open positions; no stale or invented liquidation prices.' if stale else
                       'Stop requested: liquidating on fresh quotes before exiting.' if stop else
                       'Quote runner active. Candle signals use completed REST data.' if engine.market_open else
                       'Connected; waiting for NSE equity NORMAL_OPEN status.',
                       session=today,open_positions=len(portfolio['ledger']['positions']),stale_symbols=stale,
                       candle_issues=portfolio['stream_session']['data_issues'])
    finally:
        if socket:
            socket.close()
        for future in pending:
            future.cancel()
        pool.shutdown(wait=False,cancel_futures=True)


def main():
    try:
        with mutex('scalping_runner',timeout=0):
            try:
                loop()
            except Exception:
                report('failed','Runner interrupted. Saved positions and fills remain intact; restart to recover without replaying entries.')
    except ValueError:
        # Another process owns the runner. Never overwrite its status or ledger.
        return


if __name__=='__main__':
    main()

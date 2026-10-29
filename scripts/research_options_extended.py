"""Resumable monthly research with frozen rules and a separate comparison period."""
import argparse
from collections import deque
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from threading import Lock
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from core.research import options_history as history, options_strategy, store
from scripts.research_options_sample import run as compare


class BudgetTransport(httpx.BaseTransport):
    """Budget actual requests, including retries, against all published windows."""
    def __init__(self, state_path, transport=None):
        self.transport = transport or httpx.HTTPTransport(retries=0)
        self.path = Path(state_path)
        self.lock = Lock()
        self.times = deque(json.loads(self.path.read_text()) if self.path.exists() else [])
        self.waiting = False
        self.last_status_write = 0

    def handle_request(self, request):
        while True:
            with self.lock:
                now = time.time()
                while self.times and self.times[0] <= now-1801:
                    self.times.popleft()
                # Leave headroom for other app/API activity on the same account.
                recent = [t for t in self.times if t > now-61]
                delay = max(0, (self.times[-1]+.25-now) if self.times else 0,
                    self.times[0]+1801-now if len(self.times)>=1800 else 0,
                    recent[0]+61-now if len(recent)>=400 else 0)
                if delay <= 0:
                    self.times.append(now)
                    history.save_json(self.path,list(self.times))
                    if self.waiting:
                        history.save_json(self.path.with_name('budget-status.json'),dict(status='active',checked_at=datetime.now(timezone.utc).isoformat()))
                        self.waiting=False
                    break
                if delay > 1 and (not self.waiting or now-self.last_status_write>=30):
                    history.save_json(self.path.with_name('budget-status.json'),dict(status='waiting_for_api_budget',
                        checked_at=datetime.fromtimestamp(now,timezone.utc).isoformat(),
                        earliest_resume_at=datetime.fromtimestamp(now+delay,timezone.utc).isoformat(),
                        wait_seconds=round(delay),requests_in_window=len(self.times)))
                    self.waiting=True
                    self.last_status_write=now
            time.sleep(min(delay, 1))
        return self.transport.handle_request(request)

    def close(self):
        self.transport.close()


def source_hashes():
    files = ['core/research/options_strategy.py','core/research/options_backtest.py',
             'core/research/options_costs.py','core/strategies/four_indicator.py']
    root = Path(__file__).resolve().parents[1]
    return {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in files}


def completed_month(directory):
    """Reuse immutable completed reports; final aggregation verifies source files."""
    try:
        manifest=json.loads((directory/'research-manifest.json').read_text())
        report=json.loads((directory/'research-results.json').read_text())
        records=report['source_manifests']
        return (report['status']=='diagnostic_research_only' and
            len(records)==2 and {r['file'] for r in records}=={'underlying-manifest.json','research-manifest.json'} and
            manifest['status']=='research_downloaded' and not manifest['failures'] and all(
            hashlib.sha256((directory/r['file']).read_bytes()).hexdigest()==r['sha256']
            for r in records))
    except (OSError,ValueError,KeyError):
        return False


def run(output):
    output.mkdir(parents=True,exist_ok=True)
    plan_path = output/'frozen-plan.json'
    plan = dict(created_at=datetime.now(timezone.utc).isoformat(),
        development=['2026-04-01','2026-07-31'], comparison=['2026-08-01','2026-09-30'],
        primary=dict(timeframe_minutes=3,premium_variant='fixed_250'),
        secondary=[dict(timeframe_minutes=tf,premium_variant=variant) for tf in (3,5)
                   for variant in ('fixed_250','underlying_1pct') if (tf,variant)!=(3,'fixed_250')],
        status='rules_frozen_before_retrieval', specification=options_strategy.specification(), source_hashes=source_hashes(),
        caveats=['Retrospective comparison, not a prospective forward test.',
                 'October engineering sample already inspected; excluded from both periods.',
                 'Observed-traded diagnostics do not establish complete-chain performance.'])
    if plan_path.exists():
        previous=json.loads(plan_path.read_text())
        if previous['source_hashes'] != source_hashes():
            raise ValueError('Frozen strategy source changed. Use a new study directory.')
        plan=previous
    else:
        history.save_json(plan_path,plan)
    status_path=output/'progress.json'
    old_status=json.loads(status_path.read_text()) if status_path.exists() else {}
    status=dict(status='running',started_at=old_status.get('started_at',datetime.now(timezone.utc).isoformat()),
                resumed_at=datetime.now(timezone.utc).isoformat(),completed_months=[],current_month=None)
    token=store.token()
    with httpx.Client(timeout=40,transport=BudgetTransport(output/'request-times.json')) as client:
        for month in range(4,10):
            start=date(2026,month,1)
            end=date(2026,month+1,1)-history.timedelta(days=1)
            directory=output/f'2026-{month:02d}'
            directory.mkdir(exist_ok=True)
            if completed_month(directory):
                status['completed_months'].append(directory.name)
                history.save_json(status_path,status)
                print(f'{directory.name}: completed archive and report reused.',flush=True)
                continue
            status.update(current_month=directory.name,phase='underlying')
            history.save_json(status_path,status)
            print(f'{directory.name}: preparing underlying history.',flush=True)
            underlying_path=directory/'underlying-manifest.json'
            if not underlying_path.exists() or json.loads(underlying_path.read_text()).get('status') != 'underlying_downloaded':
                history.download_underlying(client,token,start=start,end=end,output=directory)
            status['phase']='options'
            history.save_json(status_path,status)
            result=history.download_research(client,token,start=start,end=end,output=directory,
                log=lambda value:print(f'{directory.name}: {value}',flush=True))
            if result['failures']:
                raise ValueError(f'{directory.name} download has failures; resume before publishing results.')
            status['phase']='replay'
            history.save_json(status_path,status)
            compare(directory)
            status['completed_months'].append(directory.name)
            history.save_json(status_path,status)
    if plan['source_hashes'] != source_hashes():
        raise ValueError('Strategy source changed during the frozen study.')
    status.update(phase='aggregate',current_month=None)
    history.save_json(status_path,status)
    from core.research.options_extended import aggregate
    aggregate(output)
    status.update(status='complete',phase='complete',current_month=None,finished_at=datetime.now(timezone.utc).isoformat())
    history.save_json(status_path,status)
    return status


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('artifacts/options_extended_2026'))
    parser.add_argument('--finish-running-download',action='store_true',help='Finish reporting for an already running download, without making API calls.')
    args=parser.parse_args()
    try:
        if args.finish_running_download:
            # This is part of the current local pipeline, not a scheduled task.
            while True:
                failure=args.output/'failure.json'
                if failure.exists():
                    raise ValueError('The running download failed; inspect failure.json.')
                progress=args.output/'progress.json'
                value=json.loads(progress.read_text()) if progress.exists() else {}
                if value.get('status') == 'complete':
                    break
                time.sleep(5)
            plan=json.loads((args.output/'frozen-plan.json').read_text())
            if plan['source_hashes'] != source_hashes():
                raise ValueError('Frozen strategy source changed during the download.')
            value.update(status='running',phase='aggregate')
            history.save_json(progress,value)
            from core.research.options_extended import aggregate
            aggregate(args.output)
            value.update(status='complete',phase='complete',finished_at=datetime.now(timezone.utc).isoformat())
            history.save_json(progress,value)
        else:
            run(args.output)
    except Exception as exc:
        history.save_json(args.output/'failure.json',dict(status='failed',type=type(exc).__name__,message=str(exc)))
        progress=args.output/'progress.json'
        if progress.exists():
            value=json.loads(progress.read_text())
            value.update(status='failed',reason=str(exc))
            history.save_json(progress,value)
        raise

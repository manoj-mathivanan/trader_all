"""Run one tracked local momentum experiment; inputs stay in ignored data/."""
import argparse
import sys
import time
from threading import Event
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research import jobs, momentum, store
from core.research.config import current_settings


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--config', help='JSON configuration file')
    source.add_argument('--compare', help='Saved momentum run ID for frozen-input comparisons')
    parser.add_argument('--suite', choices=['refinements','research','stronger','indicators','pullbacks','fundamentals'], default='refinements', help='Declared comparison suite (with --compare)')
    args = parser.parse_args()
    finished = Event()
    def tracked(function):
        def execute(log,job_id):
            try:
                return function(log,job_id)
            finally:
                finished.set()
        return execute
    settings = current_settings(args.compare)
    if args.compare:
        reference = store.read('runs/'+args.compare)
        if not reference:
            parser.error('Reference run unavailable.')
        cfg = momentum.MomentumConfig(**{**reference['config'],'comparison_run_id':args.compare})
        momentum.prepare(settings,cfg)
        job = jobs.submit('Momentum comparison',tracked(lambda log,job_id:momentum.compare(settings,args.compare,log,job_id,args.suite)),{'reference_id':args.compare,'suite':args.suite})
    else:
        cfg = momentum.MomentumConfig.model_validate_json(Path(args.config).read_text(encoding='utf-8'))
        settings = current_settings(cfg.comparison_run_id)
        momentum.prepare(settings, cfg)
        job = jobs.submit('Momentum backtest', tracked(lambda log, job_id: momentum.run(settings, cfg, log, job_id)), cfg.model_dump(mode='json'))
    print('Job:', job['id'], flush=True)
    seen = 0
    while True:
        record = next(j for j in store.read('jobs', []) if j['id'] == job['id'])
        for line in record['logs'][seen:]:
            print(line['message'], flush=True)
        seen = len(record['logs'])
        # A separate dashboard restart can mark persisted jobs interrupted while
        # this CLI's worker is still healthy. Wait for our actual task to finish.
        if finished.is_set() and record['status'] in ('success', 'failed'):
            time.sleep(.1)  # Allow jobs.execute to persist its terminal update.
            record = next(j for j in store.read('jobs', []) if j['id'] == job['id'])
            print(record['status'], record.get('result', {}), flush=True)
            sys.exit(0 if record['status'] == 'success' else 1)
        time.sleep(1)

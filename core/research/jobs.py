from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from pathlib import Path
import traceback
from core.research import store

POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="research")


def failure_detail(error):
    frames = traceback.extract_tb(error.__traceback__)
    location = f' at {Path(frames[-1].filename).name}:{frames[-1].lineno}' if frames else ''
    return f'Unexpected failure ({type(error).__name__}{location}). Retry this job; valid saved data is retained. No credentials were logged.'


def completion_status(result):
    if not result or not result.get('partial'):
        return 'success'
    if ('daily_symbols' in result and 'minute_symbols' in result
            and result['daily_symbols'] + result['minute_symbols'] == 0):
        return 'failed'
    if result.get('counts') and set(result['counts']) <= {'failed'}:
        return 'failed'
    return 'warning'


def recover():
    for job in store.read("jobs", []):
        if job["status"] in ("queued", "running"):
            update(job["id"], status="failed", message="Interrupted by server restart. Retry this job.")
        elif (job['status'] == 'failed' and completion_status(job.get('result')) == 'warning'
              and job.get('logs') and job['logs'][-1]['message'] ==
              'Completed all stocks with failures; inspect the result and logs, then retry.'):
            update(job['id'], status='warning', message='Completed with warnings. Saved data retained; inspect coverage details for unavailable inputs.')


def update(job_id, *, status=None, message=None, result=None):
    with store.LOCK:
        jobs = store.read("jobs", [])
        job = next(j for j in jobs if j["id"] == job_id)
        if status:
            job["status"] = status
        if message:
            job["logs"].append({"at": store.now(), "message": message})
        if result:
            job["result"] = result
        job["updated_at"] = store.now()
        store.write("jobs", jobs)


def submit(kind, function, payload=None):
    with store.LOCK:
        jobs = store.read("jobs", [])
        if any(j["status"] in ("queued", "running") for j in jobs):
            raise ValueError("Another job is active. Wait for it to finish before starting a new one.")
        job = {"id": uuid4().hex[:12], "type": kind, "status": "queued", "created_at": store.now(),
               "logs": [], "payload": payload or {}}
        jobs.insert(0, job)
        store.write("jobs", jobs)

    def execute():
        update(job["id"], status="running", message=f"Started {kind}.")
        try:
            result = function(lambda message: update(job["id"], message=message), job["id"])
            status = completion_status(result)
            message = {'warning': 'Completed with warnings. Saved data retained; inspect coverage details for unavailable inputs.',
                       'failed': 'No usable data coverage. Inspect the result and logs before retrying.',
                       'success': 'Completed.'}[status]
            update(job['id'], status=status, message=message, result=result)
        except ValueError as exc:
            update(job["id"], status="failed", message=str(exc))
        except Exception as exc:
            # Never persist HTTP request headers, tokens, or raw provider responses.
            update(job["id"], status="failed", message=failure_detail(exc))

    POOL.submit(execute)
    return job

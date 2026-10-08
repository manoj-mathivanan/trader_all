from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from core.research import store

POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="research")


def recover():
    for job in store.read("jobs", []):
        if job["status"] in ("queued", "running"):
            update(job["id"], status="failed", message="Interrupted by server restart. Retry this job.")


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
            update(job["id"], status="failed" if result and result.get("partial") else "success",
                   message="Completed all stocks with failures; inspect the result and logs, then retry." if result and result.get("partial") else "Completed.", result=result)
        except ValueError as exc:
            update(job["id"], status="failed", message=str(exc))
        except Exception:
            # Never persist HTTP request headers, tokens, or raw provider responses.
            update(job["id"], status="failed", message="Unexpected failure. Check local data integrity and retry; no credentials were logged.")

    POOL.submit(execute)
    return job

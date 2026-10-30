"""Expose background job failures as a nonzero systemd service exit."""
from forward_options_paper import main, jobs, store

if __name__=='__main__':
    main()
    jobs.POOL.shutdown(wait=True)
    latest=next(j for j in store.read('jobs',[]) if j.get('payload',{}).get('study')=='options_forward_v1')
    raise SystemExit(0 if latest['status']=='success' and latest.get('result',{}).get('study')=='options_forward_v1' else 1)

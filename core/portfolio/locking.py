"""Cross-process locks for the standalone scalping runner and its dashboard controls."""
import errno
import os
import time
from contextlib import contextmanager
from core.research import store


@contextmanager
def mutex(name, timeout=5):
    if name not in ('scalping_runner', 'scalping_portfolio', 'scalping_control', 'live_runner', 'live_control'):
        raise ValueError('Unknown process lock.')
    if name.startswith('live_'):
        from core.research import identity
        if identity.username():
            name += '__'+identity.username()
    if store.database_enabled():
        from core.research import postgres_store
        with postgres_store.mutex(name, timeout):
            yield
        return
    directory = store.DATA / 'locks'
    directory.mkdir(parents=True, exist_ok=True)
    with (directory/(name+'.lock')).open('a+b') as handle:
        if not handle.tell():
            handle.write(b'\0')
            handle.flush()
        deadline = time.monotonic()+timeout
        while True:
            try:
                handle.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if time.monotonic() >= deadline:
                    raise ValueError('Trading process lock is busy.') from None
                time.sleep(.02)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)

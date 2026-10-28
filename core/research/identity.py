"""Request identity propagated explicitly into background jobs and live runners."""
from contextvars import ContextVar
from contextlib import contextmanager

_current = ContextVar('trader_identity', default=None)


def current():
    return _current.get()


def username():
    return (current() or {}).get('username')


def admin():
    return username() == 'manoj'


@contextmanager
def scope(user):
    token = _current.set(user)
    try:
        yield
    finally:
        _current.reset(token)


def private_name(name):
    return 'users/'+username()+'/'+name if username() and name.startswith('live/') else name


def label(name, owner=None):
    owner = owner or username()
    if not owner:
        return name
    prefix = owner+': '
    return (name if name.startswith(prefix) else prefix+name)[:80]


def require_data_admin():
    if current() and not admin():
        raise ValueError('Only manoj can refresh shared market data, fundamentals and news.')

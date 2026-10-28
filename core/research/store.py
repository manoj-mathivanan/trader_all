"""Application storage with an explicit PostgreSQL cutover and legacy JSON mode."""
import json
import os
import time
from copy import deepcopy
from uuid import uuid4
from pathlib import Path
from threading import RLock, local
from datetime import datetime, timezone
from cryptography.fernet import Fernet
from contextlib import contextmanager
from core.research import identity

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("TRADER_DATA_DIR", ROOT / "data"))

def database_enabled():
    mode = os.environ.get('TRADER_STORAGE', 'postgres' if os.environ.get('TRADER_DB_DSN') or os.environ.get('TRADER_DB_DSN_FILE') else 'json')
    if mode not in ('json', 'postgres'):
        raise ValueError('TRADER_STORAGE must be json or postgres.')
    return mode == 'postgres'


def ensure_ready():
    if database_enabled():
        from core.research import postgres_store
        ready = postgres_store.read('storage/migration_ready', {})
        if ready.get('status') != 'verified' or postgres_store.read('strategy_catalog') is None:
            raise ValueError('Database migration is incomplete. Verify the migration before starting the application.')
        if token_saved():
            token()  # Check that this environment can unlock its own token.


@contextmanager
def application_lock():
    if database_enabled():
        from core.research import postgres_store
        with postgres_store.mutex('application-instance', timeout=0):
            yield
    else:
        yield


class StoreLock:
    """Make existing read/modify/write blocks atomic across database processes."""
    def __init__(self):
        self.lock = RLock()
        self.state = local()

    def __enter__(self):
        self.lock.acquire()
        depth = getattr(self.state, 'depth', 0)
        try:
            if depth == 0 and database_enabled():
                from core.research import postgres_store
                self.state.transaction = postgres_store.transaction()
                self.state.transaction.__enter__()
            self.state.depth = depth + 1
            return self
        except BaseException:
            self.state.transaction = None
            self.lock.release()
            raise

    def __exit__(self, *error):
        try:
            self.state.depth -= 1
            if self.state.depth == 0 and getattr(self.state, 'transaction', None):
                transaction, self.state.transaction = self.state.transaction, None
                return transaction.__exit__(*error)
        finally:
            self.lock.release()


LOCK = StoreLock()


def validate_name(name):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name or name.startswith('/') or any(p in ('', '.', '..') for p in name.split('/')):
        raise ValueError('Invalid storage key.')
    return name


def private_dir():
    return Path(os.environ.get('TRADER_PRIVATE_DIR', DATA / 'private'))


def now():
    return datetime.now(timezone.utc).isoformat()


def read(name, default=None):
    name = identity.private_name(name)
    validate_name(name)
    if database_enabled():
        from core.research import postgres_store
        return postgres_store.read(name, default)
    with LOCK:
        path = DATA / (name + ".json")
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write(name, value):
    name = identity.private_name(name)
    validate_name(name)
    with LOCK:
        if identity.username():
            def attributed(record, previous=None):
                record = deepcopy(record)
                owner = (previous or {}).get('created_by') or identity.username()
                record['created_by'] = owner
                if isinstance(record.get('config'), dict) and 'name' in record['config']:
                    record['config']['name'] = identity.label(record['config']['name'], owner)
                return record
            if (name.startswith(('runs/', 'portfolios/', 'portfolio_scenarios/')) or name=='paper_portfolio') and isinstance(value, dict):
                value = attributed(value, read(name))
            elif name == 'runs_index' and isinstance(value, list):
                previous = {r['id']: r for r in read(name, [])}
                value = [attributed(r) if r['id'] not in previous else r for r in value]
        if database_enabled():
            from core.research import postgres_store
            return postgres_store.write(name, value)
        path = DATA / (name + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f'.{path.name}.{uuid4().hex}.tmp')
        try:
            with temp.open('x', encoding='utf-8') as pending:
                json.dump(value, pending, allow_nan=False, indent=2)
                pending.flush()
                os.fsync(pending.fileno())
            for attempt in range(5):
                try:
                    temp.replace(path)
                    break
                except PermissionError:
                    if attempt == 4:
                        raise
                    # Windows readers/virus scanners can briefly deny replacement.
                    time.sleep(.05 * 2 ** attempt)
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass


def cipher():
    if os.environ.get('TRADER_TOKEN_KEY'):
        return Fernet(os.environ['TRADER_TOKEN_KEY'].encode())
    path = Path(os.environ.get("TRADER_KEY_FILE", ROOT / ".local-key"))
    with LOCK:
        if not path.exists():
            if database_enabled():
                raise ValueError('Database token encryption requires TRADER_TOKEN_KEY or an existing TRADER_KEY_FILE.')
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as keyfile:
                keyfile.write(Fernet.generate_key())
            path.chmod(0o600)
        return Fernet(path.read_bytes())


def credential_owner(trading=False):
    return 'user:'+identity.username() if trading and identity.username() else os.environ.get('TRADER_USER_ID', 'owner')


def save_token(value, *, trading=False):
    with LOCK:
        if database_enabled():
            from core.research import postgres_store
            return postgres_store.save_token(credential_owner(trading), cipher().encrypt(value.encode()))
        if trading and identity.username():
            return write('private/user_tokens/'+identity.username(), {'encrypted_token': cipher().encrypt(value.encode()).decode()})
        private_dir().mkdir(parents=True, exist_ok=True)
        path = private_dir() / 'upstox.json'
        temp = path.with_suffix('.tmp')
        with temp.open('w', encoding='utf-8') as pending:
            os.chmod(temp, 0o600)
            json.dump({'access_token': value, 'saved_at': now()}, pending)
            pending.flush()
            os.fsync(pending.fileno())
        temp.replace(path)


def token_saved(*, trading=False):
    if database_enabled():
        from core.research import postgres_store
        return postgres_store.token_saved(credential_owner(trading))
    if trading and identity.username():
        return bool(read('private/user_tokens/'+identity.username()))
    return (private_dir() / 'upstox.json').exists() or bool(read('private/upstox'))


def token(*, trading=False):
    if database_enabled():
        from core.research import postgres_store
        value = postgres_store.token(credential_owner(trading))
        if not value:
            raise ValueError('Save your Upstox access token in Settings first.')
        return cipher().decrypt(value).decode()
    if trading and identity.username():
        record = read('private/user_tokens/'+identity.username())
        if not record:
            raise ValueError('Save your personal trading token in Settings first.')
        return cipher().decrypt(record['encrypted_token'].encode()).decode()
    path = private_dir() / 'upstox.json'
    record = json.loads(path.read_text(encoding='utf-8')) if path.exists() else read('private/upstox')
    if not record:
        raise ValueError("Save your Upstox access token in Settings first.")
    if 'access_token' in record:
        return record['access_token']
    # Read existing local installations without losing their saved connection.
    return cipher().decrypt(record["encrypted_token"].encode()).decode()


def keys(prefix='', *, recursive=False):
    if prefix:
        validate_name(prefix.rstrip('/'))
    if database_enabled():
        from core.research import postgres_store
        return postgres_store.keys(prefix, recursive)
    # Key enumeration replaces runtime directory scans; source-code files remain
    # ordinary files and are deliberately outside this API.
    base = DATA / prefix.rstrip('/')
    if not prefix.endswith('/') and prefix:
        base = base.parent
    paths = base.rglob('*.json') if recursive else base.glob('*.json')
    return sorted(p.relative_to(DATA).as_posix()[:-5] for p in paths
                  if p.relative_to(DATA).as_posix()[:-5].startswith(prefix))


def version(name):
    name = identity.private_name(name)
    validate_name(name)
    if database_enabled():
        from core.research import postgres_store
        return postgres_store.version(name)
    try:
        stat = (DATA / (name+'.json')).stat()
        return (stat.st_ino, stat.st_ctime_ns, stat.st_mtime_ns, stat.st_size)
    except FileNotFoundError:
        return None


def records(prefix='', *, recursive=False):
    """Yield documents in bounded batches, avoiding one network trip per file."""
    names = keys(prefix,recursive=recursive)
    for start in range(0,len(names),128):
        batch = names[start:start+128]
        if database_enabled():
            from core.research import postgres_store
            values = postgres_store.read_many(batch)
        else:
            values = {name:read(name) for name in batch}
        for name in batch:
            if name in values:
                yield name,values[name]


def exists(name):
    return version(name) is not None


def read_bytes(name):
    validate_name(name)
    if database_enabled():
        from core.research import postgres_store
        return postgres_store.read_bytes(name)
    return (DATA / name).read_bytes()


def write_bytes(name, data):
    validate_name(name)
    with LOCK:
        if database_enabled():
            from core.research import postgres_store
            return postgres_store.write_bytes(name, data)
        path = DATA / name
        path.parent.mkdir(parents=True, exist_ok=True)
        pending = path.with_name('.'+path.name+'.'+uuid4().hex+'.tmp')
        try:
            with pending.open('xb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            pending.replace(path)
        finally:
            pending.unlink(missing_ok=True)

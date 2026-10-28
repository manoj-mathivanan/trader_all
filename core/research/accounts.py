"""Database-backed accounts, salted passwords and revocable opaque sessions."""
import base64
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from core.research import store

COOKIE = 'trader_session'
SESSION_SECONDS = 12*60*60


def enabled():
    return store.database_enabled() or os.environ.get('TRADER_USER_LOGIN') == '1'


def normalize(value):
    value = value.strip().lower()
    if not re.fullmatch('[a-z][a-z0-9_]{2,31}', value):
        raise ValueError('Use 3–32 lowercase letters, numbers or underscores, starting with a letter.')
    return value


def password_hash(password, salt=None):
    if not 6 <= len(password) <= 128:
        raise ValueError('Use a password of 6–128 characters.')
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=3, maxmem=64*1024*1024, dklen=32)
    return 'scrypt$'+base64.b64encode(salt).decode()+'$'+base64.b64encode(digest).decode()


def matches(password, encoded):
    try:
        algorithm, salt, _ = encoded.split('$')
        if algorithm != 'scrypt':
            return False
        return hmac.compare_digest(password_hash(password, base64.b64decode(salt)), encoded)
    except (ValueError, TypeError):
        return False


_DUMMY_HASH = password_hash('invalid-password-value', b'0'*16)


def public(user):
    return dict(username=user['username'], is_admin=user['username']=='manoj',
                enabled=user.get('enabled', True), created_at=user.get('created_at'))


def users():
    return [public(u) for _, u in store.records('auth/users/')]


def create(username, password, *, bootstrap=False):
    username = normalize(username)
    encoded = password_hash(password)
    with store.LOCK:
        if store.read('auth/users/'+username):
            raise ValueError('That username already exists.')
        if username == 'manoj' and not bootstrap:
            raise ValueError('The admin account already has a dedicated setup flow.')
        if bootstrap and (username != 'manoj' or store.keys('auth/users/')):
            raise ValueError('Admin setup has already been completed.')
        user = dict(username=username, password_hash=encoded, enabled=True,
                    created_at=store.now(), session_version=1)
        store.write('auth/users/'+username, user)
    return public(user)


def ensure_admin():
    if not enabled():
        return
    password = os.environ.get('DASHBOARD_ADMIN_PASSWORD')
    if password and not store.read('auth/users/manoj'):
        # Import the existing administrator password once; never expose it.
        # Existing installations may use shorter passwords than new accounts.
        if len(password) < 6:
            raise ValueError('Set DASHBOARD_ADMIN_PASSWORD to at least 6 characters before enabling user login.')
        create('manoj', password, bootstrap=True)
    if store.read('auth/users/manoj'):
        migrate_legacy()


def migrate_legacy():
    """Preserve the original owner's broker ledger without sharing it."""
    from core.research import identity
    with store.LOCK:
        if store.read('auth/legacy_owner_migrated'):
            return
        names = store.keys('live/', recursive=True)
        for name in names:
            target = 'users/manoj/'+name
            if store.read(target) is None:
                store.write(target, store.read(name))
        if store.token_saved():
            with identity.scope(public(store.read('auth/users/manoj'))):
                if not store.token_saved(trading=True):
                    store.save_token(store.token(), trading=True)
        store.write('auth/legacy_owner_migrated', dict(username='manoj', documents=len(names), at=store.now()))


def now():
    return datetime.now(timezone.utc)


def login(username, password, client):
    try:
        username = normalize(username)
    except ValueError:
        username = 'invalid'
    key = hashlib.sha256((client+':'+username).encode()).hexdigest()
    with store.LOCK:
        attempt = store.read('auth/attempts/'+key, {})
        if attempt and datetime.fromisoformat(attempt['until']) > now() and attempt['count'] >= 5:
            return None, 'limited'
        if not attempt or datetime.fromisoformat(attempt['until']) <= now():
            attempt = dict(count=0, until=(now()+timedelta(minutes=15)).isoformat())
        user = store.read('auth/users/'+username)
        encoded = user.get('password_hash') if user else _DUMMY_HASH
        valid = matches(password, encoded)
        if not user or not user.get('enabled') or not valid:
            attempt['count'] += 1
            store.write('auth/attempts/'+key, attempt)
            return None, 'invalid'
        store.write('auth/attempts/'+key, dict(attempt, count=0))
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode()).hexdigest()
        store.write('auth/sessions/'+digest, dict(username=username,
                    session_version=user['session_version'], expires_at=(now()+timedelta(seconds=SESSION_SECONDS)).isoformat()))
        return token, public(user)


def session(token):
    if not token or not re.fullmatch('[A-Za-z0-9_-]{43}', token):
        return None
    record = store.read('auth/sessions/'+hashlib.sha256(token.encode()).hexdigest())
    if not record or record.get('revoked') or datetime.fromisoformat(record['expires_at']) <= now():
        return None
    user = store.read('auth/users/'+record['username'])
    if not user or not user.get('enabled') or user['session_version'] != record['session_version']:
        return None
    return public(user)


def logout(token):
    if token and re.fullmatch('[A-Za-z0-9_-]{43}', token):
        key = 'auth/sessions/'+hashlib.sha256(token.encode()).hexdigest()
        with store.LOCK:
            value = store.read(key)
            if value:
                store.write(key, dict(value, revoked=True))


def update(username, *, password=None, active=None):
    username = normalize(username)
    encoded = password_hash(password) if password is not None else None
    with store.LOCK:
        user = store.read('auth/users/'+username)
        if not user:
            raise ValueError('User not found.')
        if username == 'manoj' and active is False:
            raise ValueError('The admin account cannot be disabled.')
        if encoded:
            user['password_hash'] = encoded
        if active is not None:
            user['enabled'] = active
        user['session_version'] += 1
        store.write('auth/users/'+username, user)
    return public(user)

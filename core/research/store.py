"""Atomic local research artifacts. Replace with Postgres/RQ for deployment."""
import json
import os
from pathlib import Path
from threading import RLock
from datetime import datetime, timezone
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("TRADER_DATA_DIR", ROOT / "data"))
LOCK = RLock()


def private_dir():
    return Path(os.environ.get('TRADER_PRIVATE_DIR', DATA / 'private'))


def now():
    return datetime.now(timezone.utc).isoformat()


def read(name, default=None):
    with LOCK:
        path = DATA / (name + ".json")
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write(name, value):
    with LOCK:
        path = DATA / (name + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        with temp.open('w', encoding='utf-8') as pending:
            json.dump(value, pending, allow_nan=False, indent=2)
            pending.flush()
            os.fsync(pending.fileno())
        temp.replace(path)


def cipher():
    path = Path(os.environ.get("TRADER_KEY_FILE", ROOT / ".local-key"))
    with LOCK:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as keyfile:
                keyfile.write(Fernet.generate_key())
            path.chmod(0o600)
        return Fernet(path.read_bytes())


def save_token(value):
    with LOCK:
        private_dir().mkdir(parents=True, exist_ok=True)
        path = private_dir() / 'upstox.json'
        temp = path.with_suffix('.tmp')
        with temp.open('w', encoding='utf-8') as pending:
            os.chmod(temp, 0o600)
            json.dump({'access_token': value, 'saved_at': now()}, pending)
            pending.flush()
            os.fsync(pending.fileno())
        temp.replace(path)


def token_saved():
    return (private_dir() / 'upstox.json').exists() or bool(read('private/upstox'))


def token():
    path = private_dir() / 'upstox.json'
    record = json.loads(path.read_text(encoding='utf-8')) if path.exists() else read('private/upstox')
    if not record:
        raise ValueError("Save your Upstox access token in Settings first.")
    if 'access_token' in record:
        return record['access_token']
    # Read existing local installations without losing their saved connection.
    return cipher().decrypt(record["encrypted_token"].encode()).decode()

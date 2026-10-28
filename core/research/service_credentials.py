"""Shared service secrets are encrypted in storage; never returned by APIs."""
import os
from core.research import store


def key():
    value = store.read('private/services/openai', {})
    return store.cipher().decrypt(value['encrypted'].encode()).decode() if value.get('encrypted') else os.environ.get('OPENAI_API_KEY', '')


def model():
    return store.read('private/services/research', {}).get('model') or os.environ.get('TRADER_NEWS_MODEL', '')


def save(api_key=None, research_model=None):
    with store.LOCK:
        if api_key:
            store.write('private/services/openai', dict(encrypted=store.cipher().encrypt(api_key.encode()).decode()))
        if research_model:
            store.write('private/services/research', dict(model=research_model))


def status():
    return dict(market_token_saved=store.token_saved(), research_key_saved=bool(key()), research_model=model())

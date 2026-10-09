"""Upstox V3 full-feed decoding and secure quote transport. No order APIs."""
import json
import math
from datetime import datetime
from urllib.parse import quote, urlsplit
from uuid import uuid4

import httpx
import websocket
from google.protobuf.message import DecodeError
from core.market_data import MarketDataFeed_pb2 as proto
from core.research import intraday_data, store


def decode(payload):
    response = proto.FeedResponse()
    try:
        response.ParseFromString(payload)
    except DecodeError:
        raise ValueError('Malformed Upstox binary market feed.') from None
    status = None
    if response.HasField('marketInfo') and 'NSE_EQ' in response.marketInfo.segmentStatus:
        status = proto.MarketStatus.Name(response.marketInfo.segmentStatus['NSE_EQ'])
    updates = []
    for key, feed in sorted(response.feeds.items()):
        if not key.startswith('NSE_EQ|') or feed.WhichOneof('FeedUnion') != 'fullFeed' or feed.fullFeed.WhichOneof('FullFeedUnion') != 'marketFF':
            continue
        market = feed.fullFeed.marketFF
        if not market.marketLevel.bidAskQuote:
            continue
        depth = market.marketLevel.bidAskQuote[0]
        values = (market.ltpc.ltp, depth.bidP, depth.askP)
        if not all(math.isfinite(p) and p > 0 for p in values) or depth.bidP > depth.askP or min(depth.bidQ, depth.askQ) <= 0:
            continue
        updates.append(dict(key=key, timestamp=int(response.currentTs), trade_timestamp=int(market.ltpc.ltt),
                            price=market.ltpc.ltp, bid=depth.bidP, ask=depth.askP,
                            bid_quantity=int(depth.bidQ), ask_quantity=int(depth.askQ)))
    return dict(kind=proto.Type.Name(response.type), timestamp=int(response.currentTs), market_status=status, quotes=updates)


def authorized_url(token):
    # Neither exception text nor the single-use credential-bearing URL reaches logs.
    try:
        with httpx.Client(timeout=15) as client:
            response = client.get('https://api.upstox.com/v3/feed/market-data-feed/authorize',
                                  headers={'Authorization':'Bearer '+token, 'Accept':'application/json'})
            response.raise_for_status()
            payload = response.json()
        uri = payload['data']['authorized_redirect_uri']
        parsed = urlsplit(uri)
        if payload.get('status') != 'success' or parsed.scheme != 'wss' or not parsed.hostname or not parsed.hostname.endswith('.upstox.com') or parsed.username:
            raise ValueError()
        return uri
    except Exception:
        raise ValueError('Upstox stream authorization failed. Check token and market-data permissions.') from None


def connect(keys, token=None):
    socket = None
    try:
        socket = websocket.create_connection(authorized_url(token or store.token()), timeout=2,
                                             enable_multithread=True)
        socket.send_binary(json.dumps(dict(guid=uuid4().hex, method='sub',
                                          data=dict(mode='full', instrumentKeys=keys))).encode())
        return socket
    except Exception:
        if socket:
            try:
                socket.close()
            except Exception:
                pass
        raise ValueError('Upstox market-feed connection failed; no credentials were logged.') from None


def completed_minutes(item, day, clock, *, client=None):
    """REST completed candles, independent of sampled ticks and incomplete feed OHLC."""
    owned = client is None
    client = client or httpx.Client(timeout=10)
    try:
        url = f"https://api.upstox.com/v3/historical-candle/intraday/{quote(item['key'], safe='')}/minutes/1"
        response = client.get(url, headers={'Authorization':'Bearer '+store.token(), 'Accept':'application/json'})
        response.raise_for_status()
        payload = response.json()
        if payload.get('status') != 'success':
            raise ValueError()
        # Two-second publication grace; unfinished candle rows are never normalized as signals.
        cutoff = int(clock.timestamp()*1000)-2000
        raw = []
        for row in payload.get('data', {}).get('candles', []):
            instant = datetime.fromisoformat(row[0])
            if instant.tzinfo is None:
                raise ValueError()
            instant = instant.astimezone(intraday_data.IST)
            if instant.date().isoformat() != day:
                raise ValueError()
            if int(instant.timestamp()*1000)+60000 <= cutoff:
                raw.append(row)
        bars = intraday_data.normalize(raw, day, 1)
        return [b for b in bars if '09:15' <= b['time'] <= '15:29']
    except Exception:
        raise ValueError(f"Completed one-minute history unavailable for {item['symbol']}; entries remain blocked.") from None
    finally:
        if owned:
            client.close()

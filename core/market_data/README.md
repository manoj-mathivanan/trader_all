# Upstox feed schema

`MarketDataFeed.proto` is the provider's V3 market-feed schema, downloaded from
[Upstox's official schema](https://assets.upstox.com/feed/market-data-feed/v3/MarketDataFeed.proto).
`MarketDataFeed_pb2.py` is generated from that file using `grpcio-tools` 1.84.0
(protobuf code generator 7.35.1). Production requires protobuf, not the generator.

Regenerate from the repository root with:

```powershell
python -m grpc_tools.protoc -I core/market_data --python_out=core/market_data core/market_data/MarketDataFeed.proto
```

Transport follows the provider's [V3 full-feed documentation](https://upstox.com/developer/api-documentation/v3/get-market-data-feed/):
authorize a single-use secure WebSocket URL, send a binary JSON subscription,
and decode protobuf frames. Authentication failures and credential-bearing URLs
are kept out of dashboard logs. This module makes no order requests.

# Nifty 50 constituent one-minute history

Verified on 4 November 2026: all 50 matched current constituents have full
coverage from 1 October 2024 through 3 November 2026, with 518 sessions each
(25,900 stock-sessions) and 9,680,865 continuous-session minute candles in the
shared database, namespace `local`. No expected continuous-session minutes or
sessions are missing. Ordinary stocks have 193,620 candles each; ITC,
HINDUNILVR and TMPV each have 193,575 because of their published special
pre-open sessions. A separate SQL inventory confirms all reported totals.

The final dataset SHA-256 is
`6941eebd2560bca0ef96842f9aed4231489b463b1e1b192c2595e6022c0c79b4`.

`scripts/backfill_nifty50_stock_minutes.py` backfills the current 50 Nifty stocks
for 1 October 2024–3 November 2026 into the existing shared PostgreSQL namespace.
The official NSE constituent CSV is matched to Upstox instruments by ISIN. Its
raw CSV, checksum and matched identities are retained as an immutable run scope.
This is a current-constituent dataset; historical index membership is separate.

Run in the configured backend environment:

```powershell
python scripts/backfill_nifty50_stock_minutes.py --output artifacts/nifty50-stock-minutes
```

The reviewed exchange calendar expects 518 sessions per stock, including the
2024 and 2025 Muhurat sessions and 2025 and 2026 Budget weekend sessions. Dates
outside the reviewed range are rejected. Ingestion ends before the current day.

Existing candles are checked for valid OHLCV, date/time normalization, duplicate
timestamps and exact session minute coverage. Complete sessions are reused.
Missing or incomplete ranges are requested in bounded 28-day windows, with up
to three provider requests in flight. Database writes use existing transactions
and session projection code. Original provider responses are archived before
normalization; invalid provider days are quarantined rather than accepted.

Incomplete sessions receive individual V3 retries and V2 probes. The job does
not invent missing prices or substitute another stock. A better existing
session is retained if a retry is less complete. Unexpected after-hours candles
remain in raw evidence and are excluded from canonical trading minutes.

Every stock is audited again from persisted data, verifying compressed content
checksums, canonical documents and SQL projections, actual minute timestamps,
OHLCV validity and a hash of ordered candles. Each report records missing
sessions, exact missing minute times, invalid provider observations, retries,
the eligible-session list and whether the whole requested window is complete.

Instrument-specific demerger sessions use NSE's published 10:00 continuous-market
opening: ITC on 6 January 2025 (CMTR65845), HINDUNILVR on 5 December 2025
(CMTR71508), and TMPV/former TATAMOTORS on 14 October 2025 (CMTR70614).
These dates require 330 continuous-market minute bars rather than 375. Any
provider prints during the special pre-open auction remain archived separately
and cannot be treated as continuous-market fills. Session rules are scoped by
both ISIN and date; other stocks retain their normal opening time.

Use `--audit-only` after ingestion to repeat the persisted-data audit with the
instrument-specific session rules. The initial regular-clock report is retained
as evidence; the final report replaces it only after all stocks are checked.

Storage keys:

- Candles: `intraday/1m/<ISIN>/YYYY-MM-DD`
- Universe: `market_archives/nifty50_stocks_1m/2024-10-01_2026-11-03/universe`
- Stock report: the same prefix plus `/stocks/<ISIN>/verification`
- Overall report: the same prefix plus `/verification`
- Raw responses: the same prefix plus `/responses/<ISIN>/...`

The job checkpoints after every stock, uses an ingestion mutex, and is resumable.
Restarting reuses complete stored sessions and the same frozen constituent list.
Failure of one instrument is reported without preventing the others from being
audited. Overall completion requires 50 complete instrument reports; process
exit code 2 indicates coverage gaps or stock failures requiring attention.

Backtests must use actual stock candles and each report's eligibility list.
Historical constituent membership, corporate-action treatment, execution costs,
bid/ask spreads, liquidity constraints and short eligibility need to be specified
by the backtest separately from this coverage audit.

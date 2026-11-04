# Nifty 50 index one-minute history

Verified on 3 November 2026 in the shared server database, namespace `local`:
517 expected sessions are stored, containing 193,241 in-session candles. Of those,
513 sessions are complete. Four sessions each lack one provider minute:

| Session | Missing timestamp (IST) |
| --- | --- |
| 2024-12-12 | 09:42 |
| 2025-03-25 | 10:42 |
| 2025-04-04 | 11:57 |
| 2025-04-23 | 10:36 |

Both single-day V3 retries and V2 probes returned the same omissions. No entire
session is missing. Ten after-hours provider candles across five other sessions
were excluded from canonical trading bars and retained as evidence. Use the
database verification report's eligibility list for subsequent backtests.

`scripts/pull_nifty_minute_history.py` ingests the index instrument
`NSE_INDEX|Nifty 50` into the configured PostgreSQL namespace. The default
range is 1 October 2024–2 November 2026, ending before the current session.
It requires the existing saved Upstox market-data token and database settings.

Run inside the existing backend environment:

```powershell
python scripts/pull_nifty_minute_history.py --output artifacts/nifty50-minute-verification.json
```

Daily session documents use `intraday/1m/NIFTY50/YYYY-MM-DD` and are projected
into `trader.intraday_sessions` with `isin=NIFTY50`, `interval_minutes=1`.
Original provider responses and the verification report are retained under
`market_archives/nifty50_1m/2024-10-01_2026-11-02/` in database document storage.
The verification document is named `verification` under that prefix.

The audit compares NSE holiday and special-session rules with independently
requested daily candles and persisted minute sessions. Every canonical session
is reloaded, checksum-validated, normalized, and compared with its SQL projection.
The report lists missing timestamps, missing sessions, unexpected sessions, and a
SHA-256 over the ordered candle data. Single-session V3 retries and V2 probes
retain raw evidence for incomplete sessions. Requests use bounded 28-day windows;
reruns reuse archived responses and skip unchanged canonical candle data.

Regular sessions contain minute-open timestamps 09:15–15:29 IST. Muhurat sessions
use the published session times. After-hours provider rows remain in the raw
archive and in `excluded_out_of_session_bars`, outside the canonical candle list.

For backtests, read the latest verification document and use only
`eligible_sessions`. Any missing minute disqualifies its whole session unless
the experiment explicitly declares another missing-data policy. Never forward-fill
or manufacture OHLC prices. `backtest_ready` is deliberately false if any expected
session is incomplete, even when the remaining sessions are usable.

Nifty index volume is not traded volume. Coverage verification does not certify
the vendor's price accuracy. Daily index OHLC and aggregated minute OHLC are
separate observations and may differ.

The calendar is reviewed only for the default bounded date range; extending it
requires reviewing new exchange holidays and special trading sessions.

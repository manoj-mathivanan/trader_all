# NIFTYBEES one-minute history

The official Upstox NSE instrument master resolves NIFTYBEES to
`NSE_EQ|INF204KB14I2` (ISIN `INF204KB14I2`). It is stored separately from the
Nifty 50 index, whose cache identity remains `NIFTY50`.

The shared PostgreSQL database (namespace `local`) contains 193,245 ETF minute
candles from 1 October 2024 through 2 November 2026. All 517 expected sessions
passed the session and minute coverage audit, including Muhurat and Budget
weekend sessions. No missing minutes, duplicate minutes or after-hours rows
were found. Verification includes OHLC validation, checksum verification and
comparison of canonical database documents with the SQL session projection.

Run `python scripts/pull_niftybees_history.py` in the configured backend
environment to reuse archived data and repeat ingestion, verification and the
index comparison. Raw responses are retained in database document storage.

Database keys:

- Candles: `intraday/1m/INF204KB14I2/YYYY-MM-DD`
- Coverage: `market_archives/niftybees_1m/2024-10-01_2026-11-02/verification`
- Comparison: `market_archives/niftybees_1m/2024-10-01_2026-11-02/index_comparison`

The comparison matched 193,241 ETF and index minute timestamps. At 15:29 IST on
2 November 2026, the ETF candle close was INR 266.25 while the index candle
close was 23,440.80 points. The index/ETF price ratio varied from approximately
87.04 to 89.80 across the sample; it is not a fixed conversion factor.
Consecutive within-session one-minute return correlation was approximately
0.688 (192,720 pairs). These are vendor candle observations, not executable
bid/ask prices or total returns.

Backtest fills and ETF indicators must use actual ETF candles and volume.
The index history can be used separately for market signals. A strategy using
both datasets must account for the index's four incomplete sessions; the ETF
has full coverage on those dates.

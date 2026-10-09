# Quarterly fundamentals cache and buy screens

The market-history fetch now checks fundamentals for the same 750-stock total-market universe after saving daily and five-minute candles. This stage uses official NSE Ind-AS HTML filings, without an LLM/API key, third-party numeric inference or BSE fallback. Market-data selection and the smaller research universe do not limit this bulk pull.

Standalone commands, from the repository root:

```powershell
.\.venv\Scripts\python.exe scripts/pull_fundamentals.py
.\.venv\Scripts\python.exe scripts/pull_fundamentals.py --validate-only
.\.venv\Scripts\python.exe scripts/pull_fundamentals.py --symbols TCS STLTECH --retry-failed
```

Each `data/company/fundamentals/<ISIN>.json` stores the snapshot, deterministic score/checks, source documents, validation, `last_checked_at`, `last_attempted_at`, `last_pulled_at`, `last_period_end` and `next_quarter_end`. Successful versions are retained under `<ISIN>/history/`. Raw source files are in `data/company/filings/`. All timestamps include a timezone. The bulk progress/report is `data/company/fundamentals_pull.json`; the independent audit is `data/company/fundamentals_validation.json`.

A snapshot covering the latest completed calendar quarter is skipped without network requests until the next quarter ends. Otherwise the NSE index is checked at most once daily. If it still contains the stored quarter, no financial documents are downloaded and the last successful pull date stays unchanged. This avoids missing results published several weeks after quarter end. Failed downloads may be retried explicitly on the same day with `--retry-failed`; repeated ordinary pulls leave them for the next day. A failed new quarter cannot replace an older valid snapshot. This deliberately does not ingest same-quarter revisions after that quarter is stored.

The pull chooses consolidated filings when available, with matching previous-year quarterly and annual comparables. It validates exact company identity, dates, periods, accounting basis, INR units, source SHA-256 checksums, parsed source rows and recomputed metrics before saving. Missing annual comparables, missing balance-sheet inputs or ambiguous figures remain unknown. Bank/NBFC taxonomies, REITs and unsupported NSE forms currently do not receive fabricated scores. Such instruments remain blocked when the required evidence is absent; attempting every stock does not guarantee a score for every stock.

The Fundamentals page has separate saved **Fundamental buy screens** for Swing and Intraday momentum. Defaults: score at least 60/100, evidence coverage at least 80%, financial period at most 180 days old. Missing evidence and flagged concerns block new buys. Thresholds are configurable through the screen forms and `PUT /api/company/buy-screen/{strategy}`. `GET /api/company/buy-check/{strategy}/{ISIN}` returns eligibility, reasons, score, metrics and dates. The per-stock **Check buy** button compares both strategies.

Current swing technical candidates and forward swing paper entries enforce the buy screen. Paper checks record the snapshot ID, thresholds and rejection reasons in the cycle journal, with evidence available by the decision time. Existing positions still receive exits. Intraday momentum remains research-only (no paper/live execution module); its prospective check uses the same stored-score gate and its engine accepts an explicit entry-check callback for future execution integration. Historical backtests never inject today's cache: both engines' historical defaults remain unchanged.

P/E, promoter pledging and full governance research are not added by this pull. News remains a separate on-demand LLM review. The score is the existing experimental fundamental score, not a validated return predictor.

New long swing backtests and paper portfolios in the UI default to five positions and `fundamental_score` priority. API/model defaults retain alphabetical priority for legacy callers. Company scans rank passing candidates by score and show the first five recommendations. Score ties prefer evidence coverage, then symbol. Open holdings are not replaced merely because another stock scores higher.

Historical fundamental ranking uses `core/research/fundamental_history.py` to reconstruct scores from verified archived NSE filings, applying each filing's publication timestamp to every input (including older-period comparables). It does not substitute the current cache for past decisions. Evidence is downloaded retrospectively and intermediate quarters/revisions are incomplete. Missing, stale or flagged historical scores rank last; ranking alone does not enforce the live buy screen. Frozen financial inputs and a checksum are stored at `data/run_fundamentals/<run-id>.json`; frozen comparisons reuse them. Long intraday swing screens also support this priority; bearish short screens reject it.

Run the matched comparison with `scripts/compare_fundamental_ranking.py --reference <saved-swing-run-id> --start 2026-06-01 --end 2026-10-01`. It holds price inputs, costs, signals and exits fixed within each pair and changes only ranking, with five positions in both. Results are in [FUNDAMENTAL_RANKING_COMPARISON.md](FUNDAMENTAL_RANKING_COMPARISON.md).

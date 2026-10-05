# Data-validity safeguards — first increment

These checks do not establish a trading edge or certify corporate-action adjustment.
No historical report, provider candle or paper ledger is migrated by this change.

## Price-history audit and circuit breaker

Market data → **Audit price history** reads the selected universe's current cached
history and lists absolute opening gaps of **35% or more** versus the previous
observed close. It shows both dates: the prior observation can be years earlier.
The audit is read-only and does not call Upstox or repair prices.

New backtest jobs halt if this check finds a gap anywhere in their input history
through the test end, including indicator warmup. This deliberately blocks a run
until suspect data is independently investigated. There is no automatic bypass.
The error identifies the first symbol/date and the number of findings; the UI
audit lists the full current-cache findings.

Paper cycles halt before simulation/ledger commit for gaps in newly processed
sessions, including the transition from the last processed close. Pausing entries
does not bypass this check: a held position can also have invalid accounting.
Ingestion may still update the provider cache; the paper ledger stays unchanged.
Already processed history retains its existing fingerprint guard. Review warmup
and previously processed inputs separately; this incremental check does not
retroactively certify them.

Legitimate gaps can trigger this rule; smaller actions can escape it. Splits,
bonuses, mergers, instrument history stitching and provider errors require
different remedies. Do not apply split factors merely because a gap exists, and
do not edit a ledger to make a failed cycle resume.

For a local audit including overlaps with existing report holding periods:

```powershell
.venv/Scripts/python.exe scripts/audit_data.py --output artifacts/my-price-audit.json
```

Use a new output filename. Optional `--data-dir` selects another local data copy.
The output compares current cached bars with report trade dates; it does not
scan each frozen report input, match an event calendar, or measure warmup,
breadth/ranking or missed-signal impacts. No overlap is not a clean bill of health.

## Initial local observations (4 October 2026)

The local cache audit scanned 500 symbols and 112 saved reports and found 31
large gaps. None intersected the recorded holding periods under this limited
current-cache comparison. Several findings warrant instrument-identity checks:

| Symbol | Previous observation | New observation | Prices |
|---|---|---|---|
| RAINBOW | 4 June 2019 | 10 May 2022 | Previous close ₹0.75 → open ₹510 |
| KFINTECH | 29 May 2018 | 29 December 2022 | Previous close ₹11.95 → open ₹367 |
| PRIVISCL | 20 August 2020 | 21 August 2020 | Previous close ₹0.15 → open ₹527 |

These are suspicious transitions, not confirmed corporate-action classifications.
They must not be automatically converted into adjustment factors.

Nestlé's issuer filing documents a ten-for-one split effective 5 January 2024:
[issuer filing](https://www.nestle.in/sites/g/files/pydnoa451/files/2025-01/BSENSEUFRs_31.12.2024.pdf).
The local NESTLEIND cache has a 4 January close of ₹1,355.80 and a 5 January open
of ₹1,377.00. Continuity across the event suggests that at least this price series
is already adjusted. This observation does not verify volume adjustment, all
events, or all instruments. An automatic global backward-adjustment pass would
therefore be premature.

Next: verify instrument identity for flagged histories and compare a sourced
sample of split/bonus events with prices and volume before designing adjustment
and held-position accounting. Preserve raw evidence and existing reports.

## IPO eligibility

IPO signals now require a verified, sourced listing date and a signal-date age
between zero and `ipo_max_age_days` inclusive. The default is **730 calendar
days**, an explicit research assumption, configurable in screens/backtests/paper.
This establishes young-listing eligibility, not proof that a base is its first.
The first downloaded candle is never treated as a listing date.

Provide independently checked listing evidence in the installation-specific
`data/metadata/listings.json` (or the configured data directory), keyed by ISIN:

```json
{
  "<ISIN>": {
    "listing_date": "YYYY-MM-DD",
    "source": "<official listing notice URL>",
    "verified": true
  }
}
```

Four issuer-sourced listing dates (RAINBOW, KFINTECH, HOMEFIRST and ANGELONE) are now bundled in reference_data/history_evidence.json. Other dates are not guessed. Missing evidence excludes a symbol
from new IPO backtests and prevents IPO entries in paper; existing positions
continue through the ordinary exit engine unless the gap guard halts the cycle.
No eligible IPO inputs produces an actionable error. Verified evidence is frozen
into the first input candle of each new run, without modifying the provider cache.

## Breadth coverage

When `skip_weak_markets` is enabled, entries require at least
`market_min_coverage_pct` of the simulation universe to have a dated 200-session
average on the signal date. The default is **80%**. Zero eligible history fails
the gate. Exactly 200 observations are sufficient. Qualified breadth must then
meet `market_breadth_pct`; exits continue normally. Coverage is based on symbols
included in simulation after exclusions, not the entire exchange.

Historical reports remain unchanged and may reflect earlier rules. New reports
save the audit result and prominently state survivorship bias and unverified
adjustment status. Historical trade explanations are reconstructions and can
flag differences from current rules; they do not rewrite recorded fills.


## Evidence-backed histories and split/bonus contracts (5 October 2026)

Derived inputs exclude candles before the four verified listing dates. The cache
and old reports are unchanged. PRIVISCL is quarantined entirely pending a sourced
history reconstruction. Research excludes it visibly; paper halts if it is held.
The UI audit distinguishes raw-cache gaps, applied history policies and unresolved
gaps in derived inputs. Quarantine can reduce universe breadth; exclusions remain
part of each report's disclosed assumptions.

The NSE 4 January 2024 Nestle bhavcopy has close ₹27,116.40 and volume 132,390.
The cached close is ₹1,355.80 and volume 2,647,800: approximately 20 times price
adjustment and exactly 20 times volume adjustment, consistent with the 2024 split
and 2025 bonus. Source:
https://nsearchives.nseindia.com/content/historical/EQUITIES/2024/JAN/cm04JAN2024bhav.csv.zip
This is a verified sample, not a provider-wide adjustment guarantee. The read-only
provider corporate-action probe returned HTTP 403; no authenticated event calendar
was obtained. Reliance's requested legacy bhavcopy URL returned 404.

The engine now supports explicit verified split/bonus contracts in the private
installation data at metadata/corporate_actions.json, keyed by current ISIN:

```json
{
  "<ISIN>": [{
    "id": "<unique action id>", "kind": "split",
    "ex_date": "YYYY-MM-DD", "share_factor": 2,
    "price_basis": "raw", "volume_basis": "raw",
    "verified": true, "source": "<issuer/exchange action notice>",
    "basis_source": "<independent raw-versus-provider OHLCV comparison>"
  }]
}
```

The share factor is new shares per old share (a 1:1 bonus uses 2). Validate the
ex-date, not just record/allotment dates. No live adjustment contracts are seeded:
unknown raw/adjusted basis is not guessed. Mixed price/volume bases, duplicate
same-date contracts, fractional share entitlements, dividends, rights and
mergers/demergers are unsupported and must halt for review. Use already_adjusted
for BOTH basis fields only after independently checking that the provider already
adjusted the series. Such a contract leaves it unchanged.

For raw contracts, indicator context adjusts previous OHLC and volume only for
actions effective by that signal/session. Future actions cannot alter past signals.
Raw execution prices remain intact. Held quantity multiplies and entry/stop/best
prices divide by the verified factor before ex-date stop checks. Cash, aggregate
cost basis, fees and monetary initial risk remain unchanged. Action IDs are
checkpointed for idempotent restart. Original buy fills and initial quantities
remain recorded; closed trades add exit_quantity for the changed unit count.
Reconstructed chart stop traces are omitted when a trade crosses a share action.

Existing processed-provider revisions still halt paper via its fingerprint guard.
This does not automatically reconcile an already-adjusted provider rewriting old
bars while a physical paper position is open. That requires a separately verified
reconciliation; do not bypass the fingerprint. Backtest findings are audited on the
contract-normalized price view before simulation.

New runs and paper cycles record exact source-file hashes, dependency versions,
Git revision/dirty status when available, and input history evidence. Docker lacks
Git metadata but still records the exact source tree. Historical reports receive
no invented revision identity.

## Frozen-input audit, recovery and validation

Use a new output and replay directory for the full saved-input audit:

```powershell
.venv/Scripts/python.exe scripts/audit_data.py --frozen --replay-dir artifacts/new-replays --output artifacts/new-frozen-audit.json
```

Separate replays use current code and verified history policies; originals stay
unchanged. Unresolved gaps block reruns, and metric deltas cannot be attributed to
one repair alone. This can take minutes for large saved input collections.

A production backup was copied to this computer and restored into a separate
ignored artifacts/production-backups directory. All 512 files passed manifest/path
and content checksum validation; private credentials were excluded. Archive and
server SHA256 matched. This proves that backup's restore path, not an automatic
ongoing off-server backup schedule. Live production storage was not replaced.

The fixed candidate, data gate, future holdout and decision log are recorded in
[VALIDATION_PLAN.md](VALIDATION_PLAN.md). Historical membership and unresolved
corporate actions keep the edge-validation gate closed.


## Official NSE listing import

The official NSE EQUITY_L.csv provides a DATE OF LISTING column. The new
scripts/refresh_listing_evidence.py matches it by exact ISIN AND symbol and accepts
EQ/BE/BZ equity series. A conflicting prior date or duplicate ISIN stops import;
no candle dates or company-name guesses are used. The import stores source URL
and complete downloaded-master SHA256 with each verified date.

The current master matched **497/500** universe instruments in both environments.
BAGMANE, BIRET and EMBASSY were not matched by this equity master; their listing
eligibility remains unverified rather than invented. The bundled four issuer
records are a fallback, not the complete installed metadata. The master dates
establish NSE listing eligibility, not historical index membership or adjusted
prices. Re-import a new official master when changing the universe.

```powershell
.venv/Scripts/python.exe scripts/refresh_listing_evidence.py --data-dir data --report artifacts/new-listing-import.json
```

A downloaded official CSV can be supplied with --csv for reproducible import.
Dates and action metadata are frozen once per simulation/audit. New unheld listings
without sufficient history wait for warmup and do not block the whole paper cycle;
held symbols with insufficient context still halt. No history is fabricated.


**Exchange listing is not IPO age.** The NSE master can include secondary venue
listings (for example long-established Nestle or Force Motors). Dates from this
master limit unverified NSE-source history; they never automatically establish
IPO youth. IPO predicates additionally require ipo_verified=true, ipo_date and
ipo_source for the original public listing. The four issuer-sourced IPO records
carry that evidence; the remaining imported venue dates do not. A manual initial
IPO record can use the listing date as ipo_date only when that fact is verified.
Unknown initial IPO dates block IPO entries. This distinction can reduce the
eligible IPO universe even though venue-date coverage is 497/500.

The broad frozen-input audit found input issues in 110 of 112 reports. Applying
listing-history policies still left unresolved gaps, so those 110 corrected
replays remained blocked. The current derived cache has 10 unresolved gaps after
31 raw-cache findings. No original report was deleted or retroactively relabeled
as profitable/unprofitable. Remaining names: ABREL, COHANCE, HEGAM, IIFL, NMDC,
SIEMENS, TATACHEM, TATACOMM, TMPV and VEDL. These require event-specific evidence,
especially demergers; a split/bonus factor is not a substitute.

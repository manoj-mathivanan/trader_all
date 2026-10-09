# Base-and-pivot research — 8 October 2026

Neither experimental variant passes the frozen research-candidate rule. Keep the
existing paper portfolio; do not promote either variant based on these results.
Owner decision: retired on 8 October 2026. The experimental UI option and runtime
support were removed after the failed comparison. It was never deployed. Completed
results, frozen inputs and replay code remain archived locally.

## Matched results after modeled costs

Historical = 1 January 2020–31 December 2025. Recent 2026 = 1 January–1 October 2026.
Each window starts independently with cash and ends with liquidation; returns
across windows must not be added. Every run uses the identical frozen 347-stock
input snapshot and trading assumptions. These are net hypothetical returns, not
production portfolio performance or reference-site backtest results.

| Window | Variant | Net return | Max drawdown | Trades | Win rate | Profit factor | Run ID |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| historical | blue_sky | +25.44% | 27.65% | 330 | 42.73% | 1.14 | `7fc90f9e42c2` |
| historical | base_pivot | +24.60% | 31.66% | 242 | 45.45% | 1.19 | `a424d263580b` |
| historical | base_pivot_rs70 | +25.04% | 22.93% | 288 | 43.06% | 1.15 | `1a3a958d1f8b` |
| recent_2026 | blue_sky | -9.57% | 9.66% | 44 | 31.82% | 0.60 | `fedc63d0a1ee` |
| recent_2026 | base_pivot | -15.49% | 15.49% | 42 | 26.19% | 0.34 | `a6647e40707c` |
| recent_2026 | base_pivot_rs70 | -18.09% | 18.09% | 41 | 21.95% | 0.26 | `e3bb534623d6` |

## Decision and learnings

The predeclared gate requires positive return and greater return than Blue sky in
both windows, with drawdown no greater than 20% in each. It is a research heuristic,
not an owner-approved live risk limit. Both variants fail: neither beats baseline
in either window; both lose in 2026 and exceed 20% historical drawdown.

- A closing-pivot base detector does not automatically improve returns. The
  historical unfiltered variant has fewer trades and a higher win rate, but lower
  net return and deeper drawdown. Entry timing and subsequent cash/slot paths matter.
- RS70 reduces historical drawdown relative to the unfiltered base variant, yet
  produces the largest 2026 loss. One useful historical statistic does not establish
  robustness. RS filtering can alter later account paths, so filtered trades are not
  necessarily a simple subset of the unfiltered trade ledger.
- The current baseline also loses in 2026 and has 27.65% historical drawdown. Keeping
  it as the comparison baseline is not a profitability endorsement.
- These findings evaluate our defined approximation, not Banana Patterns' actual
  engine. Differences in its stock list never proved superior returns.
- No parameters were retuned after observing these six results. Neither variant
  warrants replacing the baseline or starting an automatically promoted paper account.
  A future revised hypothesis must be defined before testing and ultimately collect
  an untouched forward record.

## Frozen hypotheses and shared account assumptions

Baseline: the current custom Blue sky settings, with Skip weak markets off.
Capital 100,000; next-session open swing entries; 1% risk; 8% stop; +25% winner exit;
1R breakeven; 8% fallback trail; five positions; 120-session holding limit; buy cost
35 bps, sell cost 50 bps and slippage 10 bps per side. Candidate priority remains
alphabetical. SMA50; prior-50-session mean turnover >=50,000,000; volume >=1x the
prior-50-session mean; long-trend flags off; Blue sky history cap 5,000 sessions.
All three use 260-session pre-start warmup. The frozen baseline configuration in
study_plan is authoritative for every parameter.

Base-and-pivot uses a closing-history high instead of an intraday-history high and
adds base identity: choose the most recent prior bar touching the maximum prior
close within the history cap. Require 15–120 sessions since that touch, prior-base
low no more than 35% below the closing pivot, signal close strictly above the pivot,
and the unchanged trend/liquidity/volume checks. The signal bar is excluded from
base construction. Equal touches restart base age; a new closing high resets the
next base, avoiding a new base signal on every consecutive high.

The third variant changes only min_rs_rating to70. This uses our existing local
126-session cross-sectional price-return percentile, not Banana's proprietary RS.
No ATR contraction or volume-dry-up requirement was added or claimed. This detector
is a testable hypothesis, not an exact reproduction of Banana Patterns.

## Data and validation limits

The source was local cached data, prepared through current listing/corporate-action
contracts. Of 500 current constituents, 144 were excluded by the common history or
quarantine checks. Nine more had unresolved audited gaps and were explicitly
excluded from every variant: ABREL, HEGAM, IIFL, NMDC, SIEMENS, TATACHEM, TATACOMM,
TMPV and VEDL. No audit check was disabled, no prices were repaired for this study,
and excluded names were not accepted as clean data. Full-universe runs remain
blocked until these data issues are resolved through evidence.

The fixed restricted cohort is a retrospective diagnostic: exclusions use today's
available history, including information later than the earlier test dates.
Current membership, history exclusions and provider adjustment limitations create
selection/survivorship bias. Results cannot be generalized to all Nifty 500 stocks.
Both periods had already been examined in earlier research; neither is an untouched
holdout. Shared freezes isolate algorithm differences but do not remove these biases.

The normal simulation omits actual liquidity participation, circuit locks, broker
non-fills and some historical corporate-action/membership uncertainties. Assumed
costs are not a verified historical brokerage/tax schedule.

## Reproduction and saved artifacts

Study output: `artifacts/base-pivot-study-20261008/` (ignored private research artifacts).
`code/` preserves the engine source used for these runs. `data/study_plan.json`
contains settings, exact configs, source hashes, cohort, manifests and gap findings.
`data/study_results.json` contains all six result summaries. `data/runs/<id>.json`
contains full reports/trades/curves; `data/run_data/<id>.json` contains frozen inputs.
No source Settings, jobs, runs index, prices or paper ledger were changed.

Input SHA256: `52dc9cc0075a849ae7a4f2c9c0ba878d0e183239561b6d1278390010739d2bbe`.
Plan SHA256: `112302b0e3c6f2c1fcfe1a18454e630b9ba4c5e90478292649d88eba548ba8fd`.
Every completed worker asserted input-hash equality. Run each replay with the frozen
code and configuration; normal BacktestConfig comparison_run_id references the
frozen run_data. Do not overwrite old reports or silently refresh their inputs.

To create a new study with explicitly documented gap exclusions:

```powershell
.venv/Scripts/python.exe artifacts/base-pivot-study-20261008/code/scripts/compare_base_pivot.py --source-data data --baseline-config artifacts/base-pivot-study-20261008/baseline.json --output artifacts/new-base-pivot-study --exclude-unreviewed-gaps
```

The baseline JSON must use Blue sky, swing holding, next_open entries and cover the
study windows (2020 start through a 2026 end). Without the explicit exclusion flag,
unresolved gaps halt the run. The output data path must be separate from source data.
Use a fresh output directory and freeze a copy of code before execution.

The UI option, BacktestConfig additions, signal/engine/chart branches and active
comparison CLI have been removed. Current application schemas reject this pattern;
the paper portfolio continues to use its existing Blue sky rule. Archived reports
must be viewed or replayed with the preserved study code, not imported into the
current dashboard. The final removed module/CLI/test files are additionally saved
under `retired-source/` inside the study artifact directory.

At implementation verification, 177 Python tests and frontend checks passed.
The isolated study verified identical input, plan and frozen source hashes for all
six reports. Feature-specific tests are archived with the retired implementation;
application regression checks are rerun after removing it.

Removal verification: all 171 remaining Python tests and frontend checks/tests passed.
The current schema rejects base_pivot and omits base_pivot_max_days. All six saved
reports and frozen input snapshots, plus archived replay source, remain present.

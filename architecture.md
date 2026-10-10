# Trader — architecture, implementation contracts and research record

Reconciled against the local checkout on **9 October 2026 (IST)**. Includes source changes already present, whether committed or not. Dated deployment observations and research results are historical evidence, not a claim that the live server was inspected today.

## Documentation policy

Keep only README.md and architecture.md as project Markdown documentation. README covers setup and operation; architecture holds detailed contracts, schemas, research results, sources and deployment instructions. Do not create or update documentation during routine coding, testing, research or deployment unless the user explicitly asks. Research scripts export Markdown only with an explicit --markdown path. Saved JSON reports/charts remain runtime artifacts. Read only relevant architecture sections for routine work.

Current source, runtime schemas, dependency locks and deployment files define behavior. Dated experiments describe frozen historical snapshots, not current defaults. Local/uncommitted changes do not prove deployment. Proposed restructuring is not implemented by this cleanup or standing authorization to deploy/trade/modify user data.

## Current implementation

| Area | Current behavior |
|---|---|
| UI | Plain FastAPI-served HTML/CSS/JavaScript; KLineChart 9.8.12; no frontend framework/build server |
| Navigation | Overview, Market data, Fundamentals, Backtests, Momentum, Scalping, production Paper trading, Jobs & logs, Settings |
| Data | Current official Nifty 50/500/Total Market membership, exact ISIN provider matching; Upstox daily/five-minute/one-minute caches |
| Rolling refresh | Daily last-calendar-year and five-minute last-ten-calendar-day history for all 750 Total Market stocks, retaining older data; official quarterly fundamentals follows |
| Swing | VCP, Blue sky, Multi-year and verified IPO screens; bullish/bearish daily/intraday research; saved screens and validated strategy presets |
| Momentum | Opening-range research, confirmation/indicator timeframes, fixed refinements/indicator/flag/reversal suites and historical fundamental gates; no paper module |
| Scalping | One-minute pullback research and separate forward streamed-quote paper locally and in production |
| Company | Direct NSE filing metrics/scoring, bulk quarterly cache, prospective buy screens, dated historical ranking and optional cited LLM reviews |
| Worker | One in-process ThreadPoolExecutor research job at a time; interrupted jobs fail on restart |
| Application storage | Independent per-environment atomic JSON files; paper accounting/checkpoint commit together; research artifacts span files |
| PostgreSQL | Independent PostgreSQL 17 market-data layer; completed local/production refreshes sync automatically; Trader readers/state still use JSON |
| Execution | Simulated only: Swing EOD next-open, Scalping observed fresh bid/ask. No live broker orders |
| Portfolio | Exactly one per implemented strategy, independent fixed capital/captured membership and durable history; no auto-create/pooling/reset |
| Runtime | Python 3.13, Node 22 for checks/vendor; one dashboard process per environment; optional separate Scalping quote process with cross-process locks |
| Hosting | DigitalOcean/Caddy/Docker Compose configuration with durable mounts; host/write-origin checks and optional Basic Auth |
| Validation | No validated edge; membership/actions/accounting/executable shorts/fills and data-basis limitations remain disclosed |

TRADER_ENV defaults to local. Generic Swing paper routes and its weekday scheduler are production-only. Scalping uses separate /api/scalping/paper routes and operates locally too. Installing does not create a portfolio, schedule or runner.

PostgreSQL runs independently under /opt/market-data with durable /srv/market-data/postgres state; Trader production JSON remains under /srv/trader/data. Importing market evidence does not synchronize credentials, paper, settings, jobs or report outputs. Database provisioning/import source is present; dated deployment records must not be read as today's verification.

## Module ownership

| Path | Responsibility |
|---|---|
| dashboard/api/main.py | Lifecycle/security, bootstrap and settings/data/jobs/backtest/paper APIs |
| dashboard/api/company_review.py | Company evidence, filings, buy screens, scans/reviews |
| dashboard/web/app.js | Navigation/state, templates/forms/charts/reports/events/polling |
| dashboard/web/company-review.js | Company feature currently sharing app.js globals |
| dashboard/web/style.css, index.html | Theme, responsive/accessibility shell |
| core/research/config.py, strategy_presets.py | Validated models and screen/strategy presets |
| core/research/upstox.py, market_data.py, intraday_data.py | Provider matching, rolling/history fetch and cache validation |
| core/research/backtest.py, short_backtest.py, intraday_long.py, intraday_short.py | Swing preparation, simulations and saved reports |
| core/research/momentum.py, momentum_indicators.py, scalping.py | Strategy config/engines and frozen suites |
| core/research/fundamentals.py, fundamental_history.py, official_filings.py, company_review.py | Direct evidence/scoring, publication-time archives and advisory web research |
| core/research/market_history.py, data_quality.py, corporate_actions.py, candle_repairs.py | Listing/quarantine/audit, verified actions and derived exact-row repairs |
| core/research/store.py, jobs.py, provenance.py | Atomic JSON, jobs/logs and source/input hashes |
| core/research/trade_chart.py, short_trade_chart.py | Frozen charts/explanations |
| core/strategies/registry.py, strategies/swing_patterns/patterns/ | Strategy identity and daily pattern predicates/registry |
| core/risk/, core/execution/ | Shared sizing and simulated fill/cost code |
| core/portfolio/ | Independent ledgers, dispatch, scheduler; separate Scalping runner/control/process locks |
| core/market_data/ | Upstox V3 full-feed transport and protobuf |
| scripts/, reference_data/ | Explicit utilities and public sourced history/repair evidence |
| deploy/, Dockerfile, compose.yaml | Hosting/backups/restore and independent PostgreSQL provision/import |
| tests/ | Isolated synthetic/temp fixtures and JavaScript checks, no shipped fake prices |

## Reading map

- [UI/Swing implementation](#ui-and-swing-implementation-contracts)
- [Strategy/portfolio contracts](#strategy-and-portfolio-contracts)
- [Rolling ingestion](#rolling-market-data-ingestion)
- [API/storage/recovery](#api-security-storage-and-recovery)
- [Exact current schemas](#exact-configuration-schemas-9-october-2026)
- [Frozen validation plan — registered 5 October 2026 (IST)](#validation-plan)
- [Intraday momentum: research and experiment review](#momentum-deep-research)
- [Fundamental ranking comparison](#fundamental-ranking-comparison)
- [Quarterly fundamentals cache and buy screens](#fundamentals-pull)
- [NSE intraday long and short strategy review](#nse-intraday-strategy-review)
- [Stronger momentum entries — 8 October 2026](#momentum-stronger-rules)
- [Reversed intraday momentum experiment](#momentum-reverse-research)
- [Intraday momentum baseline](#momentum-research)
- [Momentum indicator loop — declared 8 October 2026](#momentum-indicator-research)
- [Fundamentals before momentum entry](#momentum-fundamentals-research)
- [Scalping research](#scalping-research)
- [Trader MVP deployment](#deploy-readme)
- [Screen and backtest configuration guide](#screen-and-backtest-parameters)
- [Automatic company research](#company-research)
- [Base-and-pivot research — 8 October 2026](#base-pivot-research)
- [Banana Patterns versus our breakout signals](#banana-pattern-comparison)
- [Corporate-action history investigation — 7 October 2026](#corporate-action-review)
- [Shared market-data database](#deploy-market-data-readme)
- [Data-validity safeguards — first increment](#data-validity)
- [Upstox feed schema](#core-market-data-readme)
- [Intraday cost diagnosis](#intraday-cost-diagnosis)
- [Sector-filter implementation](#sector-filter-implementation)
- [Original Swing studies](#research-decisions-reproducible-configurations-and-results-from-the-original-swing-study)
- [Deployment/database operations](#deployment-and-database-operations)
- [Proposed restructuring/roadmap](#proposed-restructuring-and-future-scope-not-implemented)

## UI and Swing implementation contracts

The detailed Swing contracts originated in the earlier implementation and are retained with current corrections. Current schemas and the strategy-specific additions below cover later capabilities. Historical ingestion/performance counts are dated observations, not current server health.

### Complete visual specification and DOM shell

Use a plain HTML/CSS/JavaScript SPA, no framework or frontend build step. The page title is
`Trader — Swing control panel`; the brand is `trader.` with an upward-arrow mark and the subtitle
`A little more systematic.`. The header has brand, horizontal workspace menu, local-status dot,
theme toggle and an `M` personal-workspace avatar. The left rail contains strategies, saved
screens, **Add new screen**, the risk message **Protect first. Let the winners run.**, and a
research-workspace/version footer. Workspace navigation is not duplicated in the left rail.

| Design token | Light | Dark |
|---|---|---|
| Background | `#f7f8f3` | `#151a16` |
| Panel | `#ffffff` | `#1d251f` |
| Text | `#24382d` | `#e2eadf` |
| Muted text | `#7a857c` | `#9da99f` |
| Borders | `#e5e9e0` | `#334036` |
| Green/action color | `#24764e` | `#9ec99b` |
| Soft green surface | `#edf4e9` | `#2b382a` |
| Gold | `#a38538` | `#d0bd7c` |
| Loss/error | `#b95548` | `#ee9b90` |

Typography: DM Sans for body (14 px base), Manrope for headings/brand; use sans-serif fallbacks
if Google Fonts are unavailable. Desktop header is 83 px high, left rail 223 px wide, main
content offset 223 px with 38 px horizontal padding and maximum width 1800 px. Panels have
10 px corners, 1 px borders and a subtle shadow. Buttons have 7 px corners. Heading is about
32 px. Four summary cards form a row; two-column forms use 18 px gaps. Dialog width is
`min(1000px,94vw)`, maximum height 88 vh, with sticky heading and scrollable body. Tables scroll
horizontally. At 1050 px collapse main content columns and reduce rail to 190 px; at 720 px use
two summary columns, one form column, horizontally scrolling top navigation and compact header;
hide strategy/saved-screen lists but retain Add new screen. Honor reduced-motion preferences.

Required IDs: `top-navigation`, `strategies`, `saved-screens`, `theme-toggle`, `content`, `view`,
`modal`, `modal-content`, `toast`. The modal is native `<dialog>`. Toast uses `role=status` and
`aria-live=polite`; it disappears after 5.5 seconds. Include a skip link and visible focus rings.
Theme starts light, is stored under `trader-theme` in localStorage, and tolerates storage errors.
Format currency with `en-IN` and ₹; format times in Asia/Kolkata and append IST. Escape user
strings inserted into HTML. Field help is an accessible small `i` button with hover/focus tooltip;
on small screens tooltips appear near the screen bottom. Checkboxes span the form width.

The top content banner reads **RESEARCH & PAPER — Real market data. Simulated trades. No live
execution.** Footer states rules-based research, no investment advice and hypothetical backtests,
and links to the KLineChart Apache 2.0 license. Do not substitute demo data for loading/empty states.

### Views, actions and dialogs

Hash navigation: `#overview`, `#data`, `#company`, `#backtests`, `#momentum`, `#scalping`, `#paper`, `#jobs`, `#settings`; unknown hashes
return to overview. Closing/changing views disposes charts and closes the modal.

| View | Required content and behavior |
|---|---|
| Overview | Universe, loaded-symbol/bar coverage, run count, Research/Paper mode and simulated position count; latest run's return/trade count and full-report button; connection/data/backtest onboarding; methodology strip; three recent jobs |
| Market data | Refresh universe, Fetch prices & fundamentals, 750-stock rolling fetch status and selected research universe, actual coverage and bias warning; search symbol/company/sector; table of company/symbol, sector, last close/change, bars, first/last history and Chart button |
| Backtests | New backtest; newest-first run cards with name, universe, dates, IST creation time, return, drawdown, trades; open complete report; explanatory research text |
| Paper trading | Strategy portfolio selector; Create/configure portfolio; pause/resume new entries; Run daily cycle; status/universe/start/last session/schedule; equity/cash/realized/unrealized cards; open positions, equity curve, closed trades, fills and full JSON export |
| Jobs & logs | All returned jobs with type/time/status and View logs; pending-job link and manual Refresh; readable timestamped log in a modal |
| Settings | Research-universe form (automatic history windows); private plaintext-token connection form; token saved/replacement status; environment/authentication status; backtest configuration action |

Sidebar saved-screen buttons open New backtest seeded from that screen. Add new screen opens
name, Base screen and schema-defined qualification filters. New backtest groups fields into Experiment; Banana screen
filters; Entry, risk & exits; Execution costs; acknowledgment. Strategy currently displays Swing
Pattern. Screen choices: VCP, Blue sky, Multi-year breakouts, IPO base, then each saved name.
Risk, stop and position count are numeric inputs with schema bounds, not restricted choice lists.
Entry options are pivot, close and next_open in backtests; paper restricts entry to next_open.
The sidebar's **Explore the method** action opens a methodology dialog describing the screen
families, percent-risk sizing, initial protection, breakeven and winner exits, and the data/cost
limitations. It is explanatory content, not a settings mutation or a strategy switch.

Backtest date-picker limits (5 October 2026): both New backtest
start/end inputs set HTML `min` to the available-window response's `history_start` (fallback
`start`) and `max` to `end` (fallback `history_end`). This prevents choosing dates outside
downloaded coverage in the calendar. The warmup-adjusted safe start remains a recommendation,
not the minimum date. With no history boundaries, disable the date inputs. Market data settings expose only the research universe; rolling fetch windows are automatic. Preserve cloned report
dates, but block invalid values through native input validation and `validateBacktestDates`
before submission; reject either date outside the bounds and start after end. Regression tests
cover both limits, inclusive endpoints, reversed ranges and no-history disabled fields.

Report shows return, drawdown, expectancy R, win rate, equity curve, fees, slippage, profit factor,
skipped entries, expandable warnings/exclusions/full configuration, and the complete trade ledger.
Trade headers sort symbol, entry date, quantity, P&L, R or exit reason; clicking again reverses.
Initial order is newest exit first. Entry-date cells show both entry and exit. Sorting only affects
presentation. Adjust & rerun preserves every explicit historical parameter and changes the name
to `<original> · revised`; acknowledgment resets. Export preserves the saved report as JSON.

Clicking a stock name in a backtest trade row opens a **Trade chart** dialog for that specific
stock within the selected backtest, with every recorded buy/sell shown as numbered pairs.
The clicked row selects the indicator/signal explanation; a stock-only ledger below the chart
lets the user select another trade for its setup. Short entries/covers retain their proper sides.
Sorting must retain the original trade-array index, including repeated trades in
the same stock. The dialog displays daily candles plus volume, locked green BUY and red SELL
markers at the saved entry/exit dates and execution prices (including modeled slippage), and
buy/sell date/price, quantity, net P&L and exit reason summaries. A **Back to report** button
returns to the same run and preserves the current sort. The chart is 450 px tall on desktop,
360 px on mobile; the summary uses three desktop columns and two on mobile.

`GET /api/runs/{run_id}/trades/{trade_index}/chart` validates the saved run and zero-based
ledger index, reads candles exclusively from `run_data/{run_id}.json`, and returns run_id,
trade_index, symbol, selected trade, all same-symbol trades (with original trade_index), bars and source=`frozen_backtest_snapshot`. Include up to 60 sessions
before the earliest stock entry and 20 after its latest exit, retaining every intervening candle and clipping to the
backtest end. Reject missing snapshots or entry/exit dates with an actionable 404; never fall
back to today's cache. Bind markers to the matching saved candle timestamps and trade prices.
Fit the initial viewport to the trade/context interval, allow normal pan/zoom and resize, and
dispose overlays with the chart. Same-day buys/sells retain distinct labels. Daily candles
cannot locate the intraday execution time. Cancel stale chart responses when leaving the dialog.
Verify frozen-input selection, invalid indices/missing snapshots, sorting/repeated symbols,
marker anchoring and back navigation. Regression files: tests/test_trade_chart.py and
tests/test_trade_chart.cjs; the latter runs through `npm.cmd test` with the screen-preset tests.

The trade chart also explains the decision using `core/research/trade_chart.py::explain_trade`.
Its API response adds `explanation` (series descriptors, signal date/timestamp/price, checks,
notices, pattern, entry mode, candidate priority and winner-exit rule). Each candle adds a
`chart_values` dictionary keyed by series id. Calculate all values against the full frozen
history before cropping, without modifying the snapshot. Missing warmup values are omitted.
Show distinct configured trend SMA, SMA 50 and SMA 200, plus SMA 150 for `trail_30w`.
Add the prior signal breakout high and base low (omit the base low for Blue sky), a separate
entry pivot when it differs from the signal trigger, initial stop, breakeven activation and
the +25% target only for `take_25`. Initial stop is entry × (1 − stop_pct/100), activation is
entry × (1 + stop_pct/100 × breakeven_r), target is entry × 1.25. Base/trigger/pivot levels
span the signal lookback through recorded exit; risk levels span entry through recorded exit.
All lines have checked, labelled color controls above the chart and can be toggled independently.
Render them through the price-series `TRADE_CONTEXT` KLineChart indicator on `candle_pane`;
its calc reads `chart_values`, and each figure supplies a styles callback. Toggle visibility
by overriding the indicator figures, retaining candles and recorded execution markers.

Add a blue SIGNAL marker at the completed signal session close, with a separate label offset
from BUY/SELL. The signal is the entry session for non-legacy `close` execution and the previous
session otherwise. Below the graph, **Why this trade qualified** shows the saved strategy,
signal date, entry rule, winner rule and priority, followed by actual values, requirements and
Passed/Failed/Context/Unavailable states. Reconstruct trend, breakout, prior-50-session volume
and turnover checks; enabled long/rising SMA 200 checks; VCP three-window price/volume
contraction and dryup; or base-depth checks for multi-year/IPO/legacy breakouts. Where relevant,
compute RS 126 percentile and enabled market breadth from the frozen universe on the signal
date alone. RS without a minimum is context, not a passed filter. Do not mix percent/volume
values with the chart's price axis; keep these in the condition table and volume pane.

The active-stop line is explicitly **Reconstructed active stop**, not a saved engine audit
trace. Start from the recorded entry stop; incorporate saved buy/sell costs and slippage in
breakeven; ratchet using the saved winner rule and completed closes. A stop updated at close
becomes active next session; pivot/close entries skip the entry-session stop update. If the
reconstruction reaches a stop earlier than the ledger exit, end the trace and display the
discrepancy date. Explain failed historical checks and older engine differences instead of
rewriting the ledger. VCP notices distinguish contraction trigger from execution pivot and
state that base-depth/market-cap filters are not enforced. Regression coverage in
`tests/test_trade_explanation.py` verifies full warmup, snapshot immutability, no future signal
leakage, next-session stop changes and close-entry timing. Browser verification must confirm
visible lines and toggles as well as the signal and execution labels.

Charts use vendored KLineChart 9.8.12, candlesticks plus VOL, Asia/Kolkata timezone, drag/pan,
scroll/zoom, ResizeObserver and disposal on modal changes. Daily chart is 365 px tall desktop,
310 px mobile. Equity is an SVG line/area chart with first/last date and equity labels.

Bootstrap once on load, then poll every 3 seconds without overlapping polls. Do not redraw an
open form/modal while polling; update visible job logs. Disable submissions while pending and
display request failures in the form. Background poll errors retain the last state; explicit
actions surface errors. Schema booleans use checkbox presence, numeric values use Number, all
other values use strings. `screen` and `strategy` are UI selectors, not extra BacktestConfig keys.

### Full screen-preset contract

All four built-ins currently share the following schema-defined filter seed; their pattern IDs choose
different predicates. These shared defaults do not mean the four signal rules are identical.

```json
{
  "base_days": 15, "max_depth_pct": 35, "volume_multiple": 1,
  "sma_days": 50, "require_long_trend": false,
  "require_rising_long_trend": false, "min_rs_rating": 0, "min_turnover": 50000000,
  "vcp_window_days": 10, "vcp_volume_multiple": 0.9,
  "blue_sky_lookback_days": 5000,
  "multiyear_base_days": 260, "multiyear_max_depth_pct": 50,
  "ipo_max_age_days": 730
}
```

IDs are `builtin:vcp`, `builtin:blue_sky`, `builtin:multiyear`, `builtin:ipo`; they are UI IDs only.
Saved screen stores name, one pattern ID, the schema-defined filters, created_at and an ID computed as
`custom_` + first ten hex characters of SHA1(name encoded as UTF-8). Saving the same name replaces
that preset; keep at most 100 newest presets. No delete/edit-specific screen API exists yet.
Saved strategy presets can additionally carry validated trading_defaults, minimum_warmup_sessions, source_run_id and description. Pattern/filter conflicts with trading_defaults are rejected. Bundled presets are merged with installation-specific saved screens; local saved values override the same identity. Selecting a saved screen copies its stored values. For older presets missing the three new
trend/RS filters, merge the built-in disabled defaults (false, false, 0); never leave stale
checkbox states. Set checkbox.checked for booleans, numeric input.value for numeric fields. New form merge order:
built-in/saved filters, then any explicit run seed (for cloning), then UI general defaults as
fallbacks. Always set the visible Screen selection to the chosen seed. There is no screen ID in
the saved run configuration; the resolved pattern, boolean and numeric values are the reproducible snapshot.

New backtest defaults outside filters: name `Breakout experiment`, capital ₹10,00,000, pivot,
1.5% risk, 8% stop, trail_50d, weak-market off, breakeven_r 1, trail_pct 8, five positions,
120 holding sessions, fundamental_score ranking for new long UI forms (alphabetical for legacy API/bearish), minimum_warmup_sessions 50, market_breadth_pct 40,
**10 bps slippage and zero buy/sell fees**, acknowledgment unchecked.
Zero slippage must be entered explicitly for a wholly before-cost reference comparison.
New paper capital must be entered by the owner; it has no UI default. Paper fees and slippage
default to 10 bps each and must be strictly positive. Existing portfolio settings are preserved
on open; choosing a screen replaces only filters and the hidden pattern.

### Exact local signal predicates and differences from the reference

Bars are chronological. At index i, “prior” slices exclude the signal bar; SMA includes its close.
Every family requires i ≥ max(sma_days,50), close strictly above that SMA, and the mean of prior
50 close×volume values ≥ min_turnover. Volume confirmation compares the signal-bar volume with
the prior 50-session mean times volume_multiple. This is mean turnover, not median turnover.

- **VCP:** require i ≥ max(3×vcp_window_days,sma_days,50). Use three consecutive prior windows of
  vcp_window_days; each range is (maximum high−minimum low)/maximum high. Ranges and average
  volumes must strictly decrease from oldest to newest; newest volume ≤ prior 50-day mean ×
  vcp_volume_multiple. Signal close exceeds the newest window's high and meets volume confirmation.
  `base_days` changes its execution pivot, not the contraction windows; `max_depth_pct` currently
  does not constrain VCP qualification. No explicit 0.9 tightening ratio, market-cap filter,
  52-week-high proximity or independently measured base age is implemented. Optional 200-day
  trend and local historical-price RS filters are implemented as specified below; neither is
  verified parity with the reference site.
- **Blue sky:** prior high over min(blue_sky_lookback_days,i) loaded sessions; close strictly
  exceeds it and confirms volume. “All-time” is only within available loaded/capped history.
- **Multi-year:** require i ≥ max(multiyear_base_days,sma_days,50); prior range of that length
  has depth ≤ multiyear_max_depth_pct, close above prior high and volume confirmation.
  Optional local 126-session RS is available; independently measured 52-week formation stage
  and verified proprietary-reference historical RS remain unavailable.
- **IPO base:** require i ≥ max(base_days,sma_days,50), prior base depth ≤ max_depth_pct,
  close above its prior high and SMA, with volume confirmation. Actual listing age and “first
  base” identification are not enforced; loaded history start is not proven listing date.
- **Legacy breakout:** same base depth/high/volume and trend checks as the IPO approximation;
  retained to read old experiments, hidden from new screen selections.

Optional trend predicates are common to every family: either require_long_trend or
require_rising_long_trend requires signal close strictly above inclusive SMA200; rising also
requires that SMA strictly greater than SMA200 evaluated 20 sessions earlier. The predicate
uses i>=199/219 respectively; preparation conservatively requires 200/220 pre-start sessions.
Both flags default false. False require_long_trend with true rising still enforces both tests.

Local historical RS is evaluated by the simulator, after the family signal: for symbols with
a candle on the completed signal date and index>=126, price return = close[i]/close[i-126]−1.
Sort all eligible returns ascending; zero-based tied rank is (bisect_left+bisect_right−1)/2;
percentile = rank/max(N−1,1)×100. One member gets zero. min_rs_rating=0 disables filtering;
otherwise missing score defaults below threshold and is skipped. candidate_rank=rs_126 sorts
entry candidates by descending percentile, descending return, then symbol. Use the completed
signal date (prior bar for next_open/pivot, current completed bar for close), never entry-day
close to prioritize an open fill. Default alphabetical preserves prior behavior. Members are
the run's eligible datasets; this is price-only RS without dividends or a benchmark subtraction.
Cache scores and indexed date lookups per signal date; do not scan future prefixes.

Safe-window backend warmup: VCP max(3×window,SMA,50); Blue sky max(SMA,50); Multi-year
max(multiyear_base_days,SMA,50); IPO/legacy max(base_days,SMA,50). For each symbol the suggested
first entry is bars[warmup+1]; take the latest such first entry and earliest final bar for the
common interval. History loaded instead shows the earliest/latest bars across all loaded symbols.
Preparation rejects missing/out-of-request-boundary data and excludes symbols without sufficient
pre-start bars, recording exclusions and content hashes. Add optional warmup floor 126 if RS
filter/ranking is enabled, 200 for long trend or 220 for rising trend, then take the maximum with
BacktestConfig.minimum_warmup_sessions (50–2500, default50). The minimum comparison warmup is
backtest-only; PaperConfig inherits TradingConfig, not this field. Never include warmup sessions in returns.

Initial UI coverage request uses max(base_days,SMA,minimum_warmup_sessions,RS126 if enabled,
trend200/rising220 if enabled,multiyear_base_days for that selected family,50). GET
/api/backtest/window accepts warmup50–2500. The banner is not automatically recomputed after
every form/dropdown change and the initial expression does not explicitly include 3×VCP window;
backend required_warmup/prepare remain authoritative. Preserve explicit user dates; do not
silently force the suggested common safe window on runs that deliberately exclude recent listings.

### Exact simulation, costs, exits and metrics

One no-leverage cash pool per run/portfolio. Process session dates ascending and symbols
alphabetically by default (or completed-signal RS priority when configured). Open-time gap/time exits occur first, then entries, then low-based exits and
close-based stop updates; intraday exit proceeds cannot fund earlier buys. Do not reenter a
symbol exited at the open that day. Size all candidates using that session's equity_at_open,
but decrement cash after each purchase. No separate per-position capital cap exists.

For pivot/next_open entries, test the previous completed symbol bar; for non-legacy close
entries, test the current completed bar. Pivot is the prior high before the signal bar over
base_days (VCP/IPO), min(blue_sky_lookback_days,signal index) (Blue sky), or multiyear_base_days
(Multi-year). Raw pivot fill = max(entry-day open,pivot). **Reject the entry if its day's high
is below that raw fill.** No pending pivot order carries into later days. Next_open uses open;
close uses signal close. Do not treat pivot−open as extra slippage.

For non-legacy pivot and close entries, do not apply that day's low, age increment or stop update
to the new position. Mark it at close; activate protection next session. Liquidate at the final
test close even if entry occurred that day. This daily-bar convention avoids retroactive stops
but omits possible valid same-day stops; intraday validation remains future work. Next_open and
legacy entries can use that day's low because their entry is at the open.

Let s=slippage_bps/10000, b=buy_cost_bps/10000, e=sell_cost_bps/10000. Buy fill = raw×(1+s),
sell fill = raw×(1−s); fee = filled price×quantity×side's fee rate; slippage metric sums
abs(fill−raw)×quantity. Initial stop = buy fill×(1−stop_pct/100). Unit sizing risk =
fill−stop + fill×b + stop×(e+s). Quantity = max(0,min(floor(equity×risk_pct/100/unit risk),
floor(cash/(fill×(1+b))))). Skip quantity <1 and full position slots. R uses quantity×(fill−stop),
so costs may produce losses worse than −1 R. Gaps can exceed initial risk.

Stop: if next open ≤ active stop, sell at that open; otherwise if session low ≤ stop, sell at stop.
Time exit: when stored age ≥ max_hold_days, exit at open. Increment age in the surviving bar phase.
Winner management activates when current close ≥ entry×(1+stop_pct/100×breakeven_r). Cost-adjusted
breakeven = entry_cost/quantity/((1−e)×(1−s)). trail_50d uses inclusive 50-close SMA; trail_30w
uses 150 daily closes (an approximation, not weekly aggregation). Raise stop to max(old stop,
breakeven,chosen SMA), effective next session. take_25 sells at current close once close ≥ 1.25×entry;
before that target, the current fallback raises stop to max(old stop,breakeven,best_close×(1−trail_pct/100)).
Legacy breakout also uses that percentage fallback. An unavailable selected SMA uses the fallback.
The selected SMA is only reevaluated while close meets the breakeven threshold, not unconditionally.

Weak-market gate uses the signal date: among symbols with ≥200 prior bars and a bar that day,
at least market_breadth_pct (default40%, allowed0–100%) must be strictly above their inclusive
200-close SMA. It runs only when skip_weak_markets=true; cache by signal date with indexed lookup. If none are eligible, permit entries.
Positions continue normal exits when the gate blocks new buys.

Trade P&L = sell proceeds−sell fees−entry_cost. Final equity = cash+marked positions; backtests
liquidate at each symbol's last close inside the interval, paper preserves positions. Return =
(final/initial−1)×100. Drawdown is largest percentage fall from the running equity peak, seeded
by capital. Win rate uses strictly positive trades / all trades. Expectancy is mean trade R.
Profit factor = summed positive P&L / absolute summed negative P&L. skipped_entries counts
RS/breadth rejection, position/cash limits and invalid/unreached pivot opportunities, not only
cash/position limits; the current UI cash/position label is narrower than the engine counter. No-trade win rate/expectancy
are null; no-loss profit factor is null. Equity curve rounds currency to two decimals; metrics
use its final rounded equity. Flat trades count in trade_count but neither wins nor losses.

### Persistent paper portfolio and scheduling

This section applies to production only. Local mode hides paper navigation, rejects all paper API routes and never starts or recovers the paper scheduler. Shared simulation/portfolio modules remain in the codebase for reuse and isolated tests.

Only Swing currently registers a paper plugin. Manager is strategy-ID based; future strategies
must register a distinct config model and cycle runner, get their own portfolio/cash/history,
and never reuse Swing's ledger. Registry metadata alone does not enable trading.

Creation needs a refreshed universe and real bars for every member, plus acknowledged config
and explicit capital. Set mode paper, active status, broker_account_id null, percent_risk sizer,
start_session = tomorrow's IST calendar date, empty ledger/fingerprints/cycles, and an initial
config_history entry containing the acknowledged creation configuration and UTC timestamp.
Freeze universe membership and history start. Keep capital fixed after creation; reject duplicate
creation and updates while any job runs. Configuration history records each update. Existing
positions retain pattern/stop/breakeven/winner-exit/trail/holding settings captured at entry;
fee/slippage assumptions use the current cycle config. Changes must not reset positions or cash.

Universe expansion approved on 8 October 2026: support `niftytotalmarket` in Settings and the
schema-driven research UI, displayed as Nifty Total Market (750). Fetch the official current
list from `https://www.niftyindices.com/IndexConstituent/ind_niftytotalmarket_list.csv`; match by
ISIN against the Upstox NSE master with existing ambiguity/dummy/duplicate checks, and require
at least 700 tradeable constituents before replacing the snapshot. Existing minimums remain
45 for Nifty 50 and 450 for Nifty 500. Membership remains a current snapshot, not verified
historical membership.

`POST /api/jobs/universe-expansion` accepts a validated Settings payload with universe
`niftytotalmarket`, start and end. It requires the server's token and submits a normal tracked
job named Fetch additional Total Market candles. `upstox.ingest_expansion` requires the stored
Nifty 500 snapshot, refreshes Total Market, compares ISINs, and ingests only additional members.
Normal validation, atomic per-symbol saves, partial-failure reporting and retry cache reuse
apply. Do not rewrite the Nifty 500 snapshot/candles, settings or any paper portfolio during
this operation. Results contain symbols, bars, universe and total_members. Research selection
can be changed explicitly in Settings after the pull; standard refresh/ingestion/backtests
then use the selected universe. Existing paper cycles continue to use their frozen snapshot.
No broader-universe paper account or migration is implied by downloading these inputs.
The official list observed on this date contained 755 rows: 750 tradeable stocks plus five
temporary placeholders (DUMMYHEG, DUMMYINGL1, DUMMYINGL2, DUMMYINXGN, DUMMYTRVN).
Placeholder exclusion requires a DUMMY-prefixed symbol, DU-prefixed synthetic ISIN and a
company name beginning Dummy; numbered DU1/DU2 formats are included. Unmatched real ISINs
still fail. Initial expansion job `6f2d88fdcda5` stopped before snapshot save because the two
numbered placeholders were unrecognized. After this correction, retry `64b6e7a52d38`
matched 750 tradeable members and selected exactly 250 additional ISINs. The requested
history range was 2016-10-08 through 2026-10-08, within the research ten-year validation cap;
actual bars begin at the provider's available/listed boundary. The deployment comprised
`f2c0d09` and `e7031c6`, with 128 Python tests and frontend checks passing; both GitHub CI
runs passed. Production was backed up before the deployment.
Job `64b6e7a52d38` retained valid history for 249 additional symbols but failed SOUTHBANK:
the provider returned 2,502 rows for 2,474 unique sessions, including 28 conflicting pairs
from 2017-01-19 through 2017-05-29. Prices, volumes and timestamps differ, so do not deduplicate,
aggregate or choose one without independent evidence. The invalid response was never saved.
Recovery job `40c35221e01f` requests 2017-05-30 through 2026-10-07, reusing the other cached
stocks while fetching SOUTHBANK's valid later history. This is an explicit shorter-history
limitation for that stock, not repaired 2017 data or a verified listing date. Do not backfill
its conflicting earlier provider history without sourced reconciliation.
Recovery job `40c35221e01f` succeeded at 18:08 IST with all 250 additional stocks and
425,976 saved candles; all observed final bars were 2026-10-07. Verified all additional files
were nonempty and requested coverage reached that date. The paper portfolio and stored Nifty
500 snapshot remained byte-for-byte unchanged against the preservation checkpoint. Research
Settings were then explicitly saved as universe `niftytotalmarket`, start `2017-05-30`, end
`2026-10-07` to avoid requesting SOUTHBANK's conflicting earlier data. Existing longer cached
histories for other stocks remain intact. Website bootstrap reported 750 research members
and 500 frozen paper members, with AETHER/BHEL/STLTECH positions and last_session 2026-10-07.

Cycle ingests the frozen universe through today if IST time ≥16:00, otherwise yesterday.
Use the internal `PaperIngestionRange(Settings)` model for this request. It overrides the named
`dates` validator to require start < end without the research form's 3653-day duration limit;
universe/type/extra-field validation is inherited. A fixed portfolio history start must keep
working as the completed-session cutoff advances past ten years. Do not move that start forward,
truncate existing candles, reset the ledger or relax validation on the user-facing Settings model.
This corrects the production failure observed on 5 October 2026 for history_start 2016-10-01.
Paper calls `upstox.ingest(..., universe=frozen_snapshot, extend_history=False)`; research leaves
`extend_history=True`. Forward refresh validates existing records and fetches only the later
boundary. It never backfills before the first stored bar and preserves `requested_start` metadata.
Missing stored history fails with a recovery instruction rather than silently rebuilding it.
Invalid later candles still fail normal validation; do not remove bad rows or invent replacements.
The production retry exposed MAZDOCK's valid stored range beginning 2020-10-12 alongside eight
invalid zero-price provider rows from 2017-12 through 2018-07 returned by an earlier-boundary
request. Forward paper ingestion avoids that irrelevant older request; it does not repair those
provider rows or permit them in research. Existing ledger/input fingerprints remain authoritative.
Production verification on 5 October 2026: retry job `d76d640d8b2b` completed successfully with
`sessions=0` (portfolio first eligible session 2026-10-05; no new common completed session).
Portfolio identity, creation date, history start, configuration and ledger matched the pre-fix
backup. Both fixes are in shared source and were applied to production; no portfolio reset or
local data transfer was used. Regression checks passed in the production image and local suite.
Follow-up verification on 7 October 2026: the portfolio was already active with weekday automatic
cycles enabled at 16:15 IST. Scheduled job `243bf09cc307` processed session 2026-10-06 successfully
with zero orders. Manual verification job `43967c3da8be` also succeeded, returning sessions=0
because that checkpoint was current for the common available history. Identity, capital,
configuration and creation/history dates were preserved. The newer failed jobs were a research
history fetch (invalid older MAZDOCK candles) and a backtest (historical price discontinuities),
not new paper-cycle failures. No additional trading-code change or account reset was needed.
The UI must distinguish job types: zero fills/new sessions on a successful cycle do not mean
paper is disabled, and historical failed jobs remain visible after later successful retries.
Read-only signal diagnosis on 7 October 2026 confirmed why this portfolio had no fills: its saved
`skip_weak_markets=true` and `market_breadth_pct=60` blocked four otherwise qualifying Blue sky
signals. These are observed portfolio choices, not new schema defaults. For entry session
2026-10-05 (signal day 2026-10-01), STLTECH and WELSPUNLIV qualified; 187/489 breadth-eligible
members were above their 200-session SMA (38.24%). For entry session 2026-10-06 (signal day
2026-10-05), LGEINDIA and STLTECH qualified; 192/489 were above (39.26%). Both were below the
configured 60% threshold. History coverage was 489/499=98%, exceeding the configured 80% coverage
minimum, so coverage was not the blocker. Ledger skipped=4 and fills=0 matched this gate. The
diagnosis evaluated the deployed predicates with cycle configuration snapshots, listing-filtered
history and action-adjusted signal-date context; it did not edit settings or replay paper orders.
Owner setting change on 8 October 2026: set the production Swing paper portfolio's
`skip_weak_markets=false` through its validated PUT configuration API. The portfolio remains
active with automatic weekday cycles enabled. Preserve the stored breadth/coverage thresholds,
all other configuration, allocated capital, ledger, fingerprints and cycle history. With the
gate disabled those breadth thresholds do not block new entries; ordinary screen, sizing,
position-limit and execution checks still apply. The change is recorded in config_history and
applies to subsequent unprocessed sessions, without replaying earlier skipped entries. No cycle
was submitted merely by saving this setting, and global schema defaults were not changed.

Production incident on 8 October 2026: manual job `3e768f5a48a0` at 09:30 IST and scheduled
job `0ca65d3e4e05` at 16:15 IST both completed ingestion but halted with
`Derived candle repairs changed for processed history; paper cycle halted for reconciliation. Ledger unchanged.`
The sourced COHANCE corrections were unchanged; disabling `skip_weak_markets` invalidated the
previous reconciliation proof because its checkpoint digest includes current configuration.
The checkpoint still ended on 2026-10-06 with two processed sessions and no orders. Recovery
backed up the portfolio and reconciliation metadata on the server, then used
`scripts/reconcile_candle_repairs.py` against production inputs. Both single-session cycles
were replayed using their saved configuration/status, with original and corrected derived
inputs across 499 eligible symbols. Raw processed OHLCV fingerprints were checked first.
Original replay, corrected replay and saved ledger matched exactly, including every accounting
field. Only then was `metadata/paper_repair_reconciliations.json` renewed for the exact current
checkpoint and repair-policy digests. Portfolio cash, settings, orders and history were not
rewritten. Retry job `153beb223ad5` succeeded at 17:50 IST after renewal, processing one
session (2026-10-07, the common available completed boundary) and committing three simulated
buy fills: AETHER 6 shares, BHEL 24 shares and STLTECH 11 shares. These remain three open
positions. The checkpoint advanced from 2026-10-06 to 2026-10-07; identity, allocated capital,
configuration, creation/history/start dates were verified against the pre-retry backup.
The portfolio remains active with automatic weekday runs at 16:15 IST and
`skip_weak_markets=false`. October 8 was not processed because the common observed boundary
had not reached that date; do not fabricate a missing session or use future candles.

Reconciliation operation contract: `candle_repairs.checkpoint_identity` binds portfolio ID,
the SHA-256 of ledger/config/fingerprints/cycles/start_session/universe_snapshot, and the SHA-256
of the sourced repair policy. Accept only `result=identical_ledgers` with all identities matching.
Never copy an old digest onto a changed checkpoint or remove the reconciliation guard. The
current replay helper supports evidenced single-session cycles with unchanged capital and no
orders; it must reject broader or fill-bearing checkpoints pending a reconstruction that also
verifies order metadata. Before publishing proof, ensure there are no active jobs and recheck
that the portfolio has not changed during replay. A later committed cycle records current
history evidence, allowing normal subsequent cycles to compare against that evidence.

Universe discussion on 8 October 2026: widening membership does not resolve this failure.
Before the subsequent expansion request, Settings/API supported `nifty50` and `nifty500` only.
The owner then approved pulling additional research inputs; the implementation above adds
`niftytotalmarket`. The wider research universe is:
[Nifty Total Market](https://niftyindices.com/indices/equity/broad-based-indices/nifty-total-market),
750 constituents comprising Nifty 500 plus Nifty Microcap 250. Compare matched periods and
costs, liquidity, drawdowns and history coverage before considering paper adoption. Preserve
the existing portfolio's frozen membership and accounting; any broader-universe paper trial
requires explicitly designed separate portfolio support or a versioned migration, never a
silent universe refresh or reset.

Production diagnosis on 9 October 2026: scheduled job `900e34361eb5` started at 16:15 IST and
completed at 16:24 IST, processing session 2026-10-08 with zero fills and three retained positions.
Its saved fundamental_checks explicitly blocked CUPID and PTCIL with missing validated evidence
and 0% coverage. Read-only reconstruction found both technical predicates true on signal date
2026-10-07; the fundamental gate ran before sizing. Weak-market filtering remained disabled;
cash was INR 67,176.24 and 3/5 position slots were occupied. PTCIL also would size to zero under
the 1% risk budget (roughly INR 998 versus INR 2,200 modeled risk for one share). CUPID would
size to 32 shares if the fundamental gate allowed it. These are diagnostics, not executed orders.

After the owner pulled fundamentals, current production checks showed CUPID score 65/coverage
70% and PTCIL score 45/coverage 75%, both for financial period 2026-06-30. The saved buy screen
requires score >=60, coverage >=80% and period age <=180 days; neither candidate passes.
Snapshots were recorded on October 9 after the October 8 entry time, so point-in-time checks
for that entry still correctly report unavailable evidence. Earlier manual retry `0eebfd406b8f`
completed at 23:02 IST with sessions=0 and checkpoint 2026-10-08. Owner-authorized fresh retry
`319d7bedc40a` was then submitted to refresh/check forward availability. Do not reopen or reset
the processed checkpoint, backdate financial knowledge, lower thresholds or insert retroactive
orders merely to make a retry produce fills. Current data availability and completed checkpoints
must determine whether the next cycle has any new session to commit.
Owner change later on 9 October 2026: set the production Swing fundamental buy screen's
`min_coverage_pct` from 80 to 60 via `PUT /api/company/buy-screen/swing_patterns`.
Preserve `min_score=60` and `max_age_days=180`; these are stored screen values, not changed
schema defaults. The update was applied during retry `319d7bedc40a`'s candle refresh, before
the cycle reads the fundamental screen for new entry checks. Current-time API verification
then allowed CUPID (score 65, coverage 70%, no block reasons) and still blocked PTCIL solely
on score 45 below 60 (coverage 75% now passes). This does not change evidence availability
timestamps, reopen an already processed session or guarantee a future technical signal.
Retry `319d7bedc40a` completed successfully on October 9 at 23:35 IST with sessions=0:
the common available candle boundary remained 2026-10-08, already processed. No new orders
were produced and the portfolio checkpoint/accounting remained unchanged. The lowered
coverage requirement is persisted for subsequent entry decisions; CUPID's current-time
fundamental eligibility must not be treated as a retroactive fill instruction.

Require requested coverage for every symbol; hash prior processed OHLCV through last_session
and halt if any processed data changed. Use minimum observed final date across symbols as end,
max(start_session,last_session+one calendar day) as start; require per-symbol warmup. No new
sessions returns success with zero sessions. Run the shared simulator on copied ledger state,
liquidate=False, allow_entries only if active. Annotate new orders with portfolio_id, paper mode
and job_id; atomically commit ledger, metrics, hashes and cycle record. Failed cycles leave the
portfolio unchanged, although ingestion may already have updated bar files. Retries do not
duplicate committed sessions/orders. Paused portfolios still ingest and manage exits.

auto_run defaults false; hour 16–23, minute 0–59, default 16:15 IST. The single server scheduler
checks every 30 seconds on weekdays, only at/after configured time, and claims one scheduled
attempt per strategy/day. It waits while another job is active. A normal failed attempt is not
automatically retried that day; manual retry is available. Startup first marks interrupted jobs
failed, then releases missing/interrupted schedule claims. The production container must remain running; Docker restarts it after a process crash and Docker/Caddy start at boot. No exchange-holiday calendar or notifications are implemented. The systemd backup timer is separate from this in-process paper scheduler.

## Strategy and portfolio contracts

### Strategy plugin and restart contracts

There are two distinct registries. `core/strategies/registry.py` describes navigation and capability:

| ID | Display name | Status | Granularity | Trigger | Current engine |
|---|---|---|---|---|---|
| swing_patterns | Swing patterns | active | daily | batch | daily_breakout |
| intraday_momentum | Intraday momentum | active research | intraday_5m | batch | opening_range_momentum |
| scalping | Scalping | active research | intraday_1m | batch | scalping_pullback |

Each definition exposes id/name/description/status/granularity/trigger_mode/backtest_engine.
`core/portfolio/registry.py` maps implemented strategy IDs to `PaperPlugin(config_model, run_cycle)`.
Currently its only entry is `swing_patterns: PaperPlugin(PaperConfig, paper.cycle)`. Registering
navigation metadata alone never enables paper execution. Do not route momentum through Swing's
cycle or reuse Swing's file when its implementation is added.

Manager contracts: key(strategy_id) validates against the strategy registry and returns
`portfolios/<strategy_id>`; get returns the saved record or null; save accepts strategy_id,
validated config, data settings, create flag and IST clock; set_status accepts active/paused.
Create must fail if that strategy already has a portfolio. Updates reject a mismatched stored
id/strategy_name or changed config.capital. Status/configuration changes reject queued/running
jobs. The files are independent even when two strategies hold the same ISIN; shared market-data
files are cache infrastructure, not shared positions or cash.

Paper plugin runner signature is `run_cycle(log, job_id) -> result_dict`; the runner owns that
strategy's data/signal/simulation logic and calls the shared portfolio manager with its own ID.
Swing's cycle also accepts internal `ingest=False` for isolated tests; the HTTP API always ingests.
Future intraday/tick runners need their own session checkpoints and protective execution semantics,
not a renamed daily Swing runner. Keep shared risk/cost implementations where applicable.

The UI keeps a selectedPaperStrategy, initially swing_patterns, and resolves portfolio/schema from
bootstrap.paper_portfolios[ID] and bootstrap.paper_schemas[ID]. It lists registry entries in the
Paper trading selector; entries without an implemented paper schema are disabled and marked planned.
Generic create/update/status/cycle requests include the selected ID in their URL. Legacy singular
paper_schema/paper_portfolio and Swing routes remain compatibility aliases. A new implemented
plugin's primitive schema fields render without a custom frontend page. Swing alone receives the
Banana Screen/hidden-pattern special handling; do not show Banana presets for a momentum plugin.
The current generic input renderer supports strings, numeric types, dates, booleans, enums and
string constants; nested objects, arrays, nullable unions and custom intraday schedule forms require
additional renderer work. This is an extension seam, not a claim all future UIs already exist.

Scheduler checks every 30 seconds, iterating plugin IDs in sorted order. Each uses an independent
claim: Swing retains `paper_schedule.json`; other IDs use `paper_schedules/<ID>.json`. Queue jobs
with payload {portfolio_id: ID, strategy_id: ID, trigger: "schedule"}; save attempt_day (IST date),
at and job_id while holding the same process lock. A busy global worker delays other strategies;
the next tick continues them. There is one worker across strategies, independent money per strategy.

Startup always calls jobs.recover(). Production then calls scheduler.recover_interrupted() → scheduler.start() → serve HTTP. Local proceeds directly to HTTP without recovering/starting paper scheduling. Only production shutdown signals its scheduler Event and joins the daemon thread with a two-second bound.
No startup function calls portfolio create/save or overwrites capital/positions/history.
Recovery marks queued/running jobs failed with `Interrupted by server restart. Retry this job.`.
A schedule claim with no matching job or a failed interrupted job is released by setting its
attempt_day to null and recording recovered_at. Legacy Swing claims without job_id match portfolio
payload and creation date in IST. Ordinary provider failures and completed jobs retain their claims.
An enabled schedule retries interrupted work at/after its configured weekday time; a manually
started interrupted cycle remains available to retry manually (or via a later enabled schedule).

| Interruption point | Required continuation |
|---|---|
| Before any ledger commit | Reload the previous complete record; replay uncommitted sessions |
| During temporary-file write / before replace | Ignore leftover .tmp; read previous .json; retry overwrites .tmp |
| After portfolio replace, before job success update | Retain committed ledger; retry skips dates ≤ last_session, never duplicates fills |
| During partial provider ingestion | Preserve portfolio; retain valid bar-file updates; fix/retry ingestion before simulation |
| Process restart / configuration edit | Preserve id, creation date, first eligible session, cash, positions, trades, equity and cycles |
| Processed OHLCV revised | Halt cycle; investigate input change, never silently rewrite paper history |
| Missing legacy encryption key / private token | Restore the matching legacy key only for an old encrypted token, or reconnect in that environment; portfolio history remains independent and intact |
| Missing/corrupt portfolio file | Do not auto-create a replacement account; restore a backup/investigate data integrity |

Persistence means retaining the same data directory across server restarts. Atomic replacement and
file fsync protect against an interrupted process write; they do not promise recovery from disk loss
or every filesystem/power-loss scenario. A local process is restarted with start.ps1 after a crash. Production Docker Compose uses restart: unless-stopped and durable host-mounted data/private directories; Docker and Caddy are enabled at boot. No automatic portfolio reset/delete, cash deposit/withdrawal, mode transition,
or historical-revision override is exposed in the local UI/API.

Paper record contains id, strategy_name, mode, broker_account_id, sizer_type, status, created_at,
updated_at, start_session, universe, universe_snapshot, history_start, config, config_history,
ledger, fingerprints, cycles, and metrics after the first processed cycle. config.capital is the
local allocated-capital field; the future production model's capital_allocated is not a second local
cash balance. Initial ledger/fingerprints are empty objects; cycles/config_history are arrays,
with the creation config appended to config_history. Cash appears in ledger on first processing;
before that the UI displays config.capital. Fingerprints use SHA256 over chronological rows of
only date/open/high/low/close/volume through last_session, via json.dumps(rows, sort_keys=True).
Each cycle stores job_id/at/start/end/sessions/config/order_count/status. Config history entries
store at/config. Marked unrealized P&L is sum(quantity×last_close−entry_cost), before prospective
exit charges; realized P&L is the sum of closed-trade pnl. Both remain distinct in the UI.

### Function interfaces and response shapes

The rebuild must provide these contracts even if internal code is organized differently:

| Component | Callable contract |
|---|---|
| Persistence | read(name, default=None), write(name, JSON value), now(), save_token(value), token() |
| Data | match_constituents(rows, master) → instruments/exclusions; apply_verified_overrides(candles, isin) → provider-shaped rows; refresh_universe(settings, log), ingest(settings, log, universe=None, extend_history=True), fetch_range(client, instrument, token, start, end), validate_candles(rows, start, end), merge_candles(existing, additions) |
| Signals | matches(chronological_bars, signal_index, config) → bool; separate pure predicate per family |
| Research | required_warmup(config), available_window(settings, warmup), prepare(settings, config) → universe/datasets/manifest/exclusions, run(settings, config, log, job_id, fundamental_evidence=None, sector_evidence=None) → {run_id} |
| Simulation | simulate(datasets, config, *, state=None, liquidate=True, allow_entries=True, entry_warmup=0, entry_check=None, fundamental_scores=None, sector_gate=None, sector_observe_only=False) → trades/curve/state/metrics; deepcopy input state before mutation |
| Sizer | percent_risk_size(equity, cash, fill, stop, config) → nonnegative integer |
| Fill adapter | PaperBrokerAdapter(config).fill(price, quantity, buy-or-sell) → price/fees/slippage; reject invalid side, price or quantity |
| Jobs | submit(type, callable(log, job_id), payload=None) → queued job; update(job_id, status/message/result), recover() |

Coverage response keys: start, end, warmup_sessions, ready_symbols, total_symbols, history_start,
history_end. If no safe interval exists, start/end are null, never fabricated. A symbol is ready
when it has more than warmup+2 bars; a common interval is suggested only when every record exists
and the candidate start is earlier than the candidate end. Runtime simulation session events are
the union of observed dates within the chosen interval; skip dates already in the paper checkpoint.

Job result objects: universe {symbols}; ingestion {symbols,bars}; backtest {run_id}; paper
{portfolio_id,sessions,orders}, or {portfolio_id,sessions:0} for no new sessions. A queued job
contains id/type/status/created_at/logs/payload; updated_at/result arrive during execution.
Job kinds are Refresh universe, Fetch daily candles, Backtest and Paper daily cycle. Order IDs
are `${symbol}:${date}:${side}` scoped inside that portfolio's ledger, not globally unique IDs.
The local protocol has only simulated fill(); place/modify/cancel/get_positions belong to the
future live adapter and must not be mistaken for implemented methods.

API mutations accept full validated configuration, not PATCH operations. Creation returns the
complete portfolio record. Generic status/cycle endpoints require an implemented plugin; registry
lookup alone is insufficient. All API writes use JSON, Content-Type application/json and the local
request header. The browser treats either a string detail or a 422 detail array as an actionable
error. The token is sent only to /api/connection and is never part of sample config payloads.

## Rolling market-data ingestion

### Rolling market-data fetch — 8 October 2026

This contract supersedes the previous editable history-range and missing-boundary behavior of
Market data → Fetch. Settings shows only the research Universe dropdown and private connection
controls. `DataPreferences` accepts only `universe` (nifty50/nifty500/niftytotalmarket; default
nifty50), forbids extra fields, and is the schema returned as bootstrap.settings_schema and
accepted by PUT /api/settings. Saving preserves existing internal start/end values and does
not fetch. Legacy `Settings(DataPreferences)` still includes validated start/end for existing
saved settings, frozen research/paper snapshots and the separate expansion API. Those legacy
dates never determine the standard Market data fetch.

POST /api/jobs/ingest requires the installation's saved token and queues `Fetch market history`
through the existing single-worker queue. The job snapshots the policy (Total Market, rolling
year, ten calendar days); dates are resolved when execution starts. Fetch is independent of the
selected research universe and frozen paper membership: refresh the official Nifty Total Market
list, match every tradeable constituent to an Upstox ISIN/key, and process the full matched list
(750 stocks at implementation). Exclude documented official dummy placeholders; do not silently
omit unmatched real members. The research universe dropdown continues to control scans/backtests.

`core/research/market_data.py` defines these exact rules:
1. Read current Asia/Kolkata time. Before 16:00 IST the latest eligible date is yesterday;
   at/after 16:00 it is today. Request Nifty 50 daily history for the preceding 30 calendar days
   through that date, using `NSE_INDEX|Nifty 50`. Its latest returned validated candle is the
   last completed traded day. Holidays/weekends and historical-provider publication delays
   follow actual returned data. No benchmark candles means an actionable failure before any
   stock writes; never guess an anchor from stale local stock coverage.
2. Daily start is the same calendar date in the preceding year (February 29 maps to February
   28); end is the anchor, inclusive. Request Upstox V3 days/1 for that complete rolling window
   on each stock, even if cached. This refreshes existing dates and fills interior gaps.
3. Five-minute start is anchor minus nine calendar days; end is anchor, inclusive: **10 calendar
   days, not ten trading sessions**. Request V3 minutes/5 once per stock for that range, within
   the provider's one-month retrieval limit. Store only actual returned trading sessions;
   weekends/holidays are not invented. An empty stock response is a failed download.
4. Validate finite positive consistent OHLC, nonnegative volume, duplicate keys, explicit
   intraday timezone and five-minute boundaries. Apply existing verified daily overrides.
   Validate the complete minute response before writing its sessions. Merge daily candles by
   date and same-day minute candles by timestamp, with newly validated candles taking precedence.
   Retain all older daily candles and minute session files, plus older requested coverage.
   Atomic replacement retains the old record if validation fails. Do not trim histories,
   frozen run inputs, portfolios, universe snapshots or ledgers.
5. For each constituent attempt daily and five-minute downloads independently, catching both
   expected validation/provider errors and unexpected exceptions per interval. A stock's 401/403,
   network error, malformed candle or write failure must not skip its other interval or later
   stocks. Unexpected diagnostics include the exception class only, without raw text, request
   headers or tokens. Reuse the provider helper's bounded retries. Sequential requests are paced
   by 0.15 seconds after each interval; no parallel burst. Global prerequisite/manifest storage
   failures can still fail the job. Logs show every stock's outcomes and final counts.
6. Checkpoint non-secret `market_fetch.json` after each stock and at completion. Fields: job_id,
   universe, daily_start, minute_start, end, started_at, completed_at when finished, total_symbols,
   daily_symbols, minute_symbols, daily_bars/minute_bars (validated downloads in this window),
   failures[{symbol,interval,message}], stocks[{symbol,isin,daily,minute}], partial boolean.
   Each interval has status plus counts/coverage or a safe message. Bootstrap returns market_fetch;
   the Market data screen shows resolved windows, counts, failures and completion/progress.
   Daily data/catalog continue using bars/{ISIN}.json and bar_catalog.json. Five-minute sessions
   use intraday/5m/{ISIN}/{YYYY-MM-DD}.json, shared with existing intraday and momentum loaders.
7. `jobs.submit` persists the returned summary even when partial; a completed full-list attempt
   with any interval failures is marked failed with an explicit partial-completion message.
   Successful downloads remain available. Retry through the same Fetch button after fixing the
   connection/provider issue. Do not describe a partial download as fully successful.

Backtest date pickers still use saved actual coverage with required indicator warmup, not these
rolling request dates; retained older data remains usable. All full-fetch state and tokens are
independent locally and in production. Deploy shared code through GitHub, then trigger the job
separately in each environment. Do not publish market data or copy local files onto production.
The official endpoint contract is https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/.
Tests cover leap years, inclusive windows, provider holiday/delay anchors, unfinished-day exclusion,
no benchmark data, filling daily holes while retaining old history, merging minute candles without
removing older days, rejecting malformed minute batches before replacement, universe-only settings
and attempts for both intervals across all 750 stocks despite authentication/unexpected failures.

Execution verification for this policy (8 October 2026): source `ffcec25` was pushed to public
GitHub main, GitHub checks succeeded, a production backup completed with Result=success and
ExecMainStatus=0, and production was rebuilt from that commit. Local job `56e434656706`
attempted both intervals for all 750 stocks; VEDPOWER daily failed after bounded connectivity
retries but its five-minute fetch and the remaining stocks continued. A separate, serialized
recovery job `2ae7c1e933a1` downloaded its 80 daily candles using the original frozen window,
updated the latest market_fetch summary, and retained the original failed job for audit. The
summary includes prior_failures and recovery_job_id for this one-off recovery; these are optional
operational fields, not required by ordinary fetches. Production job `b3d48ec6e710` completed
without failures. Final counts in **both** installations: 750 daily successes, 750 five-minute
successes, 183,138 downloaded daily candles and 393,750 downloaded five-minute candles.
Resolved windows: daily 2025-10-07 through 2026-10-07; five-minute 2026-09-28 through
2026-10-07. These are observed provider windows, not hardcoded future fetch bounds.
Local daily cache retained 961,472 candles, with 477 stocks extending before the rolling year,
and 4,878 older five-minute session files remained. Production retained 1,428,687 daily candles,
with 708 stocks extending before the rolling year. Research-universe selection and frozen
paper membership were preserved. The isolated release passed 136 Python tests and existing
frontend tests; the full concurrent local workspace passed 202 Python tests and its frontend
suite. All 136 release tests also passed in the deployed production image using temporary
isolated state and mounted test/scripts fixtures. Live production bootstrap and JavaScript
rendering confirmed Universe-only settings, both resolved windows and progress/count display.

### Fundamentals included in Market data fetch — 9 October 2026

Market data → Fetch prices & fundamentals now runs three stages for the same current 750-stock
Nifty Total Market universe: rolling-year daily candles, last-ten-calendar-day five-minute
candles, then quarterly fundamentals. Candle windows and retention remain as specified above.
The fundamentals stage uses the official NSE integrated-financials index and direct NSE Ind-AS
HTML filings; no provider token, LLM or paid data key is needed for that stage. One failed
stock must not abort the remaining fundamental checks. Unexpected per-stock exceptions expose
only their class. A fundamentals-stage failure cannot undo saved candles. The market_fetch
result has a nested fundamentals summary; any failed stage/stock marks the job partial/failed.
Unsupported financial taxonomies are counted honestly, not turned into fabricated snapshots.

Fundamentals implementation files: core/research/fundamentals.py (pull/lock/validation/coverage),
core/research/official_filings.py (official index/parser/calculation), and core/research/company_review.py
(validated input schema, deterministic scorer, source/date eligibility and company overview).
The company API router and company-review.js make the existing Fundamentals page available in
production. This publication adds the data fetch, evidence view and quality checks; it does not
change existing production paper-entry predicates or historical backtest priority. Local paper
and research experiments in other unfinished work retain their own separate scope.

For each stock keep company, snapshot, score/checks, source documents, validation, latest indexed
period, last_period_end, next_quarter_end, last_checked_at, last_attempted_at and last_pulled_at.
Latest records live in company/fundamentals/{ISIN}.json; each successful version is also retained
under company/fundamentals/{ISIN}/history/{snapshot_id}.json. Raw HTML and parsed financial facts
are content-addressed in company/filings/{sha256}.html and .json. Validate exact identity, financial
period/publication time, accounting basis, INR units, hashes and recomputed metrics before saving.
Failed updates retain older validated snapshots. Never delete older versions or source files.

Prefer consolidated filings for the newest indexed period, otherwise standalone. Query the NSE
index for up to the preceding 800 calendar days, choosing up to eight latest revisions for the
latest quarter, its prior-year quarter, the latest completed annual March period and its prior-year
annual comparator. The 800-day search is **not** a promise of 800 days of stored quarterly history.
Only those selected source periods are downloaded. Missing balance sheet/annual inputs stay unknown.
BANKING and NBFC_INDAS taxonomies are supported by the remaining-data refresh contract below; other unsupported forms remain incomplete.
P/E, full promoter-pledge and governance research are not inferred from missing fields.

Skip a stored snapshot covering the latest completed calendar quarter until the next quarter ends.
Otherwise check the index at most once per UTC day; when the next quarter remains unpublished,
retain the existing snapshot without redownloading its source filings. The explicit combined
Market data fetch retries previously failed stocks even if checked today (`retry_failed=True`).
Same-quarter revisions are not reingested by this policy. Standalone pull API/CLI retains its
ordinary daily-skip behavior, with CLI --retry-failed for an explicit same-day retry.
Use a cross-process filesystem lock so a standalone pull cannot overlap the combined pull.

Scored nonfinancial fields: quarterly revenue growth YoY (15 points if >=10%), PAT growth YoY
(20 if >=10%), ROE (15 if >=12%), ROCE (10 if >=15%), debt/equity (10 if <=1), interest coverage
(5 if >=3), annual operating cash flow/PAT (5 if >=0.8), pledging (10 if <=5%), no auditor concern
(5) and no governance concern (5). Missing metrics receive zero points and reduce evidence coverage.
Financial-sector inputs have separate NPA/capital-adequacy rules, but the filing downloader does
not yet populate them. Scores are experimental and must not be described as validated predictors.
Financial periods older than 180 days are flagged stale; source publication and recorded time
are both respected when choosing a snapshot for a given decision time.

Progress/checkpoints: company/fundamentals_pull.json holds job_id, started_at, total_symbols,
counts by status, stock results, completed_at, partial and coverage. The nested market_fetch
fundamentals object returns this summary. company/fundamentals_coverage.json is measured at
completion and distinguishes validated stocks, missing stocks, pull statuses, scored snapshot
period counts, retained versions, distinct company-periods, stocks with multiple snapshot periods,
unique comparative source filings, source period counts and first/last source publication.
GET /api/company/fundamentals-history returns the cached measurement, computing it when absent.
GET /api/company includes history_coverage. The Fundamentals page displays it separately from
scores; Market data shows validated coverage, updated/failed/unsupported counts and the page link.
The archive contains comparative quarterly and annual evidence, not a complete consecutive-quarter
scored history; older filings may have been collected retrospectively. Current scores must never
be substituted into historical decisions. company/fundamentals_validation.json separately records
an offline audit of checksums, identity, periods and metric reconstruction.

Operational commands: `python scripts/pull_fundamentals.py` (Total Market default),
`--retry-failed`, `--symbols TCS STLTECH` for focused retries, and `--validate-only` for an offline
source audit. Production runs the same command within its container/state mounts; tokens and
all source/price/fundamental data remain installation-specific and excluded from Git/images.
POST /api/company/fundamentals-pull queues a standalone fundamental refresh. Existing company
quality-check APIs and source review routes use the shared origin/auth guards. Deploy source
through GitHub after tests/backup, then trigger the combined job separately locally/production.

## API, security, storage and recovery

Execution and history coverage verified on 9 October 2026: published source commit `a658e1a`
passed GitHub CI and was deployed after a successful backup (Result=success, ExecMainStatus=0).
Local combined job `b8b503e6e1b7` and production job `381c05672afa` each attempted all 750
stocks. Both saved daily and five-minute data for 750/750 stocks with zero candle failures.
Windows were daily 2025-10-08–2026-10-08 and five-minute 2026-09-29–2026-10-08;
production downloaded 183,180 daily and 393,750 five-minute candles. Older files were retained.

Both environments have 567 validated financial snapshots and 183 stocks without validated
fundamentals: 118 unsupported (including the financial-sector adapter limitation) and 65 failures.
Of the 65 failures, 59 could not validate the latest indexed quarter and six had no supported
NSE Ind-AS filings. These are genuine missing/unsupported evidence, not successful scores.
The combined jobs are therefore marked failed/partial despite complete candles; failed stocks
were processed without aborting the remaining universe. Local results were 566 awaiting the
next published quarter, one already-current snapshot, 118 unsupported and 65 failures. Production
started its own independent cache and saved 567 new snapshots. No local financial data was copied.

Each environment retains one scored snapshot per covered stock: one period ended 2026-03-31,
565 ended 2026-06-30 and one ended 2026-09-30. There are 567 distinct company-periods and zero
companies with multiple scored snapshot quarters. The 2,103 unique supporting source filings
have period counts: 2024-09-30:1; 2025-03-31:476; 2025-06-30:504; 2025-09-30:1;
2026-03-31:555; 2026-06-30:565; 2026-09-30:1. These include annual financial evidence and
selected year-ago quarterly comparisons. One old source period must not be described as two
years of complete financial history for all companies. Source publication dates range from
2025-04-08 through 2026-10-08; collection happened later. A complete consecutive-quarter
historical fundamentals panel does not yet exist.

All 567 local snapshots passed the full offline source/hash/identity/metric audit (183 missing,
zero validation failures). Production validated identity, source hashes and recomputed metrics
for all 567 snapshots while pulling; a separate integrity check re-hashed all 2,103 referenced
source files with zero mismatches. Its safe report is company/fundamentals_integrity.json.
The isolated release passed 189 Python tests locally and in the production image, plus frontend
checks. Live UI/API checks confirmed all 750 production company rows and the historical report.
Local API was reloaded after its job finished to expose the new history route, retaining its
existing research credentials. The Funds page now refreshes saved evidence after a partial
standalone pull or completion of the combined fetch, shows the coverage measurement timestamp,
and guards its timer while the main application loads. It does not repeatedly reload an
unchanged completed fetch; frontend regressions cover all three cases.

### API, security and persistence contract

All routes use the same origin and optional Basic Auth (unset in the public MVP). Bind 127.0.0.1:8765 with one process, never reload/multiple workers. Local launch disables proxy headers. Production trusts proxy headers only from 127.0.0.1; Caddy removes X-Forwarded-For so the peer remains loopback. Accept loopback peers and localhost/loopback hosts (testclient/testserver in tests), plus the hostname of explicitly configured TRADER_PUBLIC_ORIGIN. Mutations require `X-Trader-Request: local-ui`; when Origin is present, require exact TRADER_PUBLIC_ORIGIN for the public host, otherwise exact base-origin match. These guards are not a login or authorization system. Security response headers: nosniff, DENY frames,
no-referrer and no-store. Do not expose OpenAPI/docs endpoints. ValueError returns 400 detail. Standard schema errors return 422 locations/messages without echoing inputs; generic plugin-config validation returns a safe 422 detail string. Invalid/missing run, bar and job IDs return 404; unknown strategy IDs and unimplemented paper plugins return 400, and GET of a valid strategy without a portfolio returns JSON null.

Storage root defaults to repository/data; override with TRADER_DATA_DIR. Atomic JSON writes through `store.write` use
UTF-8, reject NaN, write a unique sibling `.{filename}.{uuid4hex}.tmp` in exclusive-create mode,
flush and os.fsync the temporary file, then atomically replace, guarded by an in-process RLock.
Retry replacement only on PermissionError, up to five attempts with delays 0.05, 0.10, 0.20
and 0.40 seconds between attempts; permanent failure leaves the previous committed file intact.
Best-effort remove the unique temporary file on either success or failure. This handles brief
Windows reader/scanner locks and avoids shared temporary filename collisions. This is not
a multi-process database. Store timestamps UTC ISO strings, display IST. No broker tokens appear
in reports, logs or bootstrap. The private directory is TRADER_PRIVATE_DIR or DATA/private; new token records contain access_token and saved_at. Legacy encrypted_token records alone require Fernet .local-key (override TRADER_KEY_FILE). Keep legacy token/key together to restore them, or reconnect. No new encrypted records are written. Optional auth requires
both DASHBOARD_ADMIN_USER and DASHBOARD_ADMIN_PASSWORD; supplying just one prevents startup.
`.env` is not loaded automatically.

Local ingestion incident on 8 October 2026: job `347f2f2fed9e` failed after CHENNPETRO's
candle and catalog save while recording progress; a single-stock retry succeeded. The saved
settings were Nifty 500, 2019-01-01 through 2026-10-08. Retry `f5eeba0be448` using the existing
server also halted during progress recording after ADANIPOWER. The old catch-all discarded
exception details, so the precise original exception class cannot be recovered from these
logs. The stage implicates persistence; a transient Windows file lock is the working diagnosis,
not a verified provider candle error. The atomic-write hardening above addresses file locks
and temporary-name collisions. Unexpected job failures now record only exception class and
the final source basename/line, never exception text, full paths, headers or raw responses.
Three regression tests cover transient lock recovery, bounded permanent failure with the old
checkpoint intact, and credential-safe diagnostics; the complete local Python suite passed
191 tests. The existing API server had not loaded this source change. Automatic approval
review blocked its restart command without a specific reason beyond blocked by policy.
Recovery job `9abe7f797f1b` was submitted from a temporary standalone worker using the updated
modules and the usual job registry/queue checks; progress remains visible in the local UI.
Do not run another writer/job concurrently or confuse local Nifty 500 ingestion with the
separate production 750-stock pull. Persistent files and credentials are independent.
Recovery `9abe7f797f1b` completed successfully at 19:13 IST, refreshing all 500 stocks and
retaining 900,816 candles. The requested cutoff was October 8; observed final bars were
October 7. Research settings and universe were preserved. The temporary recovery worker
exited after completion. The existing server initially still needed a restart to import the
new atomic-write and error-diagnostic code. After the owner explicitly requested that restart,
the local server was restarted through `start.ps1` at 19:20 IST. Verified the new listener,
successful bootstrap, unchanged Nifty 500 settings, 500 cached stocks and the preserved
successful recovery job with 900,816 candles. Ordinary UI jobs now load the updated code.

| File under data/ | Contents |
|---|---|
| settings.json | universe, requested start/end |
| private/upstox.json (or separate TRADER_PRIVATE_DIR/upstox.json) | New: access_token, saved_at; legacy: encrypted_token, saved_at; never publish or include in data backups |
| universes/{universe}.json | name, fetched_at, membership=current_snapshot, source URL, source_row_count, provider_exclusions [{symbol,isin,reason}], instruments [{symbol,name,sector,key,isin,series}] |
| bars/{isin}.json | instrument, bars [{date,timestamp,open,high,low,close,volume}], fetched_at, source=upstox_v3, requested_start/end, adjustments=unverified, verified_repairs |
| provider_overrides/{isin}.json | repairs [{date,provider_values,verified_candle,source,reason,verified_at}]; exact-match independently verified source corrections only |
| bar_catalog.json | keyed by ISIN: count, first/last, close, change percent |
| screens.json | newest-first resolved saved-screen array |
| jobs.json | id/type/status/created_at/updated_at/payload/logs [{at,message}]/result |
| runs_index.json | newest-first id/created_at/config/universe/metrics summaries |
| runs/{id}.json | trades, curve, metrics, id/created_at/config/universe, universe_snapshot, manifest, excluded, warnings; persistent simulator state is removed before saving |
| run_data/{id}.json | frozen symbol→complete chronological bars used by run |
| portfolios/{strategy_id}.json | identity/mode/status/capital config, frozen universe/history, ledger/fingerprints/cycles/config_history/timestamps |
| paper_schedule.json | Swing attempt_day/at/job_id and optional recovery timestamp |
| paper_schedules/{strategy_id}.json | Future strategies' independent schedule claims |

Manifest per symbol: symbol, source, bar count, first/last, verified_repairs and SHA256 of
json.dumps(bars,sort_keys=True). Hash includes the normalized full loaded bar list, not only
the trading interval. Retain historical manifests without adding fields to old saved reports.
Ledger: cash, positions, marks, trades, curve, orders, last_session, peak, max_dd, total_fees,
total_slippage, skipped. Position: entry/date/cost/fee/quantity/stop/best_close/initial_risk/age/
exit_config. Trade: symbol, entry_date, exit_date, entry, exit, quantity, pnl, r, reason, fees.
Order: stable symbol:date:side ID, symbol/date/side/quantity/price/fees/status=FILLED/reason;
paper adds mode/portfolio/job linkage. Never serialize tokens into these structures.

One ThreadPoolExecutor worker runs queued→running→success/failed jobs. Reject new jobs while
queued/running work exists. Log ValueError as actionable text; unexpected failures use a generic
credential-safe message. A partial ingest may save successful symbols and report failures; do
not replace existing valid symbol files with bad data or claim all symbols succeeded.

Provider endpoints: official constituent CSVs at
`https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv` and `ind_nifty500list.csv`;
instrument master `https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz`;
historical URL `https://api.upstox.com/v3/historical-candle/{encoded_key}/days/1/{end}/{start}`.
Join CSV ISIN Code to NSE_EQ instruments by ISIN, prefer EQ, otherwise accept an unambiguous
provider key including BE/RR series. Exclude only rows with Symbol starting DUMMY and ISIN
starting DUM; record them explicitly. Fail all universe refresh on ordinary unmatched/ambiguous
members, duplicate ISINs or count <45/<450. Apply verified overrides to incoming provider rows
before validate_candles; leave ordinary validation failures actionable. Retry provider calls three times on network/transient status errors;
401/403 is actionable token/network failure. Validate finite positive prices, nonnegative volume,
low≤open/close≤high, no duplicate/out-of-request dates. Sort/merge by session date. Never invent
sessions; boundary-only ingestion does not repair internal gaps or revise all historical bars.

### Current route inventory

Extracted from the current API source. Static assets are mounted at /static. Company routes inherit authentication/origin checks; model and feature contracts below describe payloads.

| Method | Route | Handler |
|---|---|---|
| GET | `/` | `dashboard/api/main.py::index` |
| GET | `/api/bootstrap` | `dashboard/api/main.py::bootstrap` |
| PUT | `/api/settings` | `dashboard/api/main.py::save_settings` |
| POST | `/api/bearish/scan` | `dashboard/api/main.py::scan_bearish` |
| PUT | `/api/connection` | `dashboard/api/main.py::save_connection` |
| POST | `/api/screens` | `dashboard/api/main.py::save_screen` |
| POST | `/api/jobs/universe` | `dashboard/api/main.py::universe_job` |
| GET | `/api/data-quality` | `dashboard/api/main.py::audit_price_history` |
| POST | `/api/jobs/ingest` | `dashboard/api/main.py::ingest_job` |
| POST | `/api/jobs/universe-expansion` | `dashboard/api/main.py::universe_expansion_job` |
| POST | `/api/jobs/backtest` | `dashboard/api/main.py::backtest_job` |
| GET | `/api/backtest/window` | `dashboard/api/main.py::backtest_window` |
| GET | `/api/sectors` | `dashboard/api/main.py::sector_audit` |
| POST | `/api/jobs/sectors` | `dashboard/api/main.py::sector_fetch_job` |
| POST | `/api/jobs/sector-comparison` | `dashboard/api/main.py::sector_comparison_job` |
| POST | `/api/jobs/momentum` | `dashboard/api/main.py::momentum_job` |
| POST | `/api/jobs/momentum-comparison` | `dashboard/api/main.py::momentum_comparison_job` |
| POST | `/api/momentum/coverage` | `dashboard/api/main.py::momentum_coverage` |
| POST | `/api/jobs/scalping` | `dashboard/api/main.py::scalping_job` |
| POST | `/api/scalping/coverage` | `dashboard/api/main.py::scalping_coverage` |
| POST | `/api/jobs/scalping-comparison` | `dashboard/api/main.py::scalping_comparison_job` |
| GET | `/api/scalping/paper/portfolio` | `dashboard/api/main.py::get_scalping_paper` |
| GET | `/api/scalping/paper/export` | `dashboard/api/main.py::export_scalping_paper` |
| POST | `/api/scalping/paper/portfolio` | `dashboard/api/main.py::create_scalping_paper` |
| PUT | `/api/scalping/paper/portfolio` | `dashboard/api/main.py::update_scalping_paper` |
| PUT | `/api/scalping/paper/status` | `dashboard/api/main.py::scalping_status` |
| GET | `/api/scalping/paper/runner` | `dashboard/api/main.py::scalping_runner_status` |
| POST | `/api/scalping/paper/start` | `dashboard/api/main.py::start_scalping_runner` |
| POST | `/api/scalping/paper/stop` | `dashboard/api/main.py::stop_scalping_runner` |
| POST | `/api/paper/portfolio` | `dashboard/api/main.py::create_paper` |
| PUT | `/api/paper/portfolio` | `dashboard/api/main.py::update_paper` |
| PUT | `/api/paper/status` | `dashboard/api/main.py::paper_status` |
| POST | `/api/jobs/paper` | `dashboard/api/main.py::paper_job` |
| GET | `/api/strategies/{strategy_id}/paper/portfolio` | `dashboard/api/main.py::get_strategy_portfolio` |
| POST | `/api/strategies/{strategy_id}/paper/portfolio` | `dashboard/api/main.py::create_strategy_portfolio` |
| PUT | `/api/strategies/{strategy_id}/paper/portfolio` | `dashboard/api/main.py::update_strategy_portfolio` |
| PUT | `/api/strategies/{strategy_id}/paper/status` | `dashboard/api/main.py::update_strategy_status` |
| POST | `/api/strategies/{strategy_id}/paper/cycle` | `dashboard/api/main.py::strategy_paper_job` |
| GET | `/api/bars/{isin}` | `dashboard/api/main.py::bars` |
| GET | `/api/runs/{run_id}` | `dashboard/api/main.py::run_result` |
| GET | `/api/jobs/{job_id}` | `dashboard/api/main.py::job_detail` |
| GET | `/api/runs/{run_id}/trades/{trade_index}/chart` | `dashboard/api/main.py::trade_chart` |
| GET | `/api/company` | `dashboard/api/company_review.py::overview` |
| GET | `/api/company/fundamentals-history` | `dashboard/api/company_review.py::fundamentals_history` |
| GET | `/api/company/fundamentals/{isin}` | `dashboard/api/company_review.py::stored_fundamentals` |
| GET | `/api/company/buy-screen/{strategy}` | `dashboard/api/company_review.py::buy_screen` |
| PUT | `/api/company/buy-screen/{strategy}` | `dashboard/api/company_review.py::save_buy_screen` |
| GET | `/api/company/buy-check/{strategy}/{isin}` | `dashboard/api/company_review.py::buy_check` |
| POST | `/api/company/fundamentals-pull` | `dashboard/api/company_review.py::pull_fundamentals` |
| POST | `/api/company/evidence` | `dashboard/api/company_review.py::import_evidence` |
| GET | `/api/company/evidence/{isin}` | `dashboard/api/company_review.py::evidence` |
| POST | `/api/company/scan` | `dashboard/api/company_review.py::scan` |
| POST | `/api/company/reviews` | `dashboard/api/company_review.py::create_review` |
| POST | `/api/company/research` | `dashboard/api/company_review.py::automatic_research` |
| GET | `/api/company/reviews/{review_id}` | `dashboard/api/company_review.py::review` |

## Verification contracts

### Regression acceptance requirements

Backtest dialog correction (deployed 4 October 2026, source commit
`bc0cc06381ec166793e19dad5e98d796764a996c`): open the modal immediately with a
"Checking downloaded history and available test dates" status before awaiting the window API.
Render the completed form only if the dialog is still open and its request generation matches;
closing it or starting another request must discard stale responses. Window fetch failures
appear inside the dialog. Do not silently clamp cloned experiment configurations.

`available_window` keeps compact chronological session-date/requested-range metadata cached
per bar-file path and `(mtime_ns, size)`, bounded to 2048 entries, invalidated on atomic ingestion
updates. Read one uncached record at a time, not every universe OHLCV record simultaneously.
Return `missing_symbols` alongside the existing response fields. A symbol with absent/empty bars
blocks the safe-window recommendation; do not silently remove it from the universe. Bound the
recommended end by both observed candle coverage and recorded requested coverage.

Keep a status explanation next to the Run backtest button: name an active job, missing symbols
or insufficient history. Refresh this status during normal bootstrap polling, so finishing an
active job re-enables the existing form without reopening it. Preserve the disabled state while
that form submits. Reject a chosen end after the safe available end locally with instructions
to use available dates or fetch rolling market history (older saved history is retained). Scroll form errors
into view on mobile. Backend date errors give the same earlier/later-history instruction.

Observed production diagnosis: 499 of 500 Nifty 500 symbols had usable records; IDEA ingestion
failed with "Invalid OHLCV candle detected", and no IDEA record was written. Validation correctly
rejected a genuine provider-data error. Requested history ended
2026-10-01, so a test ending 2026-10-04 exceeded its recorded coverage. These are dated
observations, not hardcoded UI limits. The deployed first/cached window requests measured
approximately 5.04/0.23 seconds; the loading modal is visible immediately even on a cold request.
All 48 deployed Python tests passed; Node tests cover immediate opening, stale-response
cancellation, job-finish re-enablement and named missing-data explanations. Phone-sized
390×844 UI inspection confirmed the visible IDEA blocker next to disabled Run.

Production recovery on 4 October 2026: re-fetching Upstox's IDEA candle for 2024-08-30
confirmed OHLC `[16.44, 16.44, 15.39, 15.64]` and invalid volume `-81259413`.
The research work had already independently verified the matching NSE bhavcopy row with
volume `4213707883` (see the exact override JSON below). Production had started with fresh
state and therefore lacked that environment-specific correction. Install that exact recipe at
`/srv/trader/data/provider_overrides/INE669E01016.json` (container path
`/state/data/provider_overrides/INE669E01016.json`, owned by UID 10001). The existing provider
adapter applies it only when the date and all five original numeric OHLCV values match,
then validates the replacement normally; unmatched errors must still fail. This recovery used
the previously verified NSE evidence and freshly checked Upstox row; attempts to re-download
the NSE archive during production recovery timed out. No general overflow correction or
unconditional exception was added. This small recipe is a reproducible provider correction,
not a copy of local research datasets; runtime files remain outside GitHub.

After installation, production ingestion job `dfb94361ed9e` completed successfully at
2026-10-04 14:13:08 UTC with `symbols=500`, `bars=834559`; IDEA contributed 1983 bars.
History requested remains 2018-10-01 through 2026-10-01. The earlier failed jobs remain in
the job history as evidence; their status is not rewritten. On a fresh installation, reproduce
and verify this correction before ingestion if Upstox still supplies that exact invalid row.

Regression acceptance: custom→every built-in resets all applicable schema filters and checkbox.checked;
old presets inherit disabled new-filter defaults; exact provider repair matches all values;
ordinary unmatched/ambiguous constituents fail; RS ranking uses only completed-session prefixes;
trend/warmup/breadth options obey their bounds and default-disabled compatibility; fresh VCP form applies the preset;
saved-screen sidebar selection opens the correct option/values; cloning preserves explicit old
values until selection; single dropdown submits correct hidden pattern; costs/risk/capital remain
unchanged; pivot above high never fills; no retroactive pivot/close stops; final-session positions
liquidate; next-open gaps/costs/shared cash remain correct; paper cycles are forward-only,
idempotent, atomic on failure, detect historical revisions, preserve exit settings and enforce
isolated strategy identities/capital. Include API host/origin/token-privacy validation and
scheduler one-attempt/restart checks. Tests use synthetic fixtures only, never dashboard data.

### Rebuild and verification sequence

1. Create the local source paths listed above plus core/portfolio/{manager,registry,paper,scheduler}.py,
   core/risk/position_sizer.py and core/execution/paper.py. Keep production modules separate.
2. Implement schemas/storage/security and bootstrap, registry, provider ingestion and jobs.
3. Implement predicates and the shared daily simulator to the formulas and conventions above.
4. Build the HTML shell, design tokens, nine production views/eight local views, dialogs/preset merge and polling behavior; gate paper routes/scheduler on TRADER_ENV.
5. Implement paper manager/plugin/cycle/scheduler using the same simulator; persist independently.
6. Vendor KLineChart and its license. Add Python execution/data/API/paper tests and Node dropdown
   regression tests. No production DB, Redis, broker SDK, vectorbt or frontend framework is needed.
7. Start locally, enter a token through Settings, refresh universe, fetch actual data, inspect a
   chart, run a backtest and inspect/export its complete report. Separately deploy production from the embedded specification, enter its own token, load its own history and create paper there if desired.

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-lock.txt
npm.cmd install
npm.cmd run vendor
npm.cmd run check
npm.cmd test
.venv/Scripts/python.exe -m unittest discover -s tests -q
./start.ps1
```

The commands above assume a document-only rebuild: first create requirements-lock.txt from the
pinned dependency list below and package.json from its complete contents later in this document.
For an existing checkout with package-lock.json, use `npm.cmd ci` instead of `npm.cmd install`.
If rebuilding without the original Python lockfile, the current local direct requirements are FastAPI
≥0.115,<1; Uvicorn ≥0.34,<1; httpx ≥0.28,<1; cryptography ≥44,<51, with Pydantic 2 schemas.
The observed environment uses Python 3.13; exact pinned dependency snapshot follows below.
package.json is private, version 0.1.0, depends on klinecharts 9.8.12. Scripts: vendor runs
`node scripts/vendor.mjs`, check runs `node --check dashboard/web/app.js`, test runs
`node tests/test_screen_presets.cjs`. Vendor script copies the library and Apache license into
dashboard/web/vendor/. Start runs Uvicorn on loopback port 8765 with --no-proxy-headers.
Ignore .venv, __pycache__, all data/, .local-key, .env and runtime logs/pids; do not commit secrets.
No document can regenerate previously fetched candles or private tokens: reconnect and fetch real
history, or restore a secure backup. Never hardcode the historical metrics as dashboard content.

## Exact configuration schemas (9 October 2026)

Generated from current Pydantic models. Defaults are API defaults; UI presets can override them. Cross-field/time/date/acknowledgment validators still apply. Dependency pins live in requirements-lock.txt, package-lock.json and deploy/market-data/requirements.txt; duplicated source/lock dumps were removed. Nested record definitions remain in the identified implementation.

### DataPreferences

Implementation: `core/research/config.py`.

| Field | Type / constraints | Default |
|---|---|---|
| `universe` | {"enum":["nifty50","nifty500","niftytotalmarket"],"type":"string"} | "nifty50" |

### Settings

Implementation: `core/research/config.py`.

| Field | Type / constraints | Default |
|---|---|---|
| `universe` | {"enum":["nifty50","nifty500","niftytotalmarket"],"type":"string"} | "nifty50" |
| `start` | {"format":"date","type":"string"} | "2018-10-01" |
| `end` | {"format":"date","type":"string"} | "2026-10-01" |

### ScreenInput

Implementation: `core/research/strategy_presets.py`.

| Field | Type / constraints | Default |
|---|---|---|
| `name` | {"maxLength":80,"minLength":1,"type":"string"} | Required |
| `pattern` | {"enum":["vcp","blue_sky","multiyear","ipo"],"type":"string"} | "vcp" |
| `base_days` | {"maximum":250,"minimum":5,"type":"integer"} | 25 |
| `max_depth_pct` | {"exclusiveMinimum":0,"maximum":80,"type":"number"} | 30 |
| `volume_multiple` | {"maximum":10,"minimum":0.1,"type":"number"} | 1.5 |
| `sma_days` | {"maximum":250,"minimum":5,"type":"integer"} | 50 |
| `require_long_trend` | {"type":"boolean"} | false |
| `require_rising_long_trend` | {"type":"boolean"} | false |
| `min_rs_rating` | {"maximum":100,"minimum":0,"type":"number"} | 0 |
| `min_turnover` | {"maximum":1000000000000.0,"minimum":0,"type":"number"} | 50000000 |
| `vcp_window_days` | {"maximum":60,"minimum":3,"type":"integer"} | 10 |
| `vcp_volume_multiple` | {"exclusiveMinimum":0,"maximum":1,"type":"number"} | 0.8 |
| `blue_sky_lookback_days` | {"maximum":5000,"minimum":50,"type":"integer"} | 5000 |
| `multiyear_base_days` | {"maximum":2500,"minimum":252,"type":"integer"} | 260 |
| `multiyear_max_depth_pct` | {"exclusiveMinimum":0,"maximum":90,"type":"number"} | 50 |
| `ipo_max_age_days` | {"maximum":3653,"minimum":1,"type":"integer"} | 730 |
| `trading_defaults` | {"anyOf":[{"$ref":"#/$defs/TradingConfig"},{"type":"null"}]} | null |
| `minimum_warmup_sessions` | {"anyOf":[{"maximum":2500,"minimum":50,"type":"integer"},{"type":"null"}]} | null |
| `source_run_id` | {"anyOf":[{"pattern":"^[0-9a-f]{12}(?:_[a-z0-9]+)?$","type":"string"},{"type":"null"}]} | null |
| `description` | {"maxLength":1500,"type":"string"} | "" |

### BacktestConfig

Implementation: `core/research/config.py`.

| Field | Type / constraints | Default |
|---|---|---|
| `name` | {"maxLength":80,"minLength":1,"type":"string"} | "Breakout experiment" |
| `pattern` | {"enum":["breakout","vcp","blue_sky","multiyear","ipo"],"type":"string"} | "breakout" |
| `capital` | {"maximum":10000000000.0,"minimum":1000,"type":"number"} | 1000000 |
| `base_days` | {"maximum":250,"minimum":5,"type":"integer"} | 25 |
| `max_depth_pct` | {"exclusiveMinimum":0,"maximum":80,"type":"number"} | 30 |
| `volume_multiple` | {"maximum":10,"minimum":0.1,"type":"number"} | 1.5 |
| `sma_days` | {"maximum":250,"minimum":5,"type":"integer"} | 50 |
| `require_long_trend` | {"type":"boolean"} | false |
| `require_rising_long_trend` | {"type":"boolean"} | false |
| `min_rs_rating` | {"maximum":100,"minimum":0,"type":"number"} | 0 |
| `candidate_rank` | {"enum":["alphabetical","rs_126","fundamental_score"],"type":"string"} | "alphabetical" |
| `min_turnover` | {"maximum":1000000000000.0,"minimum":0,"type":"number"} | 50000000 |
| `vcp_window_days` | {"maximum":60,"minimum":3,"type":"integer"} | 10 |
| `vcp_volume_multiple` | {"exclusiveMinimum":0,"maximum":1,"type":"number"} | 0.8 |
| `blue_sky_lookback_days` | {"maximum":5000,"minimum":50,"type":"integer"} | 5000 |
| `multiyear_base_days` | {"maximum":2500,"minimum":252,"type":"integer"} | 260 |
| `multiyear_max_depth_pct` | {"exclusiveMinimum":0,"maximum":90,"type":"number"} | 50 |
| `entry_mode` | {"enum":["pivot","close","next_open"],"type":"string"} | "pivot" |
| `risk_pct` | {"exclusiveMinimum":0,"maximum":5,"type":"number"} | 1.5 |
| `stop_pct` | {"exclusiveMinimum":0,"maximum":50,"type":"number"} | 8 |
| `winner_exit` | {"enum":["trail_50d","trail_30w","take_8","take_15","take_25"],"type":"string"} | "trail_50d" |
| `skip_weak_markets` | {"type":"boolean"} | false |
| `sector_filter` | {"enum":["off","trend","trend_rs"],"type":"string"} | "off" |
| `market_breadth_pct` | {"maximum":100,"minimum":0,"type":"number"} | 40 |
| `market_min_coverage_pct` | {"exclusiveMinimum":0,"maximum":100,"type":"number"} | 80 |
| `ipo_max_age_days` | {"maximum":3653,"minimum":1,"type":"integer"} | 730 |
| `breakeven_r` | {"maximum":10,"minimum":0.1,"type":"number"} | 1 |
| `trail_pct` | {"exclusiveMinimum":0,"maximum":50,"type":"number"} | 8 |
| `max_positions` | {"maximum":50,"minimum":1,"type":"integer"} | 5 |
| `max_hold_days` | {"maximum":1000,"minimum":1,"type":"integer"} | 120 |
| `slippage_bps` | {"maximum":500,"minimum":0,"type":"number"} | 10 |
| `buy_cost_bps` | {"maximum":500,"minimum":0,"type":"number"} | 10 |
| `sell_cost_bps` | {"maximum":500,"minimum":0,"type":"number"} | 10 |
| `execution_horizon` | {"enum":["swing","intraday"],"type":"string"} | "swing" |
| `square_off_time` | {"pattern":"^\\d{2}:\\d{2}$","type":"string"} | "15:00" |
| `comparison_run_id` | {"anyOf":[{"pattern":"^[0-9a-f]{12}(?:_[a-z0-9]+)?$","type":"string"},{"type":"null"}]} | null |
| `minimum_warmup_sessions` | {"maximum":2500,"minimum":50,"type":"integer"} | 50 |
| `start` | {"format":"date","type":"string"} | Required |
| `end` | {"format":"date","type":"string"} | Required |
| `acknowledge_limitations` | {"type":"boolean"} | false |

### BearishBacktestConfig

Implementation: `core/research/config.py`.

| Field | Type / constraints | Default |
|---|---|---|
| `pattern` | {"enum":["vcp_breakdown","new_lows","multiyear_breakdown","ipo_breakdown"],"type":"string"} | "new_lows" |
| `base_days` | {"maximum":250,"minimum":5,"type":"integer"} | 25 |
| `max_depth_pct` | {"exclusiveMinimum":0,"maximum":80,"type":"number"} | 30 |
| `volume_multiple` | {"maximum":10,"minimum":0.1,"type":"number"} | 1.5 |
| `sma_days` | {"maximum":250,"minimum":5,"type":"integer"} | 50 |
| `require_falling_long_trend` | {"type":"boolean"} | true |
| `max_rs_rating` | {"maximum":100,"minimum":0,"type":"number"} | 30 |
| `min_turnover` | {"maximum":1000000000000.0,"minimum":0,"type":"number"} | 50000000 |
| `vcp_window_days` | {"maximum":60,"minimum":3,"type":"integer"} | 10 |
| `vcp_volume_multiple` | {"exclusiveMinimum":0,"maximum":1,"type":"number"} | 0.8 |
| `low_lookback_days` | {"maximum":5000,"minimum":50,"type":"integer"} | 252 |
| `multiyear_base_days` | {"maximum":2500,"minimum":252,"type":"integer"} | 260 |
| `multiyear_max_depth_pct` | {"exclusiveMinimum":0,"maximum":90,"type":"number"} | 50 |
| `ipo_max_age_days` | {"maximum":3653,"minimum":1,"type":"integer"} | 730 |
| `require_weak_market` | {"type":"boolean"} | true |
| `max_market_breadth_pct` | {"maximum":100,"minimum":0,"type":"number"} | 40 |
| `market_min_coverage_pct` | {"exclusiveMinimum":0,"maximum":100,"type":"number"} | 80 |
| `name` | {"maxLength":80,"minLength":1,"type":"string"} | "Breakout experiment" |
| `capital` | {"maximum":10000000000.0,"minimum":1000,"type":"number"} | 1000000 |
| `require_long_trend` | {"type":"boolean"} | false |
| `require_rising_long_trend` | {"type":"boolean"} | false |
| `min_rs_rating` | {"maximum":100,"minimum":0,"type":"number"} | 0 |
| `candidate_rank` | {"enum":["alphabetical","rs_126","fundamental_score"],"type":"string"} | "alphabetical" |
| `blue_sky_lookback_days` | {"maximum":5000,"minimum":50,"type":"integer"} | 5000 |
| `entry_mode` | {"enum":["pivot","close","next_open"],"type":"string"} | "pivot" |
| `risk_pct` | {"exclusiveMinimum":0,"maximum":5,"type":"number"} | 1.5 |
| `stop_pct` | {"exclusiveMinimum":0,"maximum":50,"type":"number"} | 8 |
| `winner_exit` | {"enum":["trail_50d","trail_30w","take_8","take_15","take_25"],"type":"string"} | "trail_50d" |
| `skip_weak_markets` | {"type":"boolean"} | false |
| `sector_filter` | {"enum":["off","trend","trend_rs"],"type":"string"} | "off" |
| `market_breadth_pct` | {"maximum":100,"minimum":0,"type":"number"} | 40 |
| `breakeven_r` | {"maximum":10,"minimum":0.1,"type":"number"} | 1 |
| `trail_pct` | {"exclusiveMinimum":0,"maximum":50,"type":"number"} | 8 |
| `max_positions` | {"maximum":50,"minimum":1,"type":"integer"} | 5 |
| `max_hold_days` | {"maximum":1000,"minimum":1,"type":"integer"} | 120 |
| `slippage_bps` | {"maximum":500,"minimum":0,"type":"number"} | 10 |
| `buy_cost_bps` | {"maximum":500,"minimum":0,"type":"number"} | 10 |
| `sell_cost_bps` | {"maximum":500,"minimum":0,"type":"number"} | 10 |
| `execution_horizon` | {"enum":["swing","intraday"],"type":"string"} | "swing" |
| `square_off_time` | {"pattern":"^\\d{2}:\\d{2}$","type":"string"} | "15:00" |
| `comparison_run_id` | {"anyOf":[{"pattern":"^[0-9a-f]{12}(?:_[a-z0-9]+)?$","type":"string"},{"type":"null"}]} | null |
| `minimum_warmup_sessions` | {"maximum":2500,"minimum":50,"type":"integer"} | 50 |
| `start` | {"format":"date","type":"string"} | Required |
| `end` | {"format":"date","type":"string"} | Required |
| `acknowledge_limitations` | {"type":"boolean"} | false |
| `borrow_cost_bps_year` | {"maximum":100000,"minimum":0,"type":"number"} | 0 |

### PaperConfig

Implementation: `core/portfolio/paper.py`.

| Field | Type / constraints | Default |
|---|---|---|
| `name` | {"maxLength":80,"minLength":1,"type":"string"} | "Swing paper portfolio" |
| `pattern` | {"enum":["vcp","blue_sky","multiyear","ipo"],"type":"string"} | "vcp" |
| `capital` | {"maximum":10000000000.0,"minimum":1000,"type":"number"} | Required |
| `base_days` | {"maximum":250,"minimum":5,"type":"integer"} | 25 |
| `max_depth_pct` | {"exclusiveMinimum":0,"maximum":80,"type":"number"} | 30 |
| `volume_multiple` | {"maximum":10,"minimum":0.1,"type":"number"} | 1.5 |
| `sma_days` | {"maximum":250,"minimum":5,"type":"integer"} | 50 |
| `require_long_trend` | {"type":"boolean"} | false |
| `require_rising_long_trend` | {"type":"boolean"} | false |
| `min_rs_rating` | {"maximum":100,"minimum":0,"type":"number"} | 0 |
| `candidate_rank` | {"enum":["alphabetical","rs_126","fundamental_score"],"type":"string"} | "alphabetical" |
| `min_turnover` | {"maximum":1000000000000.0,"minimum":0,"type":"number"} | 50000000 |
| `vcp_window_days` | {"maximum":60,"minimum":3,"type":"integer"} | 10 |
| `vcp_volume_multiple` | {"exclusiveMinimum":0,"maximum":1,"type":"number"} | 0.8 |
| `blue_sky_lookback_days` | {"maximum":5000,"minimum":50,"type":"integer"} | 5000 |
| `multiyear_base_days` | {"maximum":2500,"minimum":252,"type":"integer"} | 260 |
| `multiyear_max_depth_pct` | {"exclusiveMinimum":0,"maximum":90,"type":"number"} | 50 |
| `entry_mode` | {"const":"next_open","type":"string"} | "next_open" |
| `risk_pct` | {"exclusiveMinimum":0,"maximum":5,"type":"number"} | 1.5 |
| `stop_pct` | {"exclusiveMinimum":0,"maximum":50,"type":"number"} | 8 |
| `winner_exit` | {"enum":["trail_50d","trail_30w","take_8","take_15","take_25"],"type":"string"} | "trail_50d" |
| `skip_weak_markets` | {"type":"boolean"} | false |
| `sector_filter` | {"enum":["off","trend","trend_rs"],"type":"string"} | "off" |
| `market_breadth_pct` | {"maximum":100,"minimum":0,"type":"number"} | 40 |
| `market_min_coverage_pct` | {"exclusiveMinimum":0,"maximum":100,"type":"number"} | 80 |
| `ipo_max_age_days` | {"maximum":3653,"minimum":1,"type":"integer"} | 730 |
| `breakeven_r` | {"maximum":10,"minimum":0.1,"type":"number"} | 1 |
| `trail_pct` | {"exclusiveMinimum":0,"maximum":50,"type":"number"} | 8 |
| `max_positions` | {"maximum":50,"minimum":1,"type":"integer"} | 5 |
| `max_hold_days` | {"maximum":1000,"minimum":1,"type":"integer"} | 120 |
| `slippage_bps` | {"exclusiveMinimum":0,"maximum":500,"type":"number"} | 10 |
| `buy_cost_bps` | {"exclusiveMinimum":0,"maximum":500,"type":"number"} | 10 |
| `sell_cost_bps` | {"exclusiveMinimum":0,"maximum":500,"type":"number"} | 10 |
| `sector_observe_only` | {"type":"boolean"} | true |
| `auto_run` | {"type":"boolean"} | false |
| `run_hour` | {"maximum":23,"minimum":16,"type":"integer"} | 16 |
| `run_minute` | {"maximum":59,"minimum":0,"type":"integer"} | 15 |
| `acknowledge_limitations` | {"type":"boolean"} | false |

### MomentumConfig

Implementation: `core/research/momentum.py`.

| Field | Type / constraints | Default |
|---|---|---|
| `strategy_id` | {"const":"intraday_momentum","type":"string"} | "intraday_momentum" |
| `name` | {"maxLength":80,"minLength":1,"type":"string"} | "Opening-range momentum" |
| `start` | {"format":"date","type":"string"} | Required |
| `end` | {"format":"date","type":"string"} | Required |
| `capital` | {"maximum":10000000000.0,"minimum":1000,"type":"number"} | 1000000 |
| `direction` | {"enum":["both","long","short"],"type":"string"} | "both" |
| `execution_mode` | {"enum":["follow","reverse"],"type":"string"} | "follow" |
| `exclude_symbols` | {"items":{"type":"string"},"maxItems":50,"type":"array"} | null |
| `exclude_stock_sessions` | {"items":{"type":"string"},"maxItems":100,"type":"array"} | null |
| `opening_minutes` | {"enum":[5,10,15,30],"type":"integer"} | 5 |
| `confirmation_minutes` | {"enum":[5,10,15,30,60],"type":"integer"} | 5 |
| `volume_lookback` | {"maximum":50,"minimum":5,"type":"integer"} | 14 |
| `min_relative_volume` | {"maximum":20,"minimum":0,"type":"number"} | 1.5 |
| `liquidity_days` | {"maximum":50,"minimum":5,"type":"integer"} | 20 |
| `min_turnover` | {"maximum":1000000000000.0,"minimum":0,"type":"number"} | 50000000 |
| `liquid_universe_size` | {"maximum":500,"minimum":1,"type":"integer"} | 50 |
| `atr_days` | {"maximum":50,"minimum":5,"type":"integer"} | 14 |
| `min_atr_pct` | {"maximum":20,"minimum":0,"type":"number"} | 1 |
| `stop_atr` | {"exclusiveMinimum":0,"maximum":5,"type":"number"} | 0.5 |
| `target_r` | {"maximum":20,"minimum":0,"type":"number"} | 0 |
| `risk_pct` | {"exclusiveMinimum":0,"maximum":5,"type":"number"} | 0.25 |
| `max_positions` | {"maximum":50,"minimum":1,"type":"integer"} | 5 |
| `last_entry_time` | {"pattern":"^\\d{2}:\\d{2}$","type":"string"} | "11:30" |
| `square_off_time` | {"pattern":"^\\d{2}:\\d{2}$","type":"string"} | "15:00" |
| `require_vwap` | {"type":"boolean"} | false |
| `breakout_buffer_atr` | {"maximum":2,"minimum":0,"type":"number"} | 0 |
| `min_close_strength` | {"maximum":1,"minimum":0,"type":"number"} | 0 |
| `min_confirmation_body_atr` | {"maximum":2,"minimum":0,"type":"number"} | 0 |
| `breakeven_after_r` | {"maximum":10,"minimum":0,"type":"number"} | 0 |
| `indicator_filter` | {"enum":["none","ema","macd","ema_macd"],"type":"string"} | "none" |
| `indicator_minutes` | {"enum":[10,60],"type":"integer"} | 10 |
| `entry_pattern` | {"enum":["breakout","flag"],"type":"string"} | "breakout" |
| `stop_reference` | {"enum":["atr","pullback"],"type":"string"} | "atr" |
| `require_fundamentals` | {"type":"boolean"} | false |
| `fundamental_min_score` | {"maximum":100,"minimum":0,"type":"number"} | 60 |
| `fundamental_min_coverage_pct` | {"maximum":100,"minimum":0,"type":"number"} | 80 |
| `fundamental_max_age_days` | {"maximum":730,"minimum":1,"type":"integer"} | 180 |
| `comparison_run_id` | {"anyOf":[{"pattern":"^[0-9a-f]{12}$","type":"string"},{"type":"null"}]} | null |
| `slippage_bps` | {"maximum":500,"minimum":0,"type":"number"} | 10 |
| `buy_cost_bps` | {"maximum":500,"minimum":0,"type":"number"} | 10 |
| `sell_cost_bps` | {"maximum":500,"minimum":0,"type":"number"} | 10 |
| `acknowledge_limitations` | {"type":"boolean"} | false |

### ScalpingConfig

Implementation: `core/research/scalping.py`.

| Field | Type / constraints | Default |
|---|---|---|
| `strategy_id` | {"const":"scalping","type":"string"} | "scalping" |
| `name` | {"maxLength":80,"minLength":1,"type":"string"} | "EMA pullback scalping" |
| `capital` | {"maximum":10000000000.0,"minimum":1000,"type":"number"} | 1000000 |
| `direction` | {"enum":["both","long","short"],"type":"string"} | "both" |
| `entry_filter` | {"enum":["candles","ema","ema_vwap"],"type":"string"} | "ema" |
| `trend_fast` | {"maximum":50,"minimum":2,"type":"integer"} | 9 |
| `trend_slow` | {"maximum":100,"minimum":3,"type":"integer"} | 20 |
| `pullback_ema` | {"maximum":50,"minimum":2,"type":"integer"} | 9 |
| `pullback_bars` | {"maximum":5,"minimum":1,"type":"integer"} | 2 |
| `ema_touch_bps` | {"maximum":100,"minimum":0,"type":"number"} | 5 |
| `entry_buffer_bps` | {"maximum":100,"minimum":0,"type":"number"} | 1 |
| `min_stop_pct` | {"exclusiveMinimum":0,"maximum":5,"type":"number"} | 0.05 |
| `max_stop_pct` | {"exclusiveMinimum":0,"maximum":10,"type":"number"} | 0.5 |
| `liquidity_days` | {"maximum":50,"minimum":5,"type":"integer"} | 20 |
| `min_turnover` | {"maximum":1000000000000.0,"minimum":0,"type":"number"} | 50000000 |
| `liquid_universe_size` | {"maximum":100,"minimum":1,"type":"integer"} | 20 |
| `risk_pct` | {"exclusiveMinimum":0,"maximum":5,"type":"number"} | 0.1 |
| `max_positions` | {"maximum":20,"minimum":1,"type":"integer"} | 3 |
| `target_r` | {"exclusiveMinimum":0,"maximum":10,"type":"number"} | 1.5 |
| `max_holding_minutes` | {"maximum":120,"minimum":1,"type":"integer"} | 15 |
| `cooldown_minutes` | {"maximum":120,"minimum":1,"type":"integer"} | 5 |
| `max_trades_per_symbol` | {"maximum":20,"minimum":1,"type":"integer"} | 3 |
| `daily_loss_pct` | {"exclusiveMinimum":0,"maximum":20,"type":"number"} | 1 |
| `participation_pct` | {"exclusiveMinimum":0,"maximum":10,"type":"number"} | 1 |
| `first_entry_time` | {"pattern":"^\\d{2}:\\d{2}$","type":"string"} | "09:45" |
| `last_entry_time` | {"pattern":"^\\d{2}:\\d{2}$","type":"string"} | "14:30" |
| `square_off_time` | {"pattern":"^\\d{2}:\\d{2}$","type":"string"} | "15:15" |
| `slippage_bps` | {"maximum":500,"minimum":0,"type":"number"} | 10 |
| `buy_cost_bps` | {"maximum":500,"minimum":0,"type":"number"} | 10 |
| `sell_cost_bps` | {"maximum":500,"minimum":0,"type":"number"} | 10 |
| `acknowledge_limitations` | {"type":"boolean"} | false |
| `start` | {"format":"date","type":"string"} | Required |
| `end` | {"format":"date","type":"string"} | Required |
| `comparison_run_id` | {"anyOf":[{"pattern":"^[0-9a-f]{12}$","type":"string"},{"type":"null"}]} | null |

### ScalpingPaperConfig

Implementation: `core/portfolio/scalping_paper.py`.

| Field | Type / constraints | Default |
|---|---|---|
| `strategy_id` | {"const":"scalping","type":"string"} | "scalping" |
| `name` | {"maxLength":80,"minLength":1,"type":"string"} | "Scalping paper portfolio" |
| `capital` | {"maximum":10000000000.0,"minimum":1000,"type":"number"} | Required |
| `direction` | {"enum":["both","long","short"],"type":"string"} | "both" |
| `entry_filter` | {"enum":["candles","ema","ema_vwap"],"type":"string"} | "ema" |
| `trend_fast` | {"maximum":50,"minimum":2,"type":"integer"} | 9 |
| `trend_slow` | {"maximum":100,"minimum":3,"type":"integer"} | 20 |
| `pullback_ema` | {"maximum":50,"minimum":2,"type":"integer"} | 9 |
| `pullback_bars` | {"maximum":5,"minimum":1,"type":"integer"} | 2 |
| `ema_touch_bps` | {"maximum":100,"minimum":0,"type":"number"} | 5 |
| `entry_buffer_bps` | {"maximum":100,"minimum":0,"type":"number"} | 1 |
| `min_stop_pct` | {"exclusiveMinimum":0,"maximum":5,"type":"number"} | 0.05 |
| `max_stop_pct` | {"exclusiveMinimum":0,"maximum":10,"type":"number"} | 0.5 |
| `liquidity_days` | {"maximum":50,"minimum":5,"type":"integer"} | 20 |
| `min_turnover` | {"maximum":1000000000000.0,"minimum":0,"type":"number"} | 50000000 |
| `liquid_universe_size` | {"maximum":100,"minimum":1,"type":"integer"} | 20 |
| `risk_pct` | {"exclusiveMinimum":0,"maximum":5,"type":"number"} | 0.1 |
| `max_positions` | {"maximum":20,"minimum":1,"type":"integer"} | 3 |
| `target_r` | {"exclusiveMinimum":0,"maximum":10,"type":"number"} | 1.5 |
| `max_holding_minutes` | {"maximum":120,"minimum":1,"type":"integer"} | 15 |
| `cooldown_minutes` | {"maximum":120,"minimum":1,"type":"integer"} | 5 |
| `max_trades_per_symbol` | {"maximum":20,"minimum":1,"type":"integer"} | 3 |
| `daily_loss_pct` | {"exclusiveMinimum":0,"maximum":20,"type":"number"} | 1 |
| `participation_pct` | {"exclusiveMinimum":0,"maximum":10,"type":"number"} | 1 |
| `first_entry_time` | {"pattern":"^\\d{2}:\\d{2}$","type":"string"} | "09:45" |
| `last_entry_time` | {"pattern":"^\\d{2}:\\d{2}$","type":"string"} | "14:30" |
| `square_off_time` | {"pattern":"^\\d{2}:\\d{2}$","type":"string"} | "15:15" |
| `slippage_bps` | {"exclusiveMinimum":0,"maximum":500,"type":"number"} | 10 |
| `buy_cost_bps` | {"exclusiveMinimum":0,"maximum":500,"type":"number"} | 10 |
| `sell_cost_bps` | {"exclusiveMinimum":0,"maximum":500,"type":"number"} | 10 |
| `acknowledge_limitations` | {"type":"boolean"} | false |
| `max_spread_bps` | {"exclusiveMinimum":0,"maximum":500,"type":"number"} | 15 |
| `quote_max_age_seconds` | {"maximum":15,"minimum":1,"type":"integer"} | 3 |
| `max_entry_delay_seconds` | {"maximum":30,"minimum":2,"type":"integer"} | 8 |
| `auto_run` | {"type":"boolean"} | false |

### BuyScreen

Implementation: `core/research/fundamentals.py`.

| Field | Type / constraints | Default |
|---|---|---|
| `min_score` | {"maximum":100,"minimum":0,"type":"number"} | 60 |
| `min_coverage_pct` | {"maximum":100,"minimum":0,"type":"number"} | 80 |
| `max_age_days` | {"maximum":730,"minimum":1,"type":"integer"} | 180 |

### ImportInput

Implementation: `core/research/company_review.py`.

| Field | Type / constraints | Default |
|---|---|---|
| `fundamentals` | {"items":{"$ref":"#/$defs/FundamentalInput"},"maxItems":500,"type":"array"} | null |
| `articles` | {"items":{"$ref":"#/$defs/Article"},"maxItems":100,"type":"array"} | null |

### ReviewRequest

Implementation: `core/research/company_review.py`.

| Field | Type / constraints | Default |
|---|---|---|
| `isin` | {"pattern":"^IN[A-Z0-9]{10}$","type":"string"} | Required |
| `use_llm` | {"type":"boolean"} | false |
| `disposition` | {"enum":["watch","would_take","would_skip","undecided"],"type":"string"} | "undecided" |
| `thesis` | {"maxLength":2000,"type":"string"} | "" |

### AutoResearchRequest

Implementation: `core/research/company_review.py`.

| Field | Type / constraints | Default |
|---|---|---|
| `isin` | {"pattern":"^IN[A-Z0-9]{10}$","type":"string"} | Required |
| `disposition` | {"enum":["watch","would_take","would_skip","undecided"],"type":"string"} | "undecided" |
| `thesis` | {"maxLength":2000,"type":"string"} | "" |
| `technical_config` | {"anyOf":[{"$ref":"#/$defs/TradingConfig"},{"type":"null"}]} | null |


<a id="screen-and-backtest-parameters"></a>

## Screen and backtest configuration guide

This guide describes the current implementation in this repository, as inspected on 4 October 2026. It explains the fields in **Add a new screen** and **Backtests → New backtest**, including defaults, accepted values, formulas and interactions. Examples illustrate the software's behavior; they are not trading recommendations.

### 1. What you are configuring

A **screen** is a reusable set of stock qualification filters. It stores a name, a pattern and schema-defined filter values. Plain screens store qualification filters. Saved strategy presets may also store validated trading_defaults, comparison warmup, source_run_id and description; their pattern/filter values must agree.

A **backtest** combines those filters with a test period and portfolio execution assumptions. Selecting a screen copies its pattern and filter values into the form. You can change them for that experiment without changing the saved screen. Changing the screen selection replaces the filter fields, so select the screen before making individual adjustments.

The engine is long-only and uses daily OHLCV candles: open, high, low, close and volume. All symbols share one cash balance. A session means an available daily candle, not a calendar day. A 50-session average is therefore different from 50 calendar days.

#### Units and conventions

| Unit | Meaning | Example |
|---|---|---|
| Sessions | Daily observations for a symbol | 10 sessions is usually about two trading weeks. |
| Percent (`pct`) | Enter a percentage number, not a decimal fraction | Enter `8` for 8%. |
| Multiple | A ratio to a baseline | `1.5` means 150% of the baseline. |
| Rupees | Absolute INR amount | `50000000` = ₹5 crore. |
| Basis points (`bps`) | 1 bps = 0.01%; 100 bps = 1% | `10` bps = 0.1% per side. |
| R | Initial entry-to-stop price risk | Entry ₹100 and stop ₹92 give 1 R = ₹8 per share. |

All listed range endpoints are inclusive unless explicitly written as `> 0`. Session/count parameters must be integers. Numeric configuration values must be finite, and unknown API fields are rejected.

### 2. Configure a screen

#### Screen name — `name`

- **New-screen UI value:** `My screen`. **API:** required, 1–80 characters.
- Use a name that identifies the assumptions, such as `VCP volume 1.5 RS 80`.
- The UI trims leading/trailing whitespace before saving. The name does not affect signals.
- Saving the exact same name again replaces the screen with that name-derived ID. The server retains the latest 100 saved screens. `id` and `created_at` are generated metadata, not inputs.

#### Base screen — `pattern`

- **New-screen UI/API default:** `vcp`.
- **Choices:** `vcp`, `blue_sky`, `multiyear`, `ipo`.
- This chooses the pattern predicate. All four require the common trend, turnover and signal-volume rules described below.

| Pattern | Exact qualification in this engine |
|---|---|
| VCP — `vcp` | Three consecutive prior windows must show strictly declining normalized price ranges and strictly declining average volumes. The final window must satisfy the volume dry-up limit. The signal close must exceed the final window's high. |
| Blue sky — `blue_sky` | The signal close must exceed the highest prior high in the available history, limited by the configured lookback cap. There is no additional base-depth or contraction test. |
| Multi-year breakouts — `multiyear` | The signal close must exceed the high of the configured long base, and that base must satisfy the multiyear depth limit. |
| IPO base — `ipo` | The signal close must exceed the configured short base's high, and that base must satisfy the short-base depth limit. The current engine does **not** verify listing age or that this is the first base. |

The API also accepts legacy `breakout` for backtests, but the screen-saving API and screen dropdown do not. Its filter predicate uses the short-base rules like IPO; its execution behavior differs as explained later.

#### Filter applicability

All schema-defined filters remain visible and are saved even when the selected pattern does not use them. An inactive field does not add a condition just because you entered a value.

| Parameter | VCP | Blue sky | Multi-year | IPO / legacy breakout |
|---|---|---|---|---|
| `base_days` | Pivot fill calculation only | No | No | Signal base and pivot |
| `max_depth_pct` | No | No | No | Signal depth |
| `volume_multiple` | Yes | Yes | Yes | Yes |
| `sma_days` | Yes | Yes | Yes | Yes |
| `require_long_trend` | Yes | Yes | Yes | Yes |
| `require_rising_long_trend` | Yes | Yes | Yes | Yes |
| `min_rs_rating` | Backtest entry filter | Backtest entry filter | Backtest entry filter | Backtest entry filter |
| `min_turnover` | Yes | Yes | Yes | Yes |
| `vcp_window_days` | Yes | No | No | No |
| `vcp_volume_multiple` | Yes | No | No | No |
| `blue_sky_lookback_days` | No | Signal and pivot | No | No |
| `multiyear_base_days` | No | No | Signal and pivot | No |
| `multiyear_max_depth_pct` | No | No | Signal depth | No |

`min_rs_rating` is stored with the screen, but is applied by the simulation after the pattern predicate qualifies. The pure pattern predicate itself does not compute RS.

#### Base length (sessions) — `base_days`

- **UI default:** `15`. **Screen API/backtest model default:** `25`. **Range:** 5–250.
- Uses exactly this many completed candles immediately before the signal candle for IPO and legacy breakout. It is a fixed measurement window, not an automatically detected base of at least this length.
- The base high is the maximum high, and the base low is the minimum low in that window. The signal candle is excluded.
- A larger window can raise the breakout ceiling and capture a wider/deeper structure; it need not simply reduce signals in every dataset.
- **VCP interaction:** VCP signal qualification uses `vcp_window_days`, but pivot entry uses `base_days` to calculate the execution pivot. With defaults, qualification checks a 10-session high while the pivot fill uses a 15-session high. `next_open` and `close` do not use this pivot fill calculation.

#### Maximum base depth (%) — `max_depth_pct`

- **UI default:** `35`. **API/model default:** `30`. **Range:** > 0 through 80.
- Used only for IPO and legacy breakout.
- Formula: `depth_pct = (base_high - base_low) / base_high × 100`.
- A base with high ₹100 and low ₹75 has 25% depth. It passes a limit of 30 and fails a limit of 20. Equality passes.
- Lower values require shallower bases. This parameter has no effect on VCP, Blue sky or Multi-year qualification.

#### Volume / prior 50-session mean — `volume_multiple`

- **UI default:** `1`. **API/model default:** `1.5`. **Range:** 0.1–10.
- All patterns require `signal_volume >= mean(prior 50 volumes) × volume_multiple`.
- The mean excludes the signal candle. With a prior mean of 100,000 shares, `1.5` requires at least 150,000 shares on the signal candle.
- Higher values strengthen volume confirmation; below 1 allows below-average signal volume. This is share volume, not rupee turnover.

#### Trend SMA (sessions) — `sma_days`

- **UI/API default:** `50`. **Range:** 5–250.
- Every pattern requires the signal close to be **strictly above** the simple mean of the latest `sma_days` closes, including the signal close.
- A close equal to the average fails. This is a price-above-average test; it does not require this average to slope upward.
- Increasing the length changes the trend horizon and can increase required warmup. At least 50 prior sessions are still needed for volume and turnover even if this value is less than 50.

#### Require price above 200-day SMA — `require_long_trend`

- **UI/API default:** `false`. **Values:** `true` / `false`.
- If enabled, the signal close must also be strictly above its 200-session SMA, including the signal close.
- This supplements `sma_days`; it does not replace it. Backtest preparation requires at least 200 prior sessions when enabled.

#### Require rising 200-day SMA (20 sessions) — `require_rising_long_trend`

- **UI/API default:** `false`. **Values:** `true` / `false`.
- Requires the current 200-session SMA to be strictly greater than its value 20 sessions earlier, **and** the signal close to be above the current 200-session SMA.
- Therefore enabling this also enforces the long-trend price test even if `require_long_trend` is unchecked.
- Requires 220 warmup sessions in backtest preparation. This is a comparison between two averages, not a requirement for an increase on every intervening session.

#### Minimum 126-session RS percentile — `min_rs_rating`

- **UI/API default:** `0`. **Range:** 0–100. `0` disables the threshold.
- Computes each eligible symbol's return on the signal date: `close_today / close_126_sessions_earlier - 1`.
- Converts those returns to percentile ranks among loaded, non-excluded symbols with a candle on that date and sufficient history. It is relative to this run's dataset, not a benchmark index and not a proprietary Banana rating.
- Higher values retain stronger relative performers. A threshold of `80` requires a percentile of at least 80; it does not require an 80% price return.
- Tied returns receive their average rank. A single eligible symbol receives percentile 0. Missing RS fails a positive threshold.
- Enabling a positive threshold requires at least 126 prior sessions. Changing the universe or exclusions can change the percentile even for identical stock prices.
- `candidate_rank` is separate: this field controls eligibility; candidate ranking controls which eligible symbols get scarce cash or position slots.

#### Minimum average turnover (₹) — `min_turnover`

- **UI/API default:** `50000000` (₹5 crore per session). **Range:** 0–1,000,000,000,000.
- All patterns require `mean(close × volume over prior 50 sessions) >= min_turnover`.
- The signal candle is excluded. This is a daily traded-value proxy based on close × volume, not actual intraday traded value or a volume participation limit.
- Higher values demand more liquidity. `0` effectively removes this threshold for ordinary nonnegative data.

#### VCP contraction window (sessions) — `vcp_window_days`

- **UI/API default:** `10`. **Range:** 3–60. **Applies:** VCP only.
- Splits the `3 × vcp_window_days` candles immediately before the signal into three consecutive equal windows, oldest to newest.
- For each window, range is `(highest_high - lowest_low) / highest_high`; volume is the mean share volume.
- Requires `range_old > range_middle > range_recent` and `volume_old > volume_middle > volume_recent`. Equality fails either contraction sequence.
- The signal close must exceed the most recent window's highest high. Larger windows examine contractions over a longer period and increase warmup if `3 × window` exceeds the other requirements.

#### VCP final volume / 50-session mean — `vcp_volume_multiple`

- **UI default:** `0.9`. **API/model default:** `0.8`. **Range:** > 0 through 1. **Applies:** VCP only.
- Requires `mean_volume_recent_window <= mean_volume_prior_50 × vcp_volume_multiple`.
- For a prior 50-session mean of 100,000, `0.9` permits a final contraction-window mean up to 90,000; `0.5` permits up to 50,000.
- Lower values require stronger volume dry-up. This tests the prior contraction window; `volume_multiple` independently tests the breakout candle's volume expansion.

#### Blue-sky prior high lookback (sessions) — `blue_sky_lookback_days`

- **UI/API default:** `5000`. **Range:** 50–5000. **Applies:** Blue sky only.
- The signal close must be strictly above the highest high in the preceding `min(configured_lookback, available_prior_sessions)` candles.
- The setting is a cap, not a minimum history requirement. A symbol with 100 prior sessions and a cap of 5000 is compared with those 100 sessions.
- A larger value can include older resistance. A smaller value produces a rolling-high test. Even 5000 cannot establish a true lifetime high when the downloaded history is shorter than the listing's lifetime.
- The same lookback determines the Blue-sky pivot fill level. There is no enforced 252-session minimum in the predicate, despite the pattern registry's descriptive history label.

#### Multiyear base length (sessions) — `multiyear_base_days`

- **UI/API default:** `260`. **Range:** 252–2500. **Applies:** Multi-year only.
- Measures a fixed prior window of this length. The signal close must exceed its highest high, and its depth must pass `multiyear_max_depth_pct`.
- Also determines the pivot fill ceiling. Larger values extend the structure being measured and require more pre-test history. The engine does not independently detect how many years a base has existed.

#### Multiyear maximum base depth (%) — `multiyear_max_depth_pct`

- **UI/API default:** `50`. **Range:** > 0 through 90. **Applies:** Multi-year only.
- Uses the same high-to-low depth formula as `max_depth_pct`, over `multiyear_base_days`.
- Lower values demand shallower long bases. `max_depth_pct` does not add another depth condition for this pattern.

### 3. Data settings required before a backtest

Public Settings exposes only universe, default nifty50, with nifty50/nifty500/niftytotalmarket choices. The selection changes research membership, RS ranks, cash competition and breadth; it does not limit the full 750-stock rolling fetch. Internal legacy Settings start/end remain 2018-10-01/2026-10-01 with increasing <=3653-day validation for saved compatibility; these dates are not editable fetch controls.

Saving settings does not download candles. Refresh universe and Fetch prices & fundamentals; the latter requires a saved Upstox token (20-10,000 characters). It refreshes automatic daily last-calendar-year and five-minute last-ten-calendar-day windows, retaining older inputs. Existing cached research does not need a new token request.

Missing stock files halt preparation; insufficient pre-test indicator warmup is excluded and disclosed. Actual coverage differs from requested calendar dates, and holidays/suspensions/listings are not fabricated. Rolling history alone may be too short for a multi-year strategy.

### 4. Configure a backtest

Every filter in section 2 also appears in the backtest form and has the same meaning. The following fields complete the experiment.

#### Strategy — `strategy` (UI selector)

The current dropdown offers only **Swing Pattern** (`swing_patterns`). Intraday/scalping are planned. This selector is a UI control; `strategy` is not a field in `BacktestConfig` and is not submitted by its schema-based form reader. Do not include it in a direct backtest API payload.

#### Screen — `screen` (UI selector)

Defaults to **VCP**, unless opening a different built-in/saved screen or cloning a run. Built-in selector IDs are `builtin:vcp`, `builtin:blue_sky`, `builtin:multiyear`, `builtin:ipo`; saved screens use generated custom IDs.

This copies values into the form's actual `pattern` and filter fields. `screen` itself is not a `BacktestConfig` API field. The run records the copied configuration, rather than a live reference that follows later screen edits.

#### Run name — `name`

- **UI/model default:** `Breakout experiment`. **Range:** 1–80 characters.
- Identifies the run in reports. It has no effect on trading behavior. Use a name that makes comparisons recognizable.
- Adjust & rerun appends ` · revised`; the total name must still satisfy the length limit.

#### Test from / Test through — `start`, `end`

- **API:** both dates are required; `start < end`. **New UI run:** suggested from the downloaded safe window. Cloning preserves the run's dates.
- Both boundaries are inclusive for available candles. Earlier candles supply indicators and can provide the previous-session signal for an entry at the beginning of the test.
- This means a next-open/pivot trade on the first test session can originate from a signal just before `start`; warmup dates do not become reported portfolio sessions.
- Every symbol is liquidated at its last available candle within the interval, using that candle's close plus sell slippage/charges. A symbol whose history ends early can therefore exit before the requested `end`.
- Dates need not themselves be trading sessions, but there must be actual candles in the interval. The UI blocks an end beyond its coverage window; backend preparation also validates requested coverage.

#### Starting capital (₹) — `capital`

- **UI/model default:** `1000000` (₹10 lakh). **Range:** ₹1,000–₹10,000,000,000.
- Initial shared cash balance. Capital is not separately assigned to each stock.
- Position sizing uses portfolio equity at the session open; buying is constrained by remaining cash including buy charges. The model has no borrowing to fund an entry.
- Larger capital can change whole-share rounding and cash availability; it does not relax screen conditions.

#### Minimum comparison warmup (sessions) — `minimum_warmup_sessions`

- **UI/model default:** `50`. **Range:** 50–2500.
- Minimum number of a symbol's candles strictly before the test start. A symbol that fails is excluded for the entire run, rather than becoming eligible later in that run.
- Effective requirement is `max(minimum_warmup_sessions, required_warmup_for_rules)`:

| Rule | Required warmup component |
|---|---|
| Every pattern | At least 50 and `sma_days` |
| VCP | Also `3 × vcp_window_days` |
| IPO / legacy breakout | Also `base_days` |
| Multi-year | Also `multiyear_base_days` |
| Above 200-session SMA | Also 200 |
| Rising 200-session SMA | Also 220 |
| Positive RS threshold or RS candidate priority | Also 126 |
| Blue sky | No requirement to fill the full Blue-sky lookback cap |

For example, Multi-year with a 260-session base still needs 260 prior sessions even if this field says 50. VCP with 60-session windows needs at least 180.

The UI's safe-window suggestion uses an additional session buffer for the prior signal, and is calculated when opening the dialog. It is not recalculated for every subsequent filter edit; its calculation also does not explicitly include `3 × vcp_window_days`. Backend preparation enforces the actual configuration. Check exclusions and fetch more history or move the start if needed.

#### Entry price — `entry_mode`

- **UI/model default:** `pivot`. **Choices:** `pivot`, `close`, `next_open`.

| Choice | Signal timing and raw fill before costs |
|---|---|
| Pivot breakout — `pivot` | Requires a qualifying previous-session signal. On the following available symbol session, raw fill is `max(open, pivot)`, provided the high reaches that price. If not reached, the entry is skipped; there is no persistent pending order. |
| Close breakout — `close` | For the four current patterns, qualifies on today's completed candle and enters at today's close. This assumes execution at the very close used to confirm the signal. |
| Next session open — `next_open` | Requires a qualifying previous-session signal and fills at the following available symbol session's open. Useful when comparing with the paper engine's next-open timing. |

The pivot is the prior base high: `base_days` for VCP/IPO, `multiyear_base_days` for Multi-year, and capped prior history for Blue sky. Note the VCP signal-window/pivot-window difference in section 2.

For current-pattern `pivot` and `close` entries, initial protection, position aging and winner management start on the **next** available session. The entry-day low is not used to retroactively stop the position because daily candles cannot establish intraday ordering. Next-open entries can hit the initial stop on their entry day. All entry prices are then adjusted by buy slippage.

**Legacy `breakout`:** always uses previous-session qualification and next-open fills, irrespective of the stored `entry_mode`; its winner management uses the percentage fallback rather than the moving-average branches.

#### Simultaneous signal priority — `candidate_rank`

- **UI/model default:** `alphabetical`. **Choices:** `alphabetical`, `rs_126`.
- `alphabetical` considers symbols in sorted symbol order.
- `rs_126` considers the highest signal-date RS percentile first, then highest 126-session return, then symbol order. It requires 126-session warmup even if `min_rs_rating` is zero.
- Ranking matters when cash or `max_positions` prevents taking all candidates. It does not itself impose a minimum strength threshold.
- Ranking uses the completed signal date: today's date for current-pattern close entry; the previous available symbol session for next-open/pivot and legacy breakout. Missing RS sorts behind valid scores.

#### Risk per trade (%) — `risk_pct`

- **UI/model default:** `1.5`. **Range:** > 0 through 5.
- Sets the sizing budget to `equity_at_open × risk_pct / 100`, rather than allocating that percentage of capital to the purchase.
- Quantity is the smaller of the risk-limited and cash-limited whole-share counts, rounded down. Entries with fewer than one share are skipped.
- The sizer includes modeled fees and exit slippage in unit risk:

```text
buy_rate = buy_cost_bps / 10000
sell_rate = sell_cost_bps / 10000
slip = slippage_bps / 10000
unit_risk = fill - initial_stop + fill × buy_rate + initial_stop × (sell_rate + slip)
risk_quantity = floor(equity_at_open × risk_pct / 100 / unit_risk)
cash_quantity = floor(available_cash / (fill × (1 + buy_rate)))
quantity = max(0, min(risk_quantity, cash_quantity))
```

At equity ₹10 lakh, 1.5% gives ₹15,000 risk budget. With zero costs, fill ₹100 and stop ₹92, risk sizing gives 1,875 shares costing ₹187,500, subject to cash and capacity.

The budget is per position, not a portfolio-wide aggregate loss cap. Multiple positions can each consume a budget, and gaps can exceed the modeled stop loss. Within a session, candidates use the same open-equity basis but progressively reduced available cash; this also applies to the model's close entries.

#### Initial stop (%) — `stop_pct`

- **UI/model default:** `8`. **Range:** > 0 through 50.
- Initial stop is `slippage_adjusted_buy_fill × (1 - stop_pct / 100)`.
- Defines initial price risk for sizing and the R trigger. Wider stops generally reduce risk-limited quantity; tighter stops increase it, subject to available cash.
- For an existing protected position, an open at/below the stop exits at the open; otherwise a low at/below the stop exits at the stop. Sell slippage and charges then apply. The stop is a simulated trigger, not a guaranteed net exit price.

#### Winner exit — `winner_exit`

- **UI/model default:** `trail_50d`. **Choices:** `trail_50d`, `trail_30w`, `take_25`.
- Winner management begins only when the close reaches the `breakeven_r` threshold. Until then, initial protection and holding/end-of-data exits remain active.

| Choice | Implementation after the R trigger |
|---|---|
| 50-day trailing exit — `trail_50d` | Raises the stop to the maximum of the previous stop, cost-adjusted breakeven and current 50-session SMA. |
| 30-week trailing exit — `trail_30w` | Same, using a **150-daily-session SMA** as the 30-week approximation. It does not aggregate weekly candles. If unavailable, uses the percentage fallback. |
| Take profit at +25% — `take_25` | Exits at the close when that close is at least 25% above entry **and** the R trigger is satisfied. Before that, once the R trigger is satisfied, cost-adjusted breakeven and the percentage fallback can raise the stop. This is not an intraday limit order. |

Stops only rise; they do not fall with the moving average. Close-based stop updates become active next session. A take-profit exit uses the same close that meets its conditions, with sell costs applied.

#### Skip weak markets — `skip_weak_markets`

- **UI/model default:** `false`. **Values:** `true` / `false`.
- If enabled, new entries need sufficient signal-date market breadth as defined below. Existing positions keep their exit rules.
- This is a gate across the run's eligible stock datasets, not a test against an external index. Insufficient-data exclusions can change the breadth calculation.

#### Minimum market breadth (%) — `market_breadth_pct`

- **UI/model default:** `40`. **Range:** 0–100. Active only when `skip_weak_markets` is true.
- Breadth is `100 × eligible_symbols_above_200_session_SMA / eligible_symbols` on the signal date. Above means strictly above; equality does not count.
- Eligible symbols must have a candle on that date with index at least 200 in their dataset. The SMA includes that day's close.
- If 30 of 100 eligible symbols are above their averages, a 40% threshold blocks new entries; 40 of 100 passes.
- **Current fallback:** if there are no eligible symbols, the gate passes. Enabling the gate does not itself add a 200-session preparation requirement; early tests may therefore lack meaningful breadth. Supply sufficient history when relying on this filter.

#### Breakeven trigger (R) — `breakeven_r`

- **UI/model default:** `1`. **Range:** 0.1–10.
- Activates at `close >= entry × (1 + stop_pct / 100 × breakeven_r)`.
- With entry ₹100, stop 8% and `breakeven_r = 1`, the trigger is ₹108. At `2`, it is ₹116. The test uses the close, not the day's high.
- Cost-adjusted breakeven is `entry_cost_per_share / ((1 - sell_rate) × (1 - slip))`, so it covers the modeled buy charges and future sell costs. Gaps can still cause a loss.
- This threshold gates both breakeven and the chosen winner management. For example, stop 10% and trigger 3 R require +30%, so a `take_25` run cannot take profit merely upon reaching +25%.
- Trade-report R uses net P&L divided by initial quantity × entry-to-stop distance. That denominator excludes fees, unlike the sizing unit risk.

#### Trail below best close (%) — `trail_pct`

- **UI/model default:** `8`. **Range:** > 0 through 50.
- Fallback stop candidate: `best_close_since_entry × (1 - trail_pct / 100)`, applied only after the R trigger, along with breakeven and the existing stop.
- Used if the selected moving average is unavailable, for legacy breakout, and in `take_25` before its gated profit exit is reached.
- It is **not** an extra percentage trail continuously applied alongside an available 50/150-session SMA trail. Lower values tighten the fallback; higher values leave more room.
- The best-close baseline begins at the entry fill. For current-pattern pivot/close entry, entry-day management is skipped as described above.

#### Maximum open positions — `max_positions`

- **UI/model default:** `5`. **Range:** 1–50.
- Caps simultaneous holdings. When full, later qualifying candidates are skipped. No existing position is replaced to admit a stronger candidate, and the engine does not buy another lot of an already-held symbol.
- Open-time stop/time exits happen before entries and can release cash and slots. Intraday stop exits happen after the entry pass and cannot fund those entries. A symbol exited that day is not re-entered that day.
- This is not an equal-weight allocation rule or a maximum portfolio-risk percentage.

#### Maximum holding sessions — `max_hold_days`

- **UI/model default:** `120`. **Range:** 1–1000.
- Checked at the open: if stored age is at least the limit, the position exits at that open, unless a gap-stop reason takes precedence.
- Age increases during eligible position-management sessions with a candle for that symbol. It does not increase over weekends, missing candles, or the entry-day management skipped for current-pattern pivot/close fills.
- Consequently the calendar duration can exceed this number, and exit occurs at the next available open after the age threshold is accumulated.

#### Slippage per side (bps) — `slippage_bps`

- **Current UI/model default:** `10`. **Range:** 0–500.
- Buy fill is `raw_price × (1 + bps / 10000)`; sell fill is `raw_price × (1 - bps / 10000)`.
- At raw ₹100 and 10 bps, buy fill is ₹100.10 and sell fill is ₹99.90, before charges.
- Applies on every side, including stops, time exits, profit exits and end-of-data exits. It also affects sizing and breakeven.
- **Default distinction:** the UI explicitly sets buy/sell charges to zero but does not override slippage, so a fresh comparison run still has 10 bps slippage. For a deliberately cost-free comparison, explicitly set all three cost fields to zero.

#### All-in buy charges (bps) — `buy_cost_bps`

- **New UI default:** `0`. **Model/API default:** `10`. **Range:** 0–500.
- Buy charge is `slippage_adjusted_buy_fill × quantity × buy_cost_bps / 10000`.
- Deducted from cash in addition to purchase value; included in sizing and cost-adjusted breakeven. For ₹100,000 executed buy value, 10 bps adds ₹100.
- Enter a combined assumption for applicable fees/taxes. The engine does not itemize or verify historical broker/tax schedules.

#### All-in sell charges (bps) — `sell_cost_bps`

- **New UI default:** `0`. **Model/API default:** `10`. **Range:** 0–500.
- Sell charge is `slippage_adjusted_sell_fill × quantity × sell_cost_bps / 10000`.
- Deducted from sale proceeds and net trade P&L. Also affects sizing and breakeven. You can use a different rate from buys.
- Charges are proportional assumptions; minimum ticket charges, fee slabs and changing historical rates are not separately modeled.

#### Exploratory-backtest acknowledgement — `acknowledge_limitations`

- **UI/model initial value:** `false`. **Required to run:** `true`.
- The backend rejects a run without acknowledgement. It does not alter fills or filters.
- The recorded limitations include current-constituent survivorship bias, unverified corporate actions/calendar gaps/delisted history, local rather than verified market-wide RS, assumed costs, and no volume participation/circuit-limit/non-fill simulation.

### 5. Defaults at a glance

All four built-in screens currently copy the same filter defaults; the selected pattern determines which ones are active. Saved screens use their stored values, with missing older fields filled from built-in defaults. Adjust & rerun preserves explicit recorded values, including costs and dates.

| Parameter | Fresh UI value | API/model default if omitted |
|---|---|---|
| Screen `name` | `My screen` | Required in screen API |
| Backtest `name` | `Breakout experiment` | `Breakout experiment` |
| `pattern` | `vcp` | Screen API: `vcp`; backtest: legacy `breakout` |
| `base_days` | 15 | 25 |
| `max_depth_pct` | 35 | 30 |
| `volume_multiple` | 1 | 1.5 |
| `sma_days` | 50 | 50 |
| `require_long_trend` | false | false |
| `require_rising_long_trend` | false | false |
| `min_rs_rating` | 0 | 0 |
| `min_turnover` | 50,000,000 | 50,000,000 |
| `vcp_window_days` | 10 | 10 |
| `vcp_volume_multiple` | 0.9 | 0.8 |
| `blue_sky_lookback_days` | 5000 | 5000 |
| `multiyear_base_days` | 260 | 260 |
| `multiyear_max_depth_pct` | 50 | 50 |
| `capital` | 1,000,000 | 1,000,000 |
| `minimum_warmup_sessions` | 50 | 50 |
| Backtest `start`, `end` | Suggested safe window | Required |
| `entry_mode` | pivot | pivot |
| `candidate_rank` | fundamental_score (long Swing UI) | alphabetical |
| `risk_pct` | 1.5 | 1.5 |
| `stop_pct` | 8 | 8 |
| `winner_exit` | trail_50d | trail_50d |
| `skip_weak_markets` | false | false |
| `market_breadth_pct` | 40 | 40 |
| `breakeven_r` | 1 | 1 |
| `trail_pct` | 8 | 8 |
| `max_positions` | 5 | 5 |
| `max_hold_days` | 120 | 120 |
| `slippage_bps` | 10 | 10 |
| `buy_cost_bps` | 0 | 10 |
| `sell_cost_bps` | 0 | 10 |
| `acknowledge_limitations` | false; must check | false; must supply true |

The API accepts only `pattern` and the actual configuration fields, not the UI-only `screen` or `strategy` selectors. Fields with defaults can be omitted by direct API callers; the UI normally submits explicit values. Screen name is required, and backtest dates plus a true acknowledgement must be supplied.

### 6. Practical configuration sequence

1. Select the universe in Settings, request enough daily history before the planned test, refresh the universe and fetch candles.
2. Create/select a screen. Choose its pattern first, then adjust its applicable filters. Save it with a descriptive name if you want to reuse it.
3. Open New backtest and review dates, capital and warmup. The selected screen's filters are copied into this run.
4. Choose entry mode and candidate priority. Configure initial risk/stop, winner management, breadth gate, capacity and holding limit.
5. Enter explicit slippage and both charge assumptions. Check the acknowledgement and run.
6. Inspect exclusions, skipped entries, modeled costs, drawdown and individual trades alongside return. The skipped-entry count includes several causes (RS, breadth, capacity, pivot not reached and insufficient cash), not only cash/position limits.
7. Use Adjust & rerun to vary an assumption while retaining the previous experiment. The application records configuration, universe, report and frozen input data; later data updates do not rewrite old runs. There is no automatic walk-forward optimizer.

### 7. Implementation references

These are repository-relative references so this file remains portable:

- [Configuration models and validation](core/research/config.py)
- [Saved-screen API model and submission endpoints](dashboard/api/main.py)
- [UI fields, built-in presets and new-run defaults](dashboard/web/app.js)
- [Pattern predicates and indicator calculations](strategies/swing_patterns/patterns/signals.py)
- [Warmup, dataset preparation, entries, ranking, breadth and exits](core/research/backtest.py)
- [Position sizing](core/risk/position_sizer.py)
- [Simulated fills, fees and slippage](core/execution/paper.py)

Update documentation only when explicitly requested. Current schema tables take precedence over dated default examples.

<a id="scalping-research"></a>

## Scalping research

Scalping supports historical research and a separate forward paper portfolio.
Open **Scalping → Scalping backtest** for research.
Daily history supplies prior turnover selection; Upstox one-minute history supplies
signals and simulated fills. The existing five-minute cache remains separate.
**Forward scalping paper** uses completed candles for signals and fresh streamed
bid/ask quotes for simulated fills. Live broker orders are not implemented.

### First run

1. Fetch daily history in Market data and save a valid Upstox token in Settings.
2. Choose a short completed-session window, initially one week, and a small scan size.
3. Set capital, direction, entry confirmation and explicit costs.
4. Select **Check minute coverage** to estimate sessions and candles, including warmup.
5. Select **Fetch missing & backtest**. Inspect Jobs & logs, then open the report.
6. Select a trade to see its frozen one-minute candles, stop, target and indicator lines.
7. **Compare confirmations** runs candles only, EMA confirmation and EMA + VWAP
   on identical frozen candles and cost settings. Every success or failure is retained.
   **Adjust & rerun** also uses the selected run's frozen reference.

### Declared baseline

These are editable research hypotheses, not optimized settings or evidence of an edge.

| Component | Default and exact rule |
|---|---|
| Selection | Up to 20 stocks ranked by the previous 20 sessions' mean close × volume, at least ₹5 crore average turnover. Current universe membership remains survivorship biased. |
| Trend | Five-minute EMA9 above EMA20, fast EMA rising, completed five-minute close above the fast EMA for longs. Reverse all comparisons for shorts. |
| Warmup | SMA-seeded EMAs; fetch at least five slow-EMA periods of prior-session complete five-minute bars. Each regular session has 375 one-minute bars. Corporate-action crossings halt pending minute price-basis verification. |
| Pullback | A directional one-minute candle followed by exactly two immediately preceding adverse candles. At least one adverse candle's range overlaps EMA9, allowing 5 bps tolerance. |
| Trigger | A directional completed one-minute close beyond the adverse candles' high/low plus 1 bp buffer, and back on the trend side of the one-minute EMA. |
| Entry | Next one-minute bar's open, with adverse slippage. Signals never use incomplete five-minute candles or future volume. |
| Optional VWAP | EMA + VWAP requires signal close above/below cumulative session typical-price × volume VWAP. |
| Candle comparison | Use consecutive completed five-minute closes for trend direction; retain the directional candle/pullback/breakout rules, without EMA touch/alignment or VWAP gates. |
| Stop | Pullback low/high with 1 bp outward buffer. Reject entries whose slipped fill-to-stop distance is outside 0.05–0.5%. |
| Target / time | 1.5 initial price-risk R target; exit after 15 minutes or at 15:15 IST, whichever occurs first. Stops/targets may exit sooner. |
| Risk | 0.1% marked equity per trade, including modeled stop-exit costs; maximum three concurrent positions. |
| Re-entry | Five-minute cooldown after exit; up to three trades per symbol per session. No same-bar re-entry after an intrabar exit. |
| Daily loss pause | At 1% loss from session-start equity, latch a pause on new entries. Existing protective exits continue; gaps can exceed the threshold. |
| Liquidity proxy | Quantity at most 1% of the completed signal-minute volume. This does not establish executable liquidity at the next open. |
| Hours | Entries from 09:45 through 14:30 IST; mandatory exit at the 15:15 bar open. Special sessions are skipped. |
| Costs | Initially 10 bps slippage per side and 10 bps buy/sell charges. Supply assumptions appropriate to the experiment; these are not a verified broker/tax schedule. |

### Accounting and timing

One shared cash pool is processed minute by minute, in prior-turnover candidate order
(symbol order breaks ties). Each long or short reserves its full entry notional plus
entry fee. Short-sale proceeds never increase buying power. Open-price exits can fund
open-price entries; intrabar stop/target proceeds can only fund subsequent minutes.
Capital is reused after exits; leverage is unavailable.

Stop gaps fill at the open. Favorable target gaps fill at the open. Within a candle,
stop takes precedence when both stop and target are touched. New positions' stops
and targets apply during the entry minute. Time/cutoff exits use the bar open before
the candle's high/low is examined. Stops stay fixed for this first setup.

Position size is limited by modeled stop risk, available cash, marked equity divided
by the position cap, and the volume proxy. Trade R uses initial fill-to-price-stop
risk; net P&L includes both transaction fees and slipped entry/exit prices.

Drawdown tracks minute-close marked equity, including entry fees but excluding
estimated liquidation costs and intraminute extrema. The daily equity curve shows
session-end cash. Reports include long/short and morning/midday/afternoon attribution,
holding time, turnover, cost impact and daily loss pauses. Earlier/later segments are
diagnostics on a known sample, not an untouched holdout.

### Reproducibility and boundaries

Saved runs freeze daily candles, one-minute sessions, universe, configuration,
input hashes and source provenance. Replays fail on missing/changed inputs rather
than fetching substitutes. Increasing scan size or warmup can require unavailable
frozen stock-sessions and therefore fail deliberately. Trade charts use the frozen
session and show indicator values known at each candle's open; the signal records
its actual completed-close indicators separately.

One-minute OHLCV cannot establish seconds-level fill quality, spreads, queue priority,
intraminute ordering, circuit restrictions or short-sale eligibility. Minute corporate
action adjustments and historical membership remain unverified. An adverse cost
stress and a genuinely untouched date window are required before judging an edge.

### Forward paper workflow

1. Load daily history and save an Upstox access token in Settings.
2. On **Scalping**, select **Create paper portfolio**, enter allocated capital,
   choose direction and confirmations, and acknowledge the simulation assumptions.
   Capital has no default and remains fixed after creation. The captured universe
   also remains fixed. No portfolio or runner is created automatically.
3. Select **Start quote runner**. The separate Python process waits for the first
   eligible weekday after creation, then freezes prior-session selection and minute
   warmup. Refresh daily coverage before each new session; stale daily history blocks
   preparation. A valid token and Upstox full-feed permission are required.
4. **Pause entries** takes effect immediately while protective exits continue.
   **Flatten & stop runner** requests liquidation on fresh regular-session quotes
   before the process exits. If markets are closed or the feed is unavailable, open
   positions remain recorded and the runner reports that it needs attention.
5. Inspect open positions, closed trade portions and observed simulated fills.
   **Export full ledger** includes every fill's book, signal, context hash and costs.
6. Configuration changes apply when the next session context is frozen. Existing
   positions keep their recorded stop, target and holding/cutoff rules. Exit costs use
   the current session's frozen assumptions. Optional automatic startup launches this
   runner when the dashboard starts; the default is off.

The runner uses the Upstox V3 binary protobuf full feed and subscribes to selected
equities plus held instruments. Initial snapshots cannot fill trades. NSE equity
`NORMAL_OPEN` status and a valid, uncrossed book are required. Quotes must be no more
than three seconds old by default and cannot be future-dated. Closed-market and stale
quotes cannot enter, mark or liquidate positions.

Completed one-minute REST candles, requested in background threads after a two-second
publication grace, drive the same candle/EMA/VWAP rules as research. Feed OHLC and
sampled ticks do not construct signal candles. Full regular-session prefixes must be
continuous from 09:15; revised processed candles latch an entry block. Default entries
expire eight seconds after signal close. REST/feed delays skip opportunities rather
than recording historical or next-open fills after the fact. This latency makes paper
results different from the idealized research next-open model.

Long entries use observed ask and exits use bid; shorts use the reverse. Adverse
configured slippage and positive charges apply to both sides. Each fill is capped by
the displayed quantity at that side of the book. Entry sizing also applies the completed
signal-minute volume cap, stop risk, cash and position limits. Both directions reserve
full notional plus fees. An exit may be partial; once triggered, its intent remains
latched until the remaining shares can exit on subsequent fresh quotes. Repeated depth
updates do not prove replenishment or executable liquidity, and queue position,
circuits, fees and short eligibility remain unverified.

Atomic portfolio replacement commits cash, positions, trades, fills and the fill
watermark together. Cross-process locks protect controls and portfolio mutations and
permit one runner per data directory. Restart/reconnect discards pending entries and
retains exposure and committed fills. Previous-day exposure, or exposure with a broken
session context, enters recovery liquidation before new signals/history preparation.
No missed historical exits are fabricated. A holiday, suspended symbol, feed outage or
missing depth can therefore leave a paper position open beyond its intended cutoff.

Marks checkpoint every ten seconds and may become stale during outages; the dashboard
reports stale held symbols. Paper drawdown is based on processed quote marks/checkpoints,
not all exchange ticks. This implementation has synthetic transport/recovery tests;
an authenticated market-hours observation run and untouched research validation remain
necessary before judging execution quality or an edge.

Implementation: `core/research/scalping.py`, parameterized
`core/research/intraday_data.py`, API endpoints and shared dashboard reporting.
Streaming implementation: `core/market_data/upstox_stream.py`,
`core/portfolio/scalping_paper.py`, `scalping_runner.py`, `scalping_control.py`
and `locking.py`. Tests: `tests/test_scalping.py`, `tests/test_scalping_paper.py`
and `tests/test_scalping.cjs`.

<a id="momentum-research"></a>

## Intraday momentum baseline

Implemented 8 October 2026. This is research on NSE cash equities, with real Upstox five-minute history. Momentum paper/streaming/live execution remains pending.

### Research comparison

There is no defensible universal “best” momentum strategy across markets, time horizons and costs. The first choice is a transparent, testable baseline suitable for this project's intraday strategy slot.

| Candidate | Evidence and fit | Decision |
|---|---|---|
| Opening-range breakout with stocks-in-play relative volume | [Zarattini, Barbon and Aziz's original paper](https://concretumgroup.com/wp-content/uploads/2026/02/A-Profitable-Day-Trading-Strategy-For-The-U.S.-Equity-Market.pdf) studies US stocks and compares ordinary ORB against volume-selected ORB. The stock-selection/volume filter matters materially. | Implement an India adaptation, then validate locally. Published returns do not transfer to this universe. |
| Practical ORB replication | [QuantConnect's own implementation](https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/p1) provides explicit same-opening-interval relative volume, prior ATR, rank selection and capital limits. | Reusable baseline structure, with conservative completed-close/next-open entries. |
| Time-series momentum | [AQR's original research](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum) supports longer-horizon own-return momentum across futures/forwards. | Useful research alternative; does not directly establish an intraday NSE equity strategy. |
| Data capability | [Upstox V3 historical documentation](https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/) specifies minute history from January 2022 and one-month retrieval limits for intervals of 1–15 minutes. | Shared five-minute session cache; missing downloads batched into at most 28 calendar days. |

### Deterministic rules

The broader [momentum research review](architecture.md#momentum-deep-research) compares twelve research/practitioner approaches and records further experiments. Opening ranges now include 10 minutes. Completed breakout confirmation has its own 5/10/15/30/60-minute control, aligned to 09:15 IST; five-minute fills and protective exits remain in effect. Defaults stay at five minutes. Hourly confirmation is not an hourly EMA/ADX trend filter.

1. Use prior-session mean rupee turnover to pick up to 50 liquid stocks daily from the selected current constituent universe. Require at least ₹5 crore average turnover and a prior arithmetic-mean 14-session true range of at least 1% of prior close. Daily-history coverage and listing evidence remain validated through the existing preparation pipeline.
2. Observe a completed 5-minute opening range starting at 09:15 IST (15/30 minutes are configurable). Divide opening volume by the average volume in the same interval over the preceding 14 observed sessions. Verified special sessions cannot substitute for regular openings. Explicit raw-volume corporate actions rebase earlier volume into the current share units.
3. Require relative volume at least 1.5 by default. Select at most five stocks by descending opening relative volume, with symbol as the tie-breaker. A positive opening candle qualifies for longs; a negative candle qualifies for shorts; a flat opening candle does not qualify. Direction is configurable.
4. After the opening range, require a completed five-minute close strictly above the opening high for longs or below the opening low for shorts. Enter at the next five-minute bar open, no later than 11:30 IST. One trade per selected stock/session, with no replacement stock or re-entry. This differs from the source paper's stop-market entry; it resolves entry/stop ordering at the cost of delayed entries.
5. Default stop distance is 0.5 prior daily ATR from the slipped execution price. Optional target is a configured multiple of initial price-stop risk; default zero means stop/cutoff only. Gaps through a stop fill at the adverse bar open. When stop and target appear in the same candle, assume stop first. No intrabar trail or implied tick ordering.
6. Risk budget defaults to 0.25% of session-opening equity per trade, including modeled costs in sizing. Each selected stock receives at most one fifth of opening equity including entry fees; unused budgets are not redistributed. Shorts reserve full notional plus entry fees. No leverage or same-day capital recycling. P&L and two-sided fees/slippage reconcile to session-end cash.
7. Exit at the open of the 15:00 IST candle unless stopped/targeted earlier. Cutoff high/low/close cannot change the exit. All trades close the same day. Stop/target timestamps identify five-minute intervals, not exact tick times.

The model, thresholds, ATR definition, close confirmation, India timings and rupee filters are documented research choices. They have not been optimized to maximize this sample's returns. Fees and slippage are configurable aggregate estimates rather than a verified brokerage/tax schedule.

### Dashboard and reproducibility

The **Momentum** view has a schema-driven form, coverage estimate, automatic missing-data fetch, experiment list, report exports and Adjust & rerun. Shared report charts read frozen five-minute candles and show execution markers at the recorded intraday timestamps. Daily volume rankings/selections are retained in each report's `selections` list.

Inputs remain under ignored `data/`: daily input snapshot, minute snapshot, universe membership, prepared daily manifest and hashes, minute snapshot hash, configuration, source-tree provenance, complete trade ledger and equity curve. Downloads retain no token in cache or report. Missing/incomplete expected intraday sessions halt the experiment; no daily or synthetic price substitute is used.

The CLI `scripts/run_momentum.py --config <local JSON file>` submits the same tracked job as the dashboard, within the common one-job-at-a-time rule.

### First real-data backtest

Run ID: `ebef4eacf96f`. Dates: **26 August–4 September 2026**, eight observed sessions. Universe: current Nifty 500, 499 symbols with sufficient daily warmup and 50 selected daily by prior turnover. One symbol was excluded for daily warmup. The run needed 1,289 stock-sessions including volume context; 33 were already cached and 1,256 were downloaded in 103 batches.

| Measure | Result |
|---|---:|
| Starting capital | ₹10,00,000 |
| Final equity | ₹9,89,451.85 |
| Net P&L | −₹10,548.15 |
| Net return | −1.0548% |
| Maximum session-end drawdown | 1.7382% |
| Trades | 21 (12 long / 9 short) |
| Win rate | 38.0952% |
| Expectancy | −0.2802 R |
| Profit factor | 0.5460 |
| Modeled fees | ₹6,665.77 |
| Modeled slippage impact | ₹6,665.78 |
| Overnight positions | 0 |

Parameters were the documented defaults: 5-minute range, relative volume ≥1.5, 0.5 ATR stop, no target, 0.25% risk per trade, five stocks, 10 bps slippage and 10 bps buy/sell charges each. This short sample checks ingestion, execution and report wiring. It neither proves nor rejects a durable edge. Its annualized Sharpe is too unstable to use for strategy selection.

A proposed September-through-1-October window failed the data diagnostic because **HEGAM on 7 September 2026** had an unresolved −64.30% daily-open discontinuity versus its previous close. The initial run ends before that event; prices were not repaired or silently replaced. Later windows need verified event/provider adjustment evidence before proceeding.

### Validation and next research gate

#### Refinement comparison — 8 October 2026

The dashboard now shows cost attribution, long/short breakdowns, signal rejections, and an earlier/later chronological diagnostic. The form groups experiment, selection, entry/protection and cost controls with explanations. Optional refinements are **VWAP confirmation**, a **prior-ATR breakout buffer**, and a **cost breakeven stop activated after a completed close reaches the chosen R threshold**. They default to disabled. VWAP is approximated from cumulative five-minute typical-price × volume; it is not tick VWAP. This is an ORB research adaptation, informed by the authors' [additional intraday momentum/VWAP research](https://concretumgroup.com/wp-content/uploads/2026/02/Beat-the-Market.pdf), not a reproduction of that SPY strategy.

**Compare refinements** runs six predeclared trials on a saved run's frozen daily/minute/universe inputs, preserving its capital and cost assumptions. Frozen hashes, date bounds and warmup are checked. Missing required frozen sessions halt comparison; no current-cache replacement or download is permitted. Adjust & rerun also uses the reference snapshot. All trials are saved; no default changes or automatic winner selection occur.

Comparison ID `84e4b600e868`, reference `ebef4eacf96f`, same 26 August–4 September 2026 dates:

| Trial | Net return | Max drawdown | Trades | Earlier 5 sessions | Later 3 sessions |
|---|---:|---:|---:|---:|---:|
| Baseline replay | −1.0548% | 1.7382% | 21 | +0.1470% | −1.2000% |
| VWAP confirmation | −1.0548% | 1.7382% | 21 | +0.1470% | −1.2000% |
| VWAP + 0.1 ATR buffer | −0.5560% | 1.1407% | 18 | +0.4857% | −1.0366% |
| VWAP + breakeven at 1R | −1.0548% | 1.7382% | 21 | +0.1470% | −1.2000% |
| VWAP + 0.75 ATR stop | −0.6953% | 1.2123% | 21 | +0.2218% | −0.9151% |
| VWAP + 2R target | −0.8666% | 1.5563% | 21 | +0.0781% | −0.9439% |

The buffer reduces losses and drawdown on this sample; all trials remain negative overall and in the later segment. The earlier/later split uses an already known sample and is a diagnostic, **not an untouched holdout**. Before-cost attribution adds recorded fee/slippage impact back to actual net P&L; it is not a separate zero-cost simulation, since costs also affect sizing and protective stops.

Focused tests cover completed-bar timing, long/short exits, adverse gaps, conservative stop/target ambiguity, cutoff future-price exclusion, no future daily selection data, reserved capital, fee reconciliation, missing-history failure, cache reuse and batch downloads, report chart levels, UI routing and intraday markers. Existing Swing/paper tests remain intact.

Next: resolve the HEGAM discontinuity with source evidence, extend to multiple market regimes with historical membership where available, and reserve untouched later dates. Compare long/short components, opening ranges, relative-volume filters and cost sensitivities using fixed predeclared experiments. Report all trials rather than choose a flattering historical curve. Circuit limits, short-sale eligibility, participation, real broker fills, exchange calendars and intraday drawdown still need validation before paper/live decisions.

<a id="company-research"></a>

## Automatic company research

The Fundamentals page adds company-quality scoring and an LLM that searches websites
for financial filings and multiple recent news articles itself. Users select a stock;
they do not supply websites, articles or financial figures. News reviews remain advisory.
Stored fundamental scores now enforce configurable prospective buy screens. Historical
backtests, stops and position sizing remain unchanged. See [Quarterly bulk pull and buy screens](architecture.md#fundamentals-pull).

### Workflow

1. Refresh the market universe and download daily history as usual.
2. Open **Fundamentals**, choose an existing technical screen and scan candidates.
3. Select **Research stock**. The thesis and provisional disposition are optional.
4. The worker searches company/exchange disclosures and recent reporting, then extracts
   financial metrics, supportive catalysts, risks, contradictions and unknowns.
5. Read the saved review and clickable citations. Reviews remain in the prospective
   journal and can be exported. Rejected candidates remain in the journal too.

Research runs as an inspectable job. Failed or interrupted jobs do not fabricate reviews
or figures. Research the technical shortlist one company at a time; there is no whole-
universe paid search. The separate NSE fundamentals pull covers the complete market-data
universe, with quarter-aware caching and automatic prospective buy restrictions.

### Server connection

For Windows local setup, run `./setup-research.ps1` from PowerShell in the project folder.
It prompts for the API key without displaying it, verifies key/model access using the
Models endpoint, and stores the key with Windows DPAPI encryption in
`%LOCALAPPDATA%/TraderCompanyResearch/openai.json`, outside the repository. The directory
has an ACL restricted to the current Windows user. Default model: `gpt-5.4-mini`, which
supports web search and structured outputs. The access check does not verify billing
or generate/search; the first company research job verifies those capabilities.
Stop the existing local server, then run `./start.ps1` to load the saved connection.
Existing process environment variables take precedence over the saved local values.
The encrypted record can be unlocked only by the same Windows account; it is not a
portable server credential. Run setup again to replace it. Never paste keys into chat.

Model reference: [GPT-5.4 Mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini).

Set `OPENAI_API_KEY` and `TRADER_NEWS_MODEL` in the server process environment. Choose
a model supporting Responses web search and structured outputs. No key or model is
silently selected, and Python does not load `.env.example` automatically. Keys are
never returned to the dashboard. Production requires the existing Basic Auth settings
before exposing a paid research action. This feature does not configure credentials.

The first Responses request requires `web_search`, includes source metadata and caps
built-in tool calls at eight. The second extracts structured data from the retrieved
report without tools. Both set `store=false`. Provider request failures are reported
without saving request headers or secrets. Live search requires a configured API key;
provider behavior is tested using mocked responses.

Official references: [Web search](https://developers.openai.com/api/docs/guides/tools-web-search)
and [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

### Evidence contracts

- Exact company identity uses name, NSE symbol and ISIN. Unconfirmed identity rejects
  the review. Web content is untrusted evidence and cannot authorize actions.
- Cited URLs must appear in provider search metadata or URL annotations; generated links
  alone are insufficient. This verifies source discovery, not the model's interpretation.
- Automatic financial scores use direct official NSE integrated Ind-AS HTML filings;
  LLM-generated financial figures never enter the score. Downloads validate symbol,
  ISIN, INR units, reporting dates and accounting basis. Original HTML, SHA-256 hashes,
  parsed rows and calculation inputs are retained under `data/company/filings`.
  The timestamp encoded in the NSE filename is recorded with an explicit notice and
  checked against the board approval date; it is not inferred by the LLM.
- Quarterly revenue/PAT growth requires matching prior-year dates, units and basis.
  NSE's integrated-filing index discovers the latest and matching prior-year quarters
  directly, independently of LLM-selected links. Old month-name dates and INR actuals
  are supported; amounts are converted to INR before comparing rupees/lakhs/crores.
  Only the reporting-quarter column is used, never the YTD column. Nonpositive prior
  bases and conflicting prior revisions leave growth unknown. An explicit unmodified
  opinion can populate the filing-specific auditor check, not the governance check.
- Annual NSE filings now populate ROE (total PAT / average total equity), ROCE
  ((PBT + finance costs) / average (total assets - current liabilities)), debt/equity
  (current and non-current borrowings plus explicit lease liabilities / total equity),
  interest coverage ((PBT + finance costs) / finance costs) and operating cash flow/PAT.
  Annual profit and finance costs use the YTD column; fourth-quarter figures are not
  annualized. Average balance-sheet ratios require two annual filings. Nonpositive
  denominators and unsupported fields remain unknown. These are the stated calculation
  conventions, and may differ from published vendor ratios.
- This adapter does not parse BSE filings, company PDFs, bank/NBFC taxonomies,
  P/E or promoter pledges. Placeholder zero ratios are
  ignored. Unsupported or inaccessible documents leave financial metrics unknown;
  failures appear in the saved review. Downloads allow only the supported official
  NSE host/path, reject redirects and cap size at 2 MB and discovery at eight files.
  Requests identify the reader with `TraderCompanyResearch/1.0`; NSE stalls the default
  Python HTTP client user-agent on this machine. Connect/read timeouts are 5/20 seconds.
- Legacy LLM-derived financial snapshots remain in the audit files but are excluded
  from the current screener. The report, discovered links, response IDs and usage
  remain preserved alongside direct filing artifacts.
- Recent-news findings require known publication dates in the preceding 30 calendar
  days. Missing dates cannot support favourable recent news. The LLM groups coverage
  of the same event, but independent corroboration is not guaranteed.
- Two non-opinion source domains are required for `supportive`; conflicting or adverse
  evidence yields `mixed` or `adverse`. Insufficient evidence remains explicit. Verdicts
  classify evidence and do not predict prices or issue buy instructions.
- The financial snapshot and review are frozen prospectively. Today's evidence must
  not be used as historical point-in-time inputs. Reviews store the selected technical
  configuration and the latest price-catalog context; signal and review dates may differ.

### Experimental score

Missing metrics earn zero points; coverage is the sum of known metric weights. Financial
periods older than 180 days, reported auditor/governance concerns, and promoter pledging
above 20% flag review. No adverse search results does not establish clean governance.

| Criterion | Non-financial weight | Bank/NBFC weight |
|---|---:|---:|
| Latest quarter revenue growth YoY ≥ 10% | 15 | 15 |
| Latest quarter PAT growth YoY ≥ 10% | 20 | 20 |
| Annual/trailing annual ROE ≥ 12% | 15 | 15 |
| Annual/trailing annual ROCE ≥ 15% | 10 | — |
| Debt/equity ≤ 1 | 10 | — |
| Annual/trailing annual interest coverage ≥ 3 | 5 | — |
| Annual operating cash flow / positive PAT ≥ 0.8 | 5 | — |
| Net NPA ≤ 2% | — | 15 |
| Capital adequacy ≥ 15% | — | 15 |
| Promoter shares pledged ≤ 5% | 10 | 10 |
| Explicit evidence of no auditor concern | 5 | 5 |
| Explicit evidence of no governance concern | 5 | 5 |

These are research thresholds, not sector regulatory requirements. IPOs may have limited
financial history; negative-base profit growth stays unknown. Valuation and acceleration
are not scored yet. Technical scans reuse swing predicates, warmup, RS, breadth, listing
and corporate-action evidence. They exclude today's possibly incomplete IST session,
stale history, quarantines and detected price discontinuities.

### Storage and evaluation

Research artifacts use the existing ignored data directory: `company/evidence.json`,
`company/reviews_index.json`, and `company/reviews/<id>.json`. Later research never rewrites
old reviews. Optional manual import APIs remain compatible but are not the primary UI.

Tests cover scoring, missing values, sector rules, timestamps, actual search execution,
identity, URL provenance, per-metric sources, news recency, provider failures, queued jobs,
immutable journals, API boundaries, automatic controls, filtering and HTML escaping.
Evaluate the configured entry filters prospectively, including rejected
candidates, net expectancy, drawdown and missed winners.

<a id="fundamentals-pull"></a>

## Quarterly fundamentals cache and buy screens

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

Run the matched comparison with `scripts/compare_fundamental_ranking.py --reference <saved-swing-run-id> --start 2026-06-01 --end 2026-10-01`. It holds price inputs, costs, signals and exits fixed within each pair and changes only ranking, with five positions in both. Results are in [FUNDAMENTAL_RANKING_COMPARISON.md](architecture.md#fundamental-ranking-comparison).

<a id="data-validity"></a>

## Data-validity safeguards — first increment

These checks do not establish a trading edge or certify corporate-action adjustment.
No historical report, provider candle or paper ledger is migrated by this change.

### Price-history audit and circuit breaker

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

### Initial local observations (4 October 2026)

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

### IPO eligibility

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

### Breadth coverage

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


### Evidence-backed histories and split/bonus contracts (5 October 2026)

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

### Frozen-input audit, recovery and validation

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
[VALIDATION_PLAN.md](architecture.md#validation-plan). Historical membership and unresolved
corporate actions keep the edge-validation gate closed.


### Official NSE listing import

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

### Initial IPO evidence expansion — 5 October 2026

Bundled initial IPO evidence now covers eight instruments. Added BAJAJHFL
(16 September 2024), HYUNDAI (22 October 2024), SWIGGY (13 November 2024), and
VMM (18 December 2024). Each record contains its issuer or NSE publication URL
and evidence location. This changes eligibility evidence, not the IPO age,
trend, liquidity or volume rules. The publications were reviewed retrospectively;
this is not a point-in-time IPO discovery universe or an untouched holdout.

The price-history audit now reports exchange-listing and initial-IPO evidence
coverage separately. Counts include instruments without cached prices and do
not imply eligible warmup, acceptable adjustment history or a qualifying signal.
Unknown original IPO dates remain blocked. Exchange-master imports preserve the
independent sourced IPO fields. Remaining data reconstruction work is unchanged.

### Exact-row correction — 7 October 2026

COHANCE's ten March 2020 BE candles were left raw while its adjacent EQ history
was bonus adjusted. NSE daily files and issuer bonus evidence now support a
derived-only correction with exact-row matching and immutable source checksums.
The 60% false discontinuity becomes the actual 20% market opening decline.
Original caches, reports and ledgers remain unchanged. Paper history using a newly
changed repair policy must be reconciled before resuming. The unresolved gap
count falls from ten to nine; this does not certify the rest of the history.

See [CORPORATE_ACTION_REVIEW.md](architecture.md#corporate-action-review) for sources, scope,
validation and remaining entitlement/accounting work for all ten investigations.

<a id="corporate-action-review"></a>

## Corporate-action history investigation — 7 October 2026

Original provider candles and saved reports are preserved. An event announcement
does not certify the provider's price/volume basis or account for distributed
securities. Nine unresolved instruments remain blocked by the gap check.

| Instrument | Cached gap date | Evidence reviewed | Outcome |
|---|---|---|---|
| COHANCE (formerly SUVENPHAR) | 24 March 2020 | Ten NSE BE candles are raw; adjacent EQ candles are adjusted for the later sourced 1:1 bonus. | Exact-row derived repair verified; no gap adjustment inferred. |
| ABREL (formerly Century Textiles) | 11 October 2019 | [UltraTech allotment filing](https://www.ultratechcement.com/content/dam/ultratechcementwebsite/pdf/stock-exchange-communication/Century%20Allotment.pdf) records one UltraTech share per eight Century shares, record date 14 October. | Demerger identified; historical identity/basis and entitlement accounting remain unresolved. |
| HEGAM | 7 September 2026 | [NSE instrument record](https://www.nseindia.com/get-quote/equity/HEGAM/HEG-Advanced-Materials-Limited) lists demerger ex-date and record date 7 September 2026. | Demerger identified; distribution, credit/tradability and provider bases remain unresolved. |
| IIFL | 30 May 2019 | [Issuer tax-basis filing](https://nsearchives.nseindia.com/corporate/IIFL_12062019180115_SEIntimationCostofAcquisition_285.pdf) and [scheme memorandum](https://nsearchives.nseindia.com/corporates/offerdocument/scheme/IM_IIFLSecurities.pdf) document securities/wealth demergers and 31 May record date. | Requires multiple resulting securities and fractional-entitlement treatment. |
| NMDC | 27 October 2022 | [NSE circular FAOP54132](https://archives.nseindia.com/content/circulars/FAOP54132.pdf) gives the demerger ex-date. NSE daily file gives raw 27 October open 92.25 and volume 38,603,184. | Cached open 27.88/volume 115,821,134 do not establish an exact consistent factor; earlier and later bases must be reconstructed. |
| SIEMENS | 7 April 2025 | [Resulting-company filing](https://www.siemens-energy-india.com/pdf/outcome-of-board-meeting-13-02-2026.pdf) records 7 April entitlement record date and June listing. | Demerger identified; unlisted entitlement valuation and execution timing remain unresolved. |
| TATACHEM | 4 March 2020 | [Issuer annual-report governance section](https://www.tatachemicals.com/tata/sites/default/files/2025-09/corporate-governance-report-2019-20_1758691856.pdf) describes price discovery/adjustment at the 5 March record date for Consumer Products demerger. | Requires resulting-company holdings and independently verified price/volume basis. |
| TATACOMM | 17 September 2019 | [Issuer January 2021 presentation](https://tatacommunications.com/hubfs/47271964/investor-presentations/pdfs/TCOM-Investor-Presentation-Jan-21.pdf) documents HPIL land demerger, 18 September record date and later October 2020 listing. | Unlisted entitlement valuation, credit and eventual sale must be modelled. |
| TMPV (formerly TATAMOTORS) | 14 October 2025 | [NSE circular FAOP70615](https://nsearchives.nseindia.com/content/circulars/FAOP70615.pdf) gives demerger ex-date 14 October; [issuer scheme release](https://www.tatamotors.com/press-releases/demerger-of-cv-business-undertaking-of-tata-motors-ltd-into-a-separate-listed-company/) states one resulting CV share per original share. | Requires both businesses and instrument identity/date mapping. |
| VEDL | 30 April 2026 | [NSE circular FAOP73857](https://nsearchives.nseindia.com/content/circulars/FAOP73857.pdf) gives demerger ex-date 30 April. | Multi-company distribution cannot be treated as a split. |

### Verified COHANCE repair

All OHLCV values of the ten cached BE sessions from 9–23 March 2020 match the
NSE daily files exactly by date, ISIN INE03QK01018, symbol SUVENPHAR and series BE.
Those rows were left on the raw basis. EQ samples on 24/25 March and 24 September
have prices at half the exchange value (within 0.026 rupees rounding tolerance)
and volumes exactly twice the exchange quantity. The 29 September sample matches
raw prices and volume after the bonus. The [issuer annual report](https://nsearchives.nseindia.com/corporate/SUVENPHAR_06082021185831_SUVENPHARAGMNoticeAR06082021.pdf)
documents the 1:1 bonus, 28 September record date and 29 September allotment.

Normalize only the ten exact documented BE rows: divide OHLC by two and multiply
volume by two. Keep exact mathematical half prices; do not invent provider tick
rounding. This changes the 24 March opening gap from -60% to -20%, consistent with
the exchange's actual opening move. It does not eliminate the real market loss.

`reference_data/candle_repairs.json` stores exact expected/replacement values,
per-file SHA256 and source URL, issuer basis evidence, and all four EQ controls.
The derived-input code rejects any matching date whose source row is neither the
documented bad row nor the verified replacement. Corrected rows are idempotent;
source cache and raw fingerprint checks remain intact. Historical paper cycles
halt when applied repairs to already processed dates differ from their saved
cycle evidence. Reconciliation never rewrites cash, fills or positions.

Corrections strictly before every saved cycle's maximum required signal, market,
RS and exit context need no historical decision reconciliation. Missing context
evidence requires a full check. Blue Sky's long lookback remains protected.
`scripts/reconcile_candle_repairs.py` can replay frozen, single-session, no-fill
checkpoints with old and new inputs. It emits evidence only if both complete
ledgers exactly match the saved ledger and every raw processed fingerprint
matches the frozen source. The record is bound to portfolio ID, complete ledger,
configuration, cycles, membership, fingerprints and repair policy hashes. Changes
invalidate it. Broader or fill-bearing checkpoints remain unsupported and halt.

No event is automatically converted into a split/bonus contract. Frozen backtest
inputs and repair evidence are retained with new results. Earlier reports keep
their original inputs and results; they need separate replays before comparison.

### Remaining reconstruction

For each of the nine demergers: verify the historical instrument identity, exact
exchange price/volume series, entitlement ratio, shares credit date, tradability,
fractional-share settlement and resulting-company price history. Then implement
and test an entitlement ledger before evaluating positions across the event.
Do not use tax cost-allocation percentages as market-price adjustment factors.

<a id="validation-plan"></a>

## Frozen validation plan — registered 5 October 2026 (IST)

This is a research protocol, not a claim of profitability or a live-trading launch.
Current data is not cleared for edge validation. Do not optimize around these
acceptance criteria or call a previously inspected period an untouched holdout.

### Candidate

Use one VCP candidate, Nifty 500, next-session open, starting research cash
₹1,000,000. Freeze these values before new experiments:

| Rule | Value |
|---|---|
| VCP windows | Three consecutive 10-session windows |
| Breakout volume multiple | 1.5 |
| Final contraction volume multiple | 0.8 |
| Trend average | 50 sessions |
| Long trend / rising long trend | Enabled / enabled |
| Minimum turnover | ₹50,000,000 |
| Candidate priority | 126-session RS |
| Market gate | Enabled, breadth ≥40%, coverage ≥80% |
| Risk / initial stop / positions | 1% / 8% / 5 |
| Breakeven / winner exit / maximum hold | 1R / 50-day trail / 120 sessions |
| Slippage per side | 20 bps |
| Buy / sell charges | 15 / 25 bps aggregate assumptions |

Freeze the complete config, source-tree hashes, input hashes and membership
snapshot in the run. The fee values are assumptions, not a verified brokerage
schedule. Stress slippage to 40 bps per side without changing other rules.

### Data gate

Before performance evaluation: resolve or explicitly exclude every suspect
instrument with sourced evidence; reconcile corporate actions and raw/adjusted
price AND volume bases; verify listing dates for IPO experiments; obtain dated
membership and delisted history for historical edge claims. Record exclusions
and their effect. The official listing import covers 497/500 current-universe symbols; three unmatched instruments remain unverified. Listing dates alone do not clear the other data gates.
An anomaly detector passing is insufficient. Unsupported mergers/demergers and
provider revisions remain blocks, not permission to infer split factors.

### Retrospective diagnostics

All dates through 5 October 2026 must be treated as previously available research
data. Once cleared, use chronological yearly evaluations and cost sensitivity,
reporting returns, drawdown, expectancy, exposure, turnover, concentration and
trade count. Compare with a dated Nifty 500 total-return benchmark. Do not
substitute an equal-weight basket or a price-only index and call it the TRI.
If benchmark data is unavailable, mark the comparison unavailable.

Separate bullish, bearish and sideways diagnostics using a rule fixed beforehand
(for example benchmark above/below its dated 200-session average and its slope).
These are diagnostics, not independently unseen validation. Never train using
later periods or change rules after seeing a validation outcome without declaring
a new candidate and a new holdout.

### Prospective holdout and graduation

Reserve observed sessions from **6 October 2026** onward. This document does not
create or replace a production portfolio or allocate capital. Observe the frozen
candidate for at least 12 months AND 100 closed trades, whichever comes later.
It cannot graduate before the data gate passes.

Provisional acceptance rules: positive net expectancy under baseline and stressed
costs; maximum marked drawdown no greater than 20%; positive excess return over
the chosen total-return benchmark across the complete observation window; no
unresolved accounting/data failures. Report uncertainty and concentration: a
small sample or one dominant winner requires continued observation, not a pass.
These thresholds express this candidate's research gate, not universal investment
standards. Passing paper simulation still requires a separate live execution test.

For edge decay, assess rolling 50-trade expectancy, six-month drawdown and data
health against the frozen baseline after each month. Record meaningful failures
in the decision log; investigate before changing rules. Never reset losing history.
No new automation or notification is created by this plan.

### Decision log

| Date (IST) | Decision | Evidence / implication |
|---|---|---|
| 5 Oct 2026 | No global split adjustment | Nestlé sample has prices adjusted by approximately 20 and volume by exactly 20; another adjustment would corrupt it. |
| 5 Oct 2026 | Reject prelisting inputs for four sourced IPOs | Preserve provider cache, filter only derived research inputs; do not invent listing dates for other instruments. |
| 5 Oct 2026 | Quarantine PRIVISCL | Corporate restructure plus implausible old price history; no verified reconstruction yet. |
| 5 Oct 2026 | Keep edge gate closed | Historical membership, remaining actions and provider history still unresolved. |

## Research decisions, reproducible configurations and results from the original Swing study

Scope: decisions and implementation from the custom-screener/Nifty 500 research conversation,
through 4 October 2026. This section records completed simulations, not a live strategy deployment.
Other threads own their portfolio/UI/strategy enhancements; preserve their contracts elsewhere in
this document. No paper portfolio, paper cycle, schedule, live order, deployment, commit or push
was created by this research work. Existing saved reports were kept immutable.

### Final retained result and decision

The retained configuration is the Blue sky research baseline below, not a new strategy registry
plugin. On the refreshed 2018-onward dataset, ₹100,000 became **₹101,919.02**, a **₹1,919.02 net
simulated profit (+1.91902%)**, April 1, 2025 through October 1, 2026. Maximum drawdown was
5.16%, with 25 completed trades. This is the final answer to the owner's profit question.
The 2026-only restart loses 1.85%; edge is not validated. Do not present a positive aggregate
return as consistent profitability, live earnings or an existing paper account balance.

Keep the saved baseline unchanged. Variant A (50-session trailing exit) remains a research
candidate; discard the 1,000-session holding extension as an upgrade; breadth 40 remains
exploratory. None passes the frozen multi-period gate; no combined variant was run or adopted.
Raising risk merely to increase profit was not approved or performed. Research retained 1% risk.

The previously saved +6.23%/₹106,227.12 result (`3f443a7698db`, repeated as `6204b7e682f2`)
used history beginning in 2019. Adding 2018 changes the historical highs used by Blue sky and
therefore qualifying signals and subsequent cash/positions. The refreshed baseline is
`7459a9f087ae`. Comparison verified zero changes to overlapping OHLCV values and 86,177 earlier
bars added across the original eligible cohort; only the run name differs in configuration.
Retain both immutable input snapshots. The old figure is a historical snapshot, not the latest
result. Data lookback must always be identified alongside performance.

### Production preset configuration follow-up — 4 October 2026

The owner deployed the application separately, then explicitly asked this thread to configure
its custom screen directly at https://trader.manojmathivanan.com/#backtests. Saved
`Nifty 500 blue_sky - research` (`custom_df67e81ea7`) through the production UI. A matching
complete-rule backtest, `Nifty 500 Blue sky - production comparison` (`59e7c535f60b`), completed
successfully: April 1, 2025–October 1, 2026, ₹100,000 to ₹106,227.12, +6.23%, 24 trades,
5.39% displayed maximum drawdown, modeled fees ₹2,279.21 and slippage ₹534.79. Before
submission, all resolved form values were checked against the retained complete configuration.
Production's coverage banner starts October 1, 2018; the latest local research includes January
2018 onward. This is a separate production-data result, not a replacement for the local
₹1,919.02 result or proof that the full datasets/engine versions match. No production data
settings, credentials, paper portfolio or schedule were changed by this configuration action.
No code commit/push was made. Presets are durable `data/screens.json` records, excluded from Git:
a code deployment alone does not transfer them. Recreate using the exact screen payload below
or securely migrate the durable data volume; risk/exits/costs still belong to individual runs.
The completed report can be cloned with Adjust & rerun to preserve these execution settings.

### Forward production paper portfolio — explicitly authorized follow-up

After the research and production backtest, the owner explicitly asked to start paper trading
with this screen. Created the first Swing patterns portfolio in production on October 4, 2026:
`Nifty 500 Blue sky - forward paper`, status active, frozen current Nifty 500 universe,
allocated capital ₹100,000, start_session October 5, 2026. Initial cash/equity ₹100,000,
zero positions, zero realized/unrealized P&L, no completed paper sessions. No historical
backtest profit was transferred to its balance. Forward sessions only; earlier data is context.

Configuration copies the retained Blue sky filters and trading settings: next_open entry,
alphabetical candidate priority, 1% risk, 8% initial stop, take_25 with documented fallback,
breadth gate enabled at60%, 1R breakeven, 8% percentage trail, five slots, hold120 sessions,
10 bps slippage/35 bps buy/50 bps sell. Long-trend flags false and min_rs_rating0. PaperConfig
has no backtest dates or minimum_warmup_sessions; do not submit that backtest-only field.
Thus paper eligibility follows the existing PaperConfig/required_warmup contract rather than
the historical comparison's frozen 443-symbol cohort. Current universe membership is fixed
by the paper creation contract, independent of research Settings changes.

Automatic cycles enabled (auto_run=true), run_hour16/run_minute15 IST, one scheduled attempt
per weekday while the production server is running. Holidays produce no fictional candles;
missed completed sessions are processed on a later successful cycle. A qualifying completed
signal enters at the next observed session's open under the daily simulation convention.
No automatic browser/Codex reminder was created. Server scheduling, valid provider token and
real candle availability remain necessary; no real broker order adapter is enabled. View at
https://trader.manojmathivanan.com/#paper. User can inspect Configure portfolio, pause entries
or run a manual cycle; edits preserve capital/history and existing positions' exit settings.

### Exact retained saved screen and execution configuration

Saved title: `Nifty 500 blue_sky - research`, ID `custom_df67e81ea7`. A saved screen stores only
the pattern and 13 signal filters. Entry, ranking, risk, breadth, exits, costs, dates, capital,
warmup and universe are not stored in it. Selecting this screen alone does not reproduce the
tested portfolio rules. Use the complete configuration below or clone the refreshed run via
Backtests → report → Adjust & rerun. Universe is the separate research Settings choice.

Saved screen record:

```json
{
  "name": "Nifty 500 blue_sky - research",
  "pattern": "blue_sky",
  "base_days": 15,
  "max_depth_pct": 35.0,
  "volume_multiple": 1.0,
  "sma_days": 50,
  "require_long_trend": false,
  "require_rising_long_trend": false,
  "min_rs_rating": 0.0,
  "min_turnover": 50000000.0,
  "vcp_window_days": 10,
  "vcp_volume_multiple": 0.9,
  "blue_sky_lookback_days": 5000,
  "multiyear_base_days": 260,
  "multiyear_max_depth_pct": 50.0,
  "id": "custom_df67e81ea7",
  "created_at": "2026-10-04T06:34:25.526820+00:00"
}
```

Complete refreshed baseline BacktestConfig, valid POST `/api/jobs/backtest` body:

```json
{
  "name": "Blue sky tweak baseline recent",
  "pattern": "blue_sky",
  "capital": 100000.0,
  "base_days": 15,
  "max_depth_pct": 35.0,
  "volume_multiple": 1.0,
  "sma_days": 50,
  "require_long_trend": false,
  "require_rising_long_trend": false,
  "min_rs_rating": 0.0,
  "candidate_rank": "alphabetical",
  "min_turnover": 50000000.0,
  "vcp_window_days": 10,
  "vcp_volume_multiple": 0.9,
  "blue_sky_lookback_days": 5000,
  "multiyear_base_days": 260,
  "multiyear_max_depth_pct": 50.0,
  "entry_mode": "next_open",
  "risk_pct": 1.0,
  "stop_pct": 8.0,
  "winner_exit": "take_25",
  "skip_weak_markets": true,
  "market_breadth_pct": 60.0,
  "breakeven_r": 1.0,
  "trail_pct": 8.0,
  "max_positions": 5,
  "max_hold_days": 120,
  "slippage_bps": 10.0,
  "buy_cost_bps": 35.0,
  "sell_cost_bps": 50.0,
  "minimum_warmup_sessions": 260,
  "start": "2025-04-01",
  "end": "2026-10-01",
  "acknowledge_limitations": true
}
```

Data preparation: current Nifty 500 snapshot, real provider bars beginning January 1, 2018 where
available, observed last session October 1, 2026. Global data settings may remain 2019 onward
after the one-off 2018 extension; Settings are not proof of the first date in a saved bar file.
Use 2018 onward explicitly when rebuilding this research. Never trim earlier bar files just
because Settings start is later. Dates April 2025–October 2026 came from the owner; October 4,
2026 was the local current date, and October 1 was the latest observed trading candle.
No future candles, forward returns, fabricated missing sessions or generated sample data were used.

`take_25` is not a pure fixed-target exit: it retains fee-adjusted breakeven and the documented
percentage-trail fallback before the target. `trail_50d` is an inclusive 50-daily-close SMA
activated under the documented breakeven rule, not a continuously unconditional 50-day stop.
Hold limits count surviving observed sessions, not calendar days. The research charges
35 bps buy, 50 bps sell and 10 bps slippage per side are assumptions, not verified historical
brokerage/tax schedules. Stress assumptions were 50/70 bps charges and 25 bps slippage.

### Full Nifty 500 ingestion and verified correction

The official CSV had 501 rows: 500 provider-matchable cash members plus `DUMMYHEG`, an official
index placeholder. Matching by ISIN within NSE_EQ prefers EQ; BE/RR are accepted if unambiguous.
Both the Symbol DUMMY prefix and ISIN DUM prefix must match before excluding a placeholder.
Never treat an ordinary unmatched instrument as a dummy or silently save an incomplete universe.
Store `source_row_count`, `provider_exclusions`, provider `series`, official symbol/name/sector,
ISIN and instrument key. Refresh rejects duplicate ISINs, ambiguous provider keys and unexpectedly
low counts (<45 Nifty 50 or <450 Nifty 500). CSV comes from niftyindices.com; provider master
comes from assets.upstox.com. See the data contract for URLs and request/validation rules.

Initial 2019-onward ingestion eventually completed all 500 instruments: 813,139 bars through
October 1, 2026. At April 2025 start, 464 members had 50 pre-start sessions and 443 had 260.
These are recorded snapshot counts, not guaranteed counts for a future fetch. Every symbol
was downloaded/considered; recent listings can still be excluded from a run for lack of warmup.

IDEA (`INE669E01016`) initially failed validation because provider volume was a signed-32-bit
overflow on August 30, 2024. Official NSE bhavcopy OHLC matched exactly and confirmed volume
4,213,707,883. Rebuild the exact-row override file with this content:

```json
{
  "repairs": [
    {
      "date": "2024-08-30",
      "source": "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_20240830_F_0000.csv.zip",
      "provider_values": [
        16.44,
        16.44,
        15.39,
        15.64,
        -81259413.0
      ],
      "verified_candle": [
        "2024-08-30T00:00:00+05:30",
        16.44,
        16.44,
        15.39,
        15.64,
        4213707883.0
      ],
      "verified_at": "2026-10-04T06:09:29.346169+00:00",
      "reason": "Provider signed-32-bit volume overflow; official NSE OHLC match exactly."
    }
  ]
}
```

Apply by date AND exact equality of all five original numeric OHLCV values; validate the
replacement with ordinary OHLCV checks. If the source row differs, do not replace it. Retain
repair provenance in bar records and run manifests. Never use abs(volume), silently delete
bad rows, adjust prices by guesswork or override arbitrary provider data. Fresh installations
should independently verify the official source again before trusting any override.

The later 2018 history extension updated 499/500 files. MAZDOCK returned invalid OHLCV; its
previous valid file was preserved, beginning October 12, 2020. It has zero pre-2020 sessions,
so it was excluded from every 2020-start matched comparison. That failure did not change the
matched cohort or results. It remains a provider issue to investigate, not a repaired dataset.
2020 comparisons used 47 Nifty 50 members or 358 Nifty 500 members with 260 pre-start sessions.

Corporate actions remain unverified. TMPV October 14, 2025 demerger was documented by the company
filing at https://nsearchives.nseindia.com/corporate/TATAMOTORSSJS_12112025224654_NSEBSECOAFINAL.pdf;
positions spanning that event were disqualified in the initial Nifty 50 research. General Nifty
500 audits flag abs(next open / prior close − 1) >20% while a position spans the date
(entry_date < gap_date <= exit_date). Do not interpret a zero flag count as verified adjustment.

### Research sequence and reconstruction procedure

All experiments are long-only historical simulations. Starting capital is ₹100,000 unless an
explicit original-reference replay says ₹1,000,000. Each run has one cash pool, integer shares,
five slots by default, fee-aware sizing/stops, daily marking, terminal liquidation and a frozen
config/universe/eligible-data manifest. Defaults are compatibility behavior, not retained strategy
rules: fill every research field explicitly. Never optimize on an unexplored period and then
describe it as untouched. The 2026 period was already examined earlier; all later windows are
descriptive/chronological robustness checks, not independent out-of-sample validation.

Original Nifty 50 stage: develop on April 1–December 31, 2025, then restart 2026 separately and
also run the continuous April 2025–October 2026 interval. Base is VCP, base_days 15, depth 35,
volume_multiple 1.5, SMA50, turnover 50,000,000, contraction window 10, dry-up 0.9, next_open,
risk 1%, stop 8%, trail_50d, breadth gate enabled/default 40%, breakeven 1R, percentage trail 8%,
five positions, hold cap 120, costs 35/50/10 bps, warmup default 50. Test the Cartesian product
of contraction window {5,10}, volume multiple {1,1.5}, exit {trail_50d,trail_30w,take_25}: 12 runs.
Then each of two parents (W10/V1/take_25 and W5/V1/trail_50d) receives one separate tweak:
volume 0.75, maximum positions 8, or holding cap 60: six runs. Freeze the best eligible earlier
configuration before the later-period run. Positive expectancy, <=15% DD, >=20 trades and no
unmodeled corporate-action exposure were heuristic gates, not statistical proof. The selected
Nifty 50 full run lost 10.85% (₹89,148.83); this was a backtest loss, not paper ledger activity.

The exact frozen Nifty 50 delta was {"vcp_window_days": 5, "volume_multiple": 1, "winner_exit": "trail_50d", "max_positions": 8}, development run `ad0db0b5c360`, frozen at 2026-10-04T05:47:38.057000+00:00. Its full-period configuration was:

```json
{
  "name": "Custom VCP full period descriptive",
  "pattern": "vcp",
  "capital": 100000.0,
  "base_days": 15,
  "max_depth_pct": 35.0,
  "volume_multiple": 1.0,
  "sma_days": 50,
  "min_turnover": 50000000.0,
  "vcp_window_days": 5,
  "vcp_volume_multiple": 0.9,
  "blue_sky_lookback_days": 5000,
  "multiyear_base_days": 260,
  "multiyear_max_depth_pct": 50.0,
  "entry_mode": "next_open",
  "risk_pct": 1.0,
  "stop_pct": 8.0,
  "winner_exit": "trail_50d",
  "skip_weak_markets": true,
  "breakeven_r": 1.0,
  "trail_pct": 8.0,
  "max_positions": 8,
  "max_hold_days": 120,
  "slippage_bps": 10.0,
  "buy_cost_bps": 35.0,
  "sell_cost_bps": 50.0,
  "start": "2025-04-01",
  "end": "2026-10-01",
  "acknowledge_limitations": true
}
```

Nifty 500 phase: repeat those 18 development trials. Add 12 trials across pattern
{vcp,blue_sky,multiyear}, trend {both long flags false,both true}, exit {trail_50d,take_25}, volume 1
and common 260-session warmup. Top two earlier candidates receive RS70+rs_126 or breadth60
separately (four runs). Initial finalists fail old-period stability; adaptive checks were
expanded to six candidates across 2021–2022 and 2023–2024 (12 runs), with adaptation recorded
before the final 2026 comparison. Freeze the candidate with highest worst old-period return if
none passes, explicitly label it a fallback. Final stage includes Nifty 50 selected rules on
Nifty 500 full period, selected VCP and Blue sky full/check pairs, and Blue sky 2026 stress:
six runs, total 52. Blue sky breadth60 selection was frozen at 2026-10-04T06:30:43.961047Z,
development ID `dc1c73b37742`; it did not pass all observed checks. No validated winner emerged.

Old 2019-history Nifty 500 full-period results: original selected VCP settings ₹88,229.17
(−11.77%, ID `fa6b937729dd`); revised VCP ₹98,579.97 (−1.42%, ID `73dc2b75832a`); Blue sky
₹106,227.12 (+6.23%, ID `3f443a7698db`). Blue sky 2026 check `a7f1896119b4` lost 1.85%; stress
`a34c0ef13a51` lost 2.17%. Subsequent history extension supersedes only the latest baseline
interpretation; never rewrite those saved results or splice restart returns into continuous P&L.

Research runners may be recreated from these loops and contracts rather than copying artifacts:
POST a complete BacktestConfig to `/api/jobs/backtest` with `X-Trader-Request: local-ui`; poll
GET `/api/jobs/{id}` until success/failed; success has result.run_id, then GET `/api/runs/{id}`.
Persist each completed job ID, configuration delta, metrics, eligible symbols, manifest hashes,
exclusions and gap exposures before starting the next run. Job states are queued/running/success/
failed, not completed/succeeded. Use bounded retries and check existing jobs after interruptions
to avoid duplicate runs. Make a stage restartable by skipping recorded (period,variant) keys.
Do not mutate global Settings to switch universes during another thread's work; direct research
run(settings,config,log,id) can use an explicit Settings snapshot while preserving global state.

### Banana reference and matched comparisons

#### Base-and-pivot experiment — retired by owner on 8 October 2026

This is an archived research decision, not a feature to rebuild into the current
application. After the matched experiment failed, the owner approved removing its
UI option, configuration fields, validation branches, signal dispatch, simulator
and trade-chart branches, active CLI and feature tests. BacktestConfig again uses
the original TradingConfig pattern enum and has no base_pivot_max_days field.
Keep the current paper portfolio and all pre-existing research features unchanged.
Keep the more accurate warning that our screens are independent approximations
inspired by Banana Patterns, with no verified detector parity.

The experiment never reached production. Preserve all completed study reports,
source/configuration/input hashes, curves, trades and frozen inputs under
`artifacts/base-pivot-study-20261008/`. The original executable application is in
its `code/` subdirectory; the final removed module, CLI and test source are also
preserved in `retired-source/`. None of these archived modules are imported by the
current application. Replay only with the isolated frozen code and data, never by
adding experimental reports or schemas to the current application or rewriting the
paper ledger. BASE_PIVOT_RESEARCH.md retains human-readable results and replay
instructions. Artifacts stay ignored and local; they are not uploaded to production.

Archived configuration used pattern=base_pivot, base_pivot_max_days=120 (validated
15–250), base_days>=15 and <=maximum, swing holding and next_open execution only.
Paper and saved-screen configurations never accepted this pattern. The historical
CLI froze input membership/manifests/gap exclusions/source provenance and complete
run configurations before observing metrics, used separate worker processes and
asserted identical input hashes. Unresolved price gaps blocked by default; explicit
exclusions removed every flagged symbol equally without repairing source prices.

Archived detector (replay only): at completed signal
index i, inspect only bars[max(0,i-blue_sky_lookback_days):i]. Pivot is the maximum
prior close; anchor is its most recent equal-price touch. Age is i-anchor, excluding
the signal bar, and floor is the minimum low over bars[anchor:i]. Qualify only if
base_days<=age<=base_pivot_max_days and (pivot-floor)/pivot*100<=max_depth_pct.
Require the existing common SMA/trend/liquidity predicate, signal close>pivot and
signal volume>=volume_multiple times the prior 50-session mean. RS and breadth
used the existing simulator rules. A new closing high resets the next base's
anchor; an equal touch restarts its age. This is a deterministic closing-high base
hypothesis, not a reproduction of Banana's proprietary base detector, ATR tests,
RS recipe or full lifetime history. Do not label it reference-site parity.

The first study fixes the current baseline's capital100000, next_open, risk1%,
stop8%, take25, five positions, hold120, buy35/sell50/slippage10 bps, weak-market
gate off and 260-session warmup. Compare Blue sky, base_pivot and base_pivot with
only min_rs_rating raised to70; alphabetic candidate ordering stays unchanged.
Use 2020-01-01–2025-12-31 and 2026-01-01–2026-10-01, with a common eligible cohort
frozen from the first start. These historical periods have already been examined;
they are diagnostic comparisons, not untouched validation. Before results, freeze
a research-candidate rule: positive return and greater return than baseline in both
windows, with drawdown<=20% in each. This heuristic is not an owner-approved live
risk limit; no automatic promotion follows. Genuine untouched validation must come
from later forward observations. Keep the existing production paper portfolio
active and preserve its identity, capital, checkpoints and accounting.

At implementation, regression checks covered wick/pivot differences, future-data
invariance, base resets, qualification failures, next-open fills, chart consistency
and paper rejection. Feature-specific tests were archived when the runtime feature
was removed; normal application tests remain required after the removal.

Completed first matched study: 347 common eligible symbols; nine unresolved-gap
exclusions (ABREL, HEGAM, IIFL, NMDC, SIEMENS, TATACHEM, TATACOMM, TMPV, VEDL),
plus 144 history/quarantine exclusions. This fixed retrospective cohort uses current
membership and present-day gap information, including later information for earlier
windows; selection/survivorship bias remains. Both windows were previously examined.
The input hash for all six runs is `52dc9cc0075a849ae7a4f2c9c0ba878d0e183239561b6d1278390010739d2bbe`.

| Window | Screen | Net return | Max drawdown | Trades | Run ID |
|---|---|---:|---:|---:|---|
| historical | blue_sky | +25.44% | 27.65% | 330 | `7fc90f9e42c2` |
| historical | base_pivot | +24.60% | 31.66% | 242 | `a424d263580b` |
| historical | base_pivot_rs70 | +25.04% | 22.93% | 288 | `1a3a958d1f8b` |
| recent_2026 | blue_sky | -9.57% | 9.66% | 44 | `fedc63d0a1ee` |
| recent_2026 | base_pivot | -15.49% | 15.49% | 42 | `a6647e40707c` |
| recent_2026 | base_pivot_rs70 | -18.09% | 18.09% | 41 | `e3bb534623d6` |

Both variants fail the frozen candidate gate: neither beats baseline in either
window, both lose in 2026 and both exceed 20% historical drawdown. No parameter
retuning, promotion, paper-account creation or production deployment was performed.
RS70 reduced historical variant drawdown but worsened 2026 losses; a higher win rate
or closer pattern interpretation does not imply better net performance. Baseline
losses and drawdown also prevent an edge-validation claim. Preserve all isolated
study plans, source hashes, manifests, gap findings and complete run snapshots under
`artifacts/base-pivot-study-20261008/`; `BASE_PIVOT_RESEARCH.md` is the human-readable
result record. Source data, shared runs history and the production paper portfolio
were untouched. The experimental option and active engine support have been removed;
only the archived study and its findings remain. Removal verification passed 171
remaining Python tests and frontend checks; the current schema rejects the retired
pattern and omits its maximum-age field. All six study reports and input snapshots
were verified preserved.

The read-only live-screen audit of 8 October 2026 is documented in
`BANANA_PATTERN_COMPARISON.md`. Our active custom Blue sky rule did not match the
reference site's displayed 1/5 October breakout-day lists: both universe membership
and base-pivot versus loaded-history intraday-high predicates differ. CPPLUS and
TDPOWERSYS specifically passed our volume/trend checks on 5 October but closed below
their prior intraday highs. The reference lists were viewed in their 7 October stage
state, not archived historical snapshots; no complete four-screen parity claim is
made. Preserve these limitations and do not describe the existing implementation as
an exact reproduction of Banana Patterns. This audit changed no trading rules or
portfolio state.

Local `Banana VCP comparison 2020-2025` ID `296f93e10b62` (and closest version `f9b80412c8b3`)
is an approximation, not verified reference-site parity. Original rules: VCP with 10-session
windows, base15/depth35, volume1/dry-up0.9, SMA50, turnover0 (closest version turnover50,000,000),
pivot entry, risk1.5%, stop8%, trail_50d, weak-market filter off, breakeven1R/trail8%, five slots,
hold1000, zero fees/slippage; Nifty 50, Jan 1, 2020–Dec 31, 2025, ₹1,000,000 capital.
The original report +144.34% contained nine entries above entry-day high and misreported pivot
premiums as slippage. Corrected frozen-input replay and the UI-visible corrected run
`0538d95ea2b4` return +178.74%, final ₹2,787,383.08, 104 trades and 17.68% DD with zero costs.
The largest three corrected gains (ADANIENT, BSE, COALINDIA) supply 59.35% of net profit;
marked calendar returns 2020–2025 are +40.61%, +50.42%, +3.13%, +30.82%, −1.02%, −1.31%.
Correcting invalid fills changes later sizing/slots, so its higher replay return does not
retroactively validate the old report. Preserve old ledgers and input hashes.

Recent Banana reruns change only dates/capital/universe and the named cost variant; retain its
default 50-session warmup. Zero-cost Nifty 500 +19.21% becomes −3.99% with costs; this is not
just fees subtracted from one ledger. Costed run charges ₹8,222.49, slippage ₹1,933.96; the
variants share 48 entries, with seven zero-only and eleven costed-only entries. Costs change
sizing, fee-adjusted stops, later cash/slots and candidate paths.

| Run / ID | Universe | Dates | Capital | Return | Final equity | Max DD | Trades |
|---|---|---|---:|---:|---:|---:|---:|
| Banana VCP corrected 2020-2025 / `0538d95ea2b4` | nifty50 | 2020-01-01–2025-12-31 | 1,000,000 | +178.74% | 2,787,383.08 | 17.68% | 104 |
| Banana VCP N50 Apr2025-Oct2026 zero costs / `2ba1de1bf087` | nifty50 | 2025-04-01–2026-10-01 | 100,000 | -5.07% | 94,926.88 | 13.11% | 19 |
| Banana VCP N50 Apr2025-Oct2026 modeled costs / `88b31fcb0a7d` | nifty50 | 2025-04-01–2026-10-01 | 100,000 | -7.21% | 92,791.12 | 13.18% | 19 |
| Banana VCP N500 Apr2025-Oct2026 zero costs / `97c611115f4a` | nifty500 | 2025-04-01–2026-10-01 | 100,000 | +19.21% | 119,209.20 | 14.97% | 55 |
| Banana VCP N500 Apr2025-Oct2026 modeled costs / `706fdc316e69` | nifty500 | 2025-04-01–2026-10-01 | 100,000 | -3.99% | 96,006.61 | 20.86% | 59 |

Matched 2020–2025 comparisons use both Nifty 50 and Nifty 500, ₹100,000, common 260-session
warmup, 2018-onward history, exactly equal eligible-symbol/candle hashes within each universe,
and zero or modeled 35/50/10 bps costs. Keep each strategy's signal/entry/risk/exit/breadth rules
intact; this is a complete-rule comparison, not only a pattern comparison or equal-risk study.
These eight runs show Banana wins the historical period; Blue sky's recent advantage is not
universal. No position in those comparisons spanned a >20% flagged gap; adjustments remain
unverified. Original reference capital and warmup differ, so the matched rows do not claim an
exact replay of the original report.

| Run / ID | Universe | Dates | Capital | Return | Final equity | Max DD | Trades |
|---|---|---|---:|---:|---:|---:|---:|
| Blue sky nifty50 2020-2025 zero costs / `9e417db0934d` | nifty50 | 2020-01-01–2025-12-31 | 100,000 | +46.26% | 146,263.63 | 12.37% | 133 |
| Banana VCP nifty50 2020-2025 zero costs / `0934edf07225` | nifty50 | 2020-01-01–2025-12-31 | 100,000 | +179.32% | 279,319.01 | 17.42% | 104 |
| Blue sky nifty50 2020-2025 modeled costs / `c0e41718e7d9` | nifty50 | 2020-01-01–2025-12-31 | 100,000 | +29.27% | 129,270.58 | 13.40% | 132 |
| Banana VCP nifty50 2020-2025 modeled costs / `47db155644f5` | nifty50 | 2020-01-01–2025-12-31 | 100,000 | +109.08% | 209,078.72 | 19.81% | 105 |
| Blue sky nifty500 2020-2025 zero costs / `84778a298880` | nifty500 | 2020-01-01–2025-12-31 | 100,000 | +67.53% | 167,533.54 | 26.93% | 232 |
| Banana VCP nifty500 2020-2025 zero costs / `d45eeabedf1c` | nifty500 | 2020-01-01–2025-12-31 | 100,000 | +251.27% | 351,266.94 | 30.52% | 212 |
| Blue sky nifty500 2020-2025 modeled costs / `6802dae7ed9d` | nifty500 | 2020-01-01–2025-12-31 | 100,000 | +14.75% | 114,754.64 | 29.84% | 235 |
| Banana VCP nifty500 2020-2025 modeled costs / `3342c3b4ff72` | nifty500 | 2020-01-01–2025-12-31 | 100,000 | +179.62% | 279,617.90 | 23.35% | 214 |

### Single-change improvement decisions (final research round)

Freeze baseline from `3f443a7698db`, use updated data, capital/costs/risk unchanged, Nifty 500,
260-session warmup. A changes only winner_exit to trail_50d; B changes only max_hold_days to
1000; C changes only market_breadth_pct to 40. Run all four versions over historical 2020–2025,
early 2021–2022, middle 2023–2024, recent April 2025–October 2026 and standalone 2026. Cohorts
match within each window but can differ across starts; returns across restarts cannot be added.
Nineteen new jobs plus one matching historical baseline reused give 20 comparisons.

Frozen promotion rule: no flagged gap exposure; drawdown <=20% in every tested window and
<=15% in recent/2026 windows; strictly positive recent and standalone 2026 returns; beat baseline
returns in at least three of five windows. These thresholds are heuristic research criteria,
not owner-approved production limits or proof of significance. Combine only changes that
independently pass. None passes; therefore no combination and no saved baseline modification.

| Window | Baseline return / DD | A trail50 return / DD | B hold1000 return / DD | C breadth40 return / DD |
|---|---:|---:|---:|---:|
| historical | +14.75% / 29.84% | +19.01% / 30.15% | +8.05% / 33.90% | +38.18% / 26.14% |
| early | -9.96% / 20.37% | -1.24% / 27.68% | -9.73% / 19.52% | -10.84% / 21.14% |
| middle | +15.37% / 6.87% | +27.66% / 13.72% | +14.33% / 7.96% | +10.46% / 7.99% |
| recent | +1.92% / 5.16% | +7.11% / 3.92% | +1.92% / 5.16% | +13.05% / 7.66% |
| 2026 | -1.85% / 3.16% | -2.59% / 3.89% | -1.85% / 3.16% | -4.03% / 6.14% |

```json
{
  "single_change_decisions": [
    {
      "variant": "A trail50",
      "changes": {
        "winner_exit": "trail_50d"
      },
      "passed": false,
      "wins": 4,
      "reasons": [
        "drawdown above 20% in a tested window",
        "non-positive recent or 2026 return"
      ]
    },
    {
      "variant": "B hold1000",
      "changes": {
        "max_hold_days": 1000
      },
      "passed": false,
      "wins": 1,
      "reasons": [
        "beats baseline in only 1/5 windows",
        "drawdown above 20% in a tested window",
        "non-positive recent or 2026 return"
      ]
    },
    {
      "variant": "C breadth40",
      "changes": {
        "market_breadth_pct": 40
      },
      "passed": false,
      "wins": 2,
      "reasons": [
        "beats baseline in only 2/5 windows",
        "drawdown above 20% in a tested window",
        "non-positive recent or 2026 return"
      ]
    }
  ],
  "passing": []
}
```

A beats baseline four of five times but exceeds the drawdown gate and loses in standalone 2026.
B wins once and is unchanged in the recent windows. C wins twice; its higher full/recent return
comes with worse standalone 2026 loss. Do not pick a pleasant aggregate and claim consistency.
The retained baseline also fails edge validation; keeping it for reference is not endorsement
for live trading. Further research or future paper evidence remains separate work.

Complete comparison IDs and observed accounting metrics:

| Run / ID | Universe | Dates | Capital | Return | Final equity | Max DD | Trades |
|---|---|---|---:|---:|---:|---:|---:|
| Blue sky nifty500 2020-2025 modeled costs / `6802dae7ed9d` | nifty500 | 2020-01-01–2025-12-31 | 100,000 | +14.75% | 114,754.64 | 29.84% | 235 |
| Blue sky tweak A trail50 historical / `53801407c1c0` | nifty500 | 2020-01-01–2025-12-31 | 100,000 | +19.01% | 119,014.84 | 30.15% | 185 |
| Blue sky tweak B hold1000 historical / `aa85979c4995` | nifty500 | 2020-01-01–2025-12-31 | 100,000 | +8.05% | 108,045.75 | 33.90% | 223 |
| Blue sky tweak C breadth40 historical / `0e88b257529a` | nifty500 | 2020-01-01–2025-12-31 | 100,000 | +38.18% | 138,180.08 | 26.14% | 289 |
| Blue sky tweak baseline early / `7d36ae11c1df` | nifty500 | 2021-01-01–2022-12-31 | 100,000 | -9.96% | 90,036.77 | 20.37% | 108 |
| Blue sky tweak A trail50 early / `d55e68732054` | nifty500 | 2021-01-01–2022-12-31 | 100,000 | -1.24% | 98,761.53 | 27.68% | 75 |
| Blue sky tweak B hold1000 early / `348e4d81af8d` | nifty500 | 2021-01-01–2022-12-31 | 100,000 | -9.73% | 90,266.73 | 19.52% | 93 |
| Blue sky tweak C breadth40 early / `6b9190faeddd` | nifty500 | 2021-01-01–2022-12-31 | 100,000 | -10.84% | 89,164.63 | 21.14% | 131 |
| Blue sky tweak baseline middle / `412615120cc1` | nifty500 | 2023-01-01–2024-12-31 | 100,000 | +15.37% | 115,372.83 | 6.87% | 74 |
| Blue sky tweak A trail50 middle / `884aeaf245a6` | nifty500 | 2023-01-01–2024-12-31 | 100,000 | +27.66% | 127,659.02 | 13.72% | 62 |
| Blue sky tweak B hold1000 middle / `499937de64bf` | nifty500 | 2023-01-01–2024-12-31 | 100,000 | +14.33% | 114,328.07 | 7.96% | 75 |
| Blue sky tweak C breadth40 middle / `8f76e53cc044` | nifty500 | 2023-01-01–2024-12-31 | 100,000 | +10.46% | 110,456.20 | 7.99% | 95 |
| Blue sky tweak baseline recent / `7459a9f087ae` | nifty500 | 2025-04-01–2026-10-01 | 100,000 | +1.92% | 101,919.02 | 5.16% | 25 |
| Blue sky tweak A trail50 recent / `589624958038` | nifty500 | 2025-04-01–2026-10-01 | 100,000 | +7.11% | 107,109.33 | 3.92% | 22 |
| Blue sky tweak B hold1000 recent / `7a51599e1eda` | nifty500 | 2025-04-01–2026-10-01 | 100,000 | +1.92% | 101,919.02 | 5.16% | 25 |
| Blue sky tweak C breadth40 recent / `5b7709ab92e3` | nifty500 | 2025-04-01–2026-10-01 | 100,000 | +13.05% | 113,046.10 | 7.66% | 54 |
| Blue sky tweak baseline 2026 / `f9bf76936a33` | nifty500 | 2026-01-01–2026-10-01 | 100,000 | -1.85% | 98,147.96 | 3.16% | 6 |
| Blue sky tweak A trail50 2026 / `0ff32a136e2f` | nifty500 | 2026-01-01–2026-10-01 | 100,000 | -2.59% | 97,405.56 | 3.89% | 6 |
| Blue sky tweak B hold1000 2026 / `8b5be7ee7ac4` | nifty500 | 2026-01-01–2026-10-01 | 100,000 | -1.85% | 98,147.96 | 3.16% | 6 |
| Blue sky tweak C breadth40 2026 / `bb217268ba80` | nifty500 | 2026-01-01–2026-10-01 | 100,000 | -4.03% | 95,974.82 | 6.14% | 36 |

### Equity graph interpretation and reproducibility controls

Curve point per observed session = cash + sum(quantity × last observed close for open positions).
Marks update daily when a held symbol has a candle; missing-symbol dates retain the prior mark.
No modeled cash interest. An all-cash portfolio therefore creates horizontal stretches, not
missing daily P&L. The original +6.23% baseline had no open positions April 1–June 9, 2025
(46 sessions at ₹100,000), and February 1–July 3, 2026 (103 sessions at ₹106,835.48).
Breadth was below60 on 45/46 and 102/103 sessions respectively; entries also require a pattern
signal. These dates belong to that immutable old-history run, not every refreshed variant.
SVG connects every curve point with equal session-index spacing; endpoint labels alone are
shown. Weekends/holidays are absent unless provider candles exist; no elapsed-calendar interpolation.

Verify for every completed liquidated run: final_equity = capital + sum(net trade P&L), within
rounding tolerance 0.02. Verify frozen datasets by SHA256(json.dumps(bars,sort_keys=True).encode())
against each manifest. Matched runs must use identical ordered (symbol,hash) lists within the
comparison window. Persist configuration, universe snapshot, requested range, first/last dates,
exclusions, repair provenance and engine-source hash in research summaries. Existing general run
records do not automatically store an engine version; research artifacts record the hash. Do not
promise exact reconstruction of provider-revised history from just the doc: private credentials,
frozen real candles and personal ledgers require secure backup. This document describes the
algorithms and configuration to rebuild behavior, not artificial data to reproduce headline profits.

Implementation verification in this thread: 44 Python tests passed at the Nifty 500 update,
Node syntax check and screen-preset regression passed, and frozen Nifty 50 disabled-feature
outputs were reproduced. This is a historical test count; other threads may add tests. New tests
cover ISIN matching/dummy exclusions/ambiguity, exact override behavior, trend flags and rising
warmup, RS percentiles/ties/filter/entry ranking without future data, configurable breadth,
checkbox reset and old-screen disabled defaults. Research scripts check real-run ledger/hash
invariants; synthetic unit tests must not alter user datasets.

### Research artifact map (optional evidence, not rebuild prerequisites)

Paths are relative to the repository. Their decisive rules/results are embedded above, so their
absence does not remove the architecture specification. Recreate a runner with the documented
loops if rebuilding from the document alone; never fabricate the original artifact contents.

| Runner / folder | Purpose |
|---|---|
| artifacts/custom_vcp_research.py; custom_vcp_202504_202610/ | Original Nifty 50 grid, refinement, freeze, full/check/stress |
| artifacts/nifty500_research.py; nifty500_202504_202610/ | 500-member audit, 52 trials, staged freeze, all_runs.csv and selected ledger |
| artifacts/report_custom_vcp.py; report_nifty500.py | Publish audited comparisons and initial saved research screen |
| artifacts/banana_vcp_recheck.py; banana_vcp_recheck/ | Frozen original audit and five corrected/recent reference reruns |
| artifacts/compare_strategies_2020_2025.py; strategy_comparison_2020_2025/ | Eight matched-period comparisons and 2018 extension log |
| artifacts/blue_sky_improvements.py; blue_sky_improvements/ | Frozen protocol, 20 comparison summary, decisions and history_effect.json |
| artifacts/architecture_research_update/ | Pre-edit architecture snapshot and documentation reconciliation validation |

The local API has no standalone custom-screen scan endpoint. The owner's request to execute
the saved screen was fulfilled as a historical backtest with the complete tested configuration;
it did not initialize paper trading. UI screens are presets, Backtests stores execution runs,
Paper stores independent portfolios. Keep those meanings distinct during reconstruction.


### Initial grid trial ledger (complete accounting, not new recommendations)

This ledger records the initial Nifty 50 18 development trials plus three validation/full/stress
runs, and all 52 Nifty 500 trials. Exact filters/risk/cost base and stage date windows are specified
above; Overrides are merged into that base, not into the final Blue sky retained configuration.
The saved run record remains authoritative for a historical trial's resolved configuration and
frozen real data. Eligibility and strategy rules were never silently expanded to synthesize
missing listing history. Tables are observations, not hardcoded application fixtures.

| Universe / stage | Label / run ID | Dates | Return | DD | Trades | Overrides from initial research base |
|---|---|---|---:|---:|---:|---|
| nifty50 training | VCP dev W5 V1 trail_50d / `f1e6c4dd2be1` | 2025-04-01–2025-12-31 | +6.11% | 3.22% | 14 | `{"vcp_window_days":5,"volume_multiple":1,"winner_exit":"trail_50d"}` |
| nifty50 training | VCP dev W5 V1 trail_30w / `ead0130f6a6b` | 2025-04-01–2025-12-31 | +4.55% | 3.06% | 13 | `{"vcp_window_days":5,"volume_multiple":1,"winner_exit":"trail_30w"}` |
| nifty50 training | VCP dev W5 V1 take_25 / `464a4193f5d4` | 2025-04-01–2025-12-31 | +3.52% | 3.60% | 15 | `{"vcp_window_days":5,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty50 training | VCP dev W5 V1.5 trail_50d / `7b2576f34715` | 2025-04-01–2025-12-31 | +0.97% | 4.14% | 9 | `{"vcp_window_days":5,"volume_multiple":1.5,"winner_exit":"trail_50d"}` |
| nifty50 training | VCP dev W5 V1.5 trail_30w / `ed0f58c5e575` | 2025-04-01–2025-12-31 | +0.65% | 4.38% | 9 | `{"vcp_window_days":5,"volume_multiple":1.5,"winner_exit":"trail_30w"}` |
| nifty50 training | VCP dev W5 V1.5 take_25 / `be9303157419` | 2025-04-01–2025-12-31 | +1.64% | 3.77% | 9 | `{"vcp_window_days":5,"volume_multiple":1.5,"winner_exit":"take_25"}` |
| nifty50 training | VCP dev W10 V1 trail_50d / `cb0a22133f06` | 2025-04-01–2025-12-31 | +4.38% | 3.36% | 13 | `{"vcp_window_days":10,"volume_multiple":1,"winner_exit":"trail_50d"}` |
| nifty50 training | VCP dev W10 V1 trail_30w / `97c488e00908` | 2025-04-01–2025-12-31 | +3.43% | 3.14% | 11 | `{"vcp_window_days":10,"volume_multiple":1,"winner_exit":"trail_30w"}` |
| nifty50 training | VCP dev W10 V1 take_25 / `2086fd2acc03` | 2025-04-01–2025-12-31 | +7.81% | 3.24% | 14 | `{"vcp_window_days":10,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty50 training | VCP dev W10 V1.5 trail_50d / `4fe5c826411b` | 2025-04-01–2025-12-31 | -1.21% | 3.65% | 12 | `{"vcp_window_days":10,"volume_multiple":1.5,"winner_exit":"trail_50d"}` |
| nifty50 training | VCP dev W10 V1.5 trail_30w / `30ddf1e0a0b8` | 2025-04-01–2025-12-31 | -1.47% | 3.65% | 11 | `{"vcp_window_days":10,"volume_multiple":1.5,"winner_exit":"trail_30w"}` |
| nifty50 training | VCP dev W10 V1.5 take_25 / `294265d24101` | 2025-04-01–2025-12-31 | -1.13% | 3.65% | 12 | `{"vcp_window_days":10,"volume_multiple":1.5,"winner_exit":"take_25"}` |
| nifty50 refinements | VCP refine W10 volume_multiple=0.75 / `5607bf395d17` | 2025-04-01–2025-12-31 | +9.32% | 3.70% | 12 | `{"vcp_window_days":10,"volume_multiple":0.75,"winner_exit":"take_25"}` |
| nifty50 refinements | VCP refine W10 max_positions=8 / `eba038e973cf` | 2025-04-01–2025-12-31 | +5.37% | 4.06% | 18 | `{"vcp_window_days":10,"volume_multiple":1,"winner_exit":"take_25","max_positions":8}` |
| nifty50 refinements | VCP refine W10 max_hold_days=60 / `c4ab4480f334` | 2025-04-01–2025-12-31 | +6.68% | 3.24% | 17 | `{"vcp_window_days":10,"volume_multiple":1,"winner_exit":"take_25","max_hold_days":60}` |
| nifty50 refinements | VCP refine W5 volume_multiple=0.75 / `195e9e37f646` | 2025-04-01–2025-12-31 | +3.53% | 5.90% | 15 | `{"vcp_window_days":5,"volume_multiple":0.75,"winner_exit":"trail_50d"}` |
| nifty50 refinements | VCP refine W5 max_positions=8 / `ad0db0b5c360` | 2025-04-01–2025-12-31 | +3.05% | 6.76% | 23 | `{"vcp_window_days":5,"volume_multiple":1,"winner_exit":"trail_50d","max_positions":8}` |
| nifty50 refinements | VCP refine W5 max_hold_days=60 / `f50c5c10ae4b` | 2025-04-01–2025-12-31 | -2.40% | 5.84% | 20 | `{"vcp_window_days":5,"volume_multiple":1,"winner_exit":"trail_50d","max_hold_days":60}` |
| nifty50 validation | Custom VCP frozen validation / `3206ec3ec1a8` | 2026-01-01–2026-10-01 | -9.68% | 9.75% | 18 | `{"vcp_window_days":5,"volume_multiple":1,"winner_exit":"trail_50d","max_positions":8}` |
| nifty50 full | Custom VCP full period descriptive / `ce5f4b1127a8` | 2025-04-01–2026-10-01 | -10.85% | 15.56% | 41 | `{"vcp_window_days":5,"volume_multiple":1,"winner_exit":"trail_50d","max_positions":8}` |
| nifty50 stress | Custom VCP validation cost stress / `dcb021869ce0` | 2026-01-01–2026-10-01 | -10.14% | 10.14% | 18 | `{"vcp_window_days":5,"volume_multiple":1,"winner_exit":"trail_50d","max_positions":8,"buy_cost_bps":50,"sell_cost_bps":70,"slippage_bps":25}` |
| nifty500 baseline | N500 dev W5 V1 trail_50d / `4c8577e8ae81` | 2025-04-01–2025-12-31 | -1.28% | 6.30% | 23 | `{"vcp_window_days":5,"volume_multiple":1,"winner_exit":"trail_50d"}` |
| nifty500 baseline | N500 dev W5 V1 trail_30w / `6728a55b077a` | 2025-04-01–2025-12-31 | -2.05% | 6.69% | 21 | `{"vcp_window_days":5,"volume_multiple":1,"winner_exit":"trail_30w"}` |
| nifty500 baseline | N500 dev W5 V1 take_25 / `92e7f2d17a93` | 2025-04-01–2025-12-31 | -2.43% | 6.90% | 27 | `{"vcp_window_days":5,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty500 baseline | N500 dev W5 V1.5 trail_50d / `dd0d9b0ba0bb` | 2025-04-01–2025-12-31 | -6.05% | 10.58% | 24 | `{"vcp_window_days":5,"volume_multiple":1.5,"winner_exit":"trail_50d"}` |
| nifty500 baseline | N500 dev W5 V1.5 trail_30w / `775da22a9057` | 2025-04-01–2025-12-31 | -4.64% | 9.85% | 21 | `{"vcp_window_days":5,"volume_multiple":1.5,"winner_exit":"trail_30w"}` |
| nifty500 baseline | N500 dev W5 V1.5 take_25 / `6ca27914dd87` | 2025-04-01–2025-12-31 | -5.85% | 11.22% | 24 | `{"vcp_window_days":5,"volume_multiple":1.5,"winner_exit":"take_25"}` |
| nifty500 baseline | N500 dev W10 V1 trail_50d / `8a155c0c6816` | 2025-04-01–2025-12-31 | +8.35% | 9.61% | 26 | `{"vcp_window_days":10,"volume_multiple":1,"winner_exit":"trail_50d"}` |
| nifty500 baseline | N500 dev W10 V1 trail_30w / `6e814c1629a9` | 2025-04-01–2025-12-31 | +15.40% | 4.80% | 16 | `{"vcp_window_days":10,"volume_multiple":1,"winner_exit":"trail_30w"}` |
| nifty500 baseline | N500 dev W10 V1 take_25 / `4ebccbea0236` | 2025-04-01–2025-12-31 | +13.17% | 4.20% | 33 | `{"vcp_window_days":10,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty500 baseline | N500 dev W10 V1.5 trail_50d / `bb95e15ebbc6` | 2025-04-01–2025-12-31 | +11.22% | 8.98% | 24 | `{"vcp_window_days":10,"volume_multiple":1.5,"winner_exit":"trail_50d"}` |
| nifty500 baseline | N500 dev W10 V1.5 trail_30w / `3abd9e76a74a` | 2025-04-01–2025-12-31 | +16.85% | 4.40% | 16 | `{"vcp_window_days":10,"volume_multiple":1.5,"winner_exit":"trail_30w"}` |
| nifty500 baseline | N500 dev W10 V1.5 take_25 / `00dfe1aa35d2` | 2025-04-01–2025-12-31 | +9.17% | 7.35% | 32 | `{"vcp_window_days":10,"volume_multiple":1.5,"winner_exit":"take_25"}` |
| nifty500 baseline | N500 refine W10 volume_multiple=0.75 / `19455fd29c6b` | 2025-04-01–2025-12-31 | +9.78% | 4.63% | 34 | `{"vcp_window_days":10,"volume_multiple":0.75,"winner_exit":"take_25"}` |
| nifty500 baseline | N500 refine W10 max_positions=8 / `f0336ecdcaad` | 2025-04-01–2025-12-31 | +10.42% | 7.44% | 48 | `{"max_positions":8,"vcp_window_days":10,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty500 baseline | N500 refine W10 max_hold_days=60 / `c98e82c6c57b` | 2025-04-01–2025-12-31 | +14.48% | 5.02% | 33 | `{"max_hold_days":60,"vcp_window_days":10,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty500 baseline | N500 refine W5 volume_multiple=0.75 / `f9fe2e6a9142` | 2025-04-01–2025-12-31 | +5.67% | 6.60% | 18 | `{"vcp_window_days":5,"volume_multiple":0.75,"winner_exit":"trail_50d"}` |
| nifty500 baseline | N500 refine W5 max_positions=8 / `d8be8eee5e0a` | 2025-04-01–2025-12-31 | -7.42% | 10.10% | 38 | `{"max_positions":8,"vcp_window_days":5,"volume_multiple":1,"winner_exit":"trail_50d"}` |
| nifty500 baseline | N500 refine W5 max_hold_days=60 / `2885cda6e44e` | 2025-04-01–2025-12-31 | +0.42% | 6.30% | 26 | `{"max_hold_days":60,"vcp_window_days":5,"volume_multiple":1,"winner_exit":"trail_50d"}` |
| nifty500 next | N500 next vcp trend0 trail_50d / `f6de520035bc` | 2025-04-01–2025-12-31 | +5.25% | 10.18% | 27 | `{"minimum_warmup_sessions":260,"pattern":"vcp","require_long_trend":false,"require_rising_long_trend":false,"volume_multiple":1,"winner_exit":"trail_50d"}` |
| nifty500 next | N500 next vcp trend0 take_25 / `cda74ad47097` | 2025-04-01–2025-12-31 | +8.81% | 6.76% | 32 | `{"minimum_warmup_sessions":260,"pattern":"vcp","require_long_trend":false,"require_rising_long_trend":false,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty500 next | N500 next vcp trend1 trail_50d / `dd6ca4e7c59c` | 2025-04-01–2025-12-31 | +5.77% | 6.07% | 28 | `{"minimum_warmup_sessions":260,"pattern":"vcp","require_long_trend":true,"require_rising_long_trend":true,"volume_multiple":1,"winner_exit":"trail_50d"}` |
| nifty500 next | N500 next vcp trend1 take_25 / `de02acb7c723` | 2025-04-01–2025-12-31 | +5.23% | 6.22% | 32 | `{"minimum_warmup_sessions":260,"pattern":"vcp","require_long_trend":true,"require_rising_long_trend":true,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty500 next | N500 next blue_sky trend0 trail_50d / `fd9c3215dc36` | 2025-04-01–2025-12-31 | +14.61% | 4.91% | 23 | `{"minimum_warmup_sessions":260,"pattern":"blue_sky","require_long_trend":false,"require_rising_long_trend":false,"volume_multiple":1,"winner_exit":"trail_50d"}` |
| nifty500 next | N500 next blue_sky trend0 take_25 / `f4dc67a53d10` | 2025-04-01–2025-12-31 | +19.57% | 4.16% | 23 | `{"minimum_warmup_sessions":260,"pattern":"blue_sky","require_long_trend":false,"require_rising_long_trend":false,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty500 next | N500 next blue_sky trend1 trail_50d / `ef78b86b3d4f` | 2025-04-01–2025-12-31 | +14.73% | 3.96% | 22 | `{"minimum_warmup_sessions":260,"pattern":"blue_sky","require_long_trend":true,"require_rising_long_trend":true,"volume_multiple":1,"winner_exit":"trail_50d"}` |
| nifty500 next | N500 next blue_sky trend1 take_25 / `366eac5c04d7` | 2025-04-01–2025-12-31 | +17.54% | 3.24% | 21 | `{"minimum_warmup_sessions":260,"pattern":"blue_sky","require_long_trend":true,"require_rising_long_trend":true,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty500 next | N500 next multiyear trend0 trail_50d / `5d936bd2f569` | 2025-04-01–2025-12-31 | +23.18% | 3.68% | 17 | `{"minimum_warmup_sessions":260,"pattern":"multiyear","require_long_trend":false,"require_rising_long_trend":false,"volume_multiple":1,"winner_exit":"trail_50d"}` |
| nifty500 next | N500 next multiyear trend0 take_25 / `670af8b7056c` | 2025-04-01–2025-12-31 | +14.70% | 3.47% | 24 | `{"minimum_warmup_sessions":260,"pattern":"multiyear","require_long_trend":false,"require_rising_long_trend":false,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty500 next | N500 next multiyear trend1 trail_50d / `2c532165ce9a` | 2025-04-01–2025-12-31 | +15.95% | 4.42% | 16 | `{"minimum_warmup_sessions":260,"pattern":"multiyear","require_long_trend":true,"require_rising_long_trend":true,"volume_multiple":1,"winner_exit":"trail_50d"}` |
| nifty500 next | N500 next multiyear trend1 take_25 / `4b1f0d54e882` | 2025-04-01–2025-12-31 | +9.35% | 4.86% | 22 | `{"minimum_warmup_sessions":260,"pattern":"multiyear","require_long_trend":true,"require_rising_long_trend":true,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty500 next_refinements | N500 next parent1 RS70 / `0423f4171782` | 2025-04-01–2025-12-31 | +9.80% | 3.74% | 31 | `{"candidate_rank":"rs_126","min_rs_rating":70,"minimum_warmup_sessions":260,"pattern":"blue_sky","require_long_trend":false,"require_rising_long_trend":false,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty500 next_refinements | N500 next parent1 breadth60 / `dc1c73b37742` | 2025-04-01–2025-12-31 | +8.53% | 5.39% | 17 | `{"market_breadth_pct":60,"minimum_warmup_sessions":260,"pattern":"blue_sky","require_long_trend":false,"require_rising_long_trend":false,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty500 next_refinements | N500 next parent2 RS70 / `b1514cd02bb0` | 2025-04-01–2025-12-31 | +9.80% | 3.74% | 31 | `{"candidate_rank":"rs_126","min_rs_rating":70,"minimum_warmup_sessions":260,"pattern":"blue_sky","require_long_trend":true,"require_rising_long_trend":true,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty500 next_refinements | N500 next parent2 breadth60 / `431478e85292` | 2025-04-01–2025-12-31 | +8.53% | 5.39% | 17 | `{"market_breadth_pct":60,"minimum_warmup_sessions":260,"pattern":"blue_sky","require_long_trend":true,"require_rising_long_trend":true,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty500 stability | N500 stability finalist1 2021-2022 / `d1d88d20d14d` | 2021-01-01–2022-12-31 | -16.81% | 28.81% | 142 | `{"minimum_warmup_sessions":260,"pattern":"blue_sky","require_long_trend":false,"require_rising_long_trend":false,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty500 stability | N500 stability finalist1 2023-2024 / `a26226082607` | 2023-01-01–2024-12-31 | +14.76% | 8.62% | 106 | `{"minimum_warmup_sessions":260,"pattern":"blue_sky","require_long_trend":false,"require_rising_long_trend":false,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty500 stability | N500 stability finalist2 2021-2022 / `0d2d05f1ec2c` | 2021-01-01–2022-12-31 | -18.35% | 30.13% | 144 | `{"minimum_warmup_sessions":260,"pattern":"blue_sky","require_long_trend":true,"require_rising_long_trend":true,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty500 stability | N500 stability finalist2 2023-2024 / `9ddbbbbd0d4b` | 2023-01-01–2024-12-31 | +14.77% | 8.62% | 106 | `{"minimum_warmup_sessions":260,"pattern":"blue_sky","require_long_trend":true,"require_rising_long_trend":true,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty500 stability | N500 stability finalist3 2021-2022 / `453fb3d924f4` | 2021-01-01–2022-12-31 | -19.54% | 26.38% | 189 | `{"candidate_rank":"rs_126","min_rs_rating":70,"minimum_warmup_sessions":260,"pattern":"blue_sky","require_long_trend":false,"require_rising_long_trend":false,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty500 stability | N500 stability finalist3 2023-2024 / `48c97463e095` | 2023-01-01–2024-12-31 | +20.38% | 16.34% | 150 | `{"candidate_rank":"rs_126","min_rs_rating":70,"minimum_warmup_sessions":260,"pattern":"blue_sky","require_long_trend":false,"require_rising_long_trend":false,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty500 stability | N500 stability finalist4 2021-2022 / `0806f134446f` | 2021-01-01–2022-12-31 | -19.54% | 26.38% | 189 | `{"candidate_rank":"rs_126","min_rs_rating":70,"minimum_warmup_sessions":260,"pattern":"blue_sky","require_long_trend":true,"require_rising_long_trend":true,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty500 stability | N500 stability finalist4 2023-2024 / `6d09a088ef08` | 2023-01-01–2024-12-31 | +20.38% | 16.34% | 150 | `{"candidate_rank":"rs_126","min_rs_rating":70,"minimum_warmup_sessions":260,"pattern":"blue_sky","require_long_trend":true,"require_rising_long_trend":true,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty500 stability | N500 stability finalist5 2021-2022 / `8ee5779997af` | 2021-01-01–2022-12-31 | -6.81% | 20.53% | 116 | `{"market_breadth_pct":60,"minimum_warmup_sessions":260,"pattern":"blue_sky","require_long_trend":false,"require_rising_long_trend":false,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty500 stability | N500 stability finalist5 2023-2024 / `0d442a2df1ec` | 2023-01-01–2024-12-31 | +14.48% | 7.02% | 76 | `{"market_breadth_pct":60,"minimum_warmup_sessions":260,"pattern":"blue_sky","require_long_trend":false,"require_rising_long_trend":false,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty500 stability | N500 stability finalist6 2021-2022 / `aa00360edb9c` | 2021-01-01–2022-12-31 | -6.81% | 20.53% | 116 | `{"market_breadth_pct":60,"minimum_warmup_sessions":260,"pattern":"blue_sky","require_long_trend":true,"require_rising_long_trend":true,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty500 stability | N500 stability finalist6 2023-2024 / `beefeb3292e8` | 2023-01-01–2024-12-31 | +14.48% | 7.02% | 76 | `{"market_breadth_pct":60,"minimum_warmup_sessions":260,"pattern":"blue_sky","require_long_trend":true,"require_rising_long_trend":true,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty500 finish | N500 same N50 frozen settings full / `fa6b937729dd` | 2025-04-01–2026-10-01 | -11.77% | 16.28% | 78 | `{"max_positions":8,"vcp_window_days":5,"volume_multiple":1,"winner_exit":"trail_50d"}` |
| nifty500 finish | N500 baseline frozen 2026 check / `af4d3695a347` | 2026-01-01–2026-10-01 | -11.48% | 11.57% | 38 | `{"max_hold_days":60,"vcp_window_days":10,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty500 finish | N500 baseline full continuous / `73dc2b75832a` | 2025-04-01–2026-10-01 | -1.42% | 14.67% | 66 | `{"max_hold_days":60,"vcp_window_days":10,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty500 finish | N500 next frozen 2026 check / `a7f1896119b4` | 2026-01-01–2026-10-01 | -1.85% | 3.16% | 6 | `{"market_breadth_pct":60,"minimum_warmup_sessions":260,"pattern":"blue_sky","require_long_trend":false,"require_rising_long_trend":false,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty500 finish | N500 next full continuous / `3f443a7698db` | 2025-04-01–2026-10-01 | +6.23% | 5.39% | 24 | `{"market_breadth_pct":60,"minimum_warmup_sessions":260,"pattern":"blue_sky","require_long_trend":false,"require_rising_long_trend":false,"volume_multiple":1,"winner_exit":"take_25"}` |
| nifty500 finish | N500 next 2026 cost stress / `a34c0ef13a51` | 2026-01-01–2026-10-01 | -2.17% | 3.30% | 6 | `{"buy_cost_bps":50,"market_breadth_pct":60,"minimum_warmup_sessions":260,"pattern":"blue_sky","require_long_trend":false,"require_rising_long_trend":false,"sell_cost_bps":70,"slippage_bps":25,"volume_multiple":1,"winner_exit":"take_25"}` |

## Historical reference observations and investigation evidence

The following observations informed decisions and debugging. They are deliberately separated
from implementation requirements; never present them as live figures, shipped example data,
unbiased performance, or a promise that a regenerated data snapshot produces the same metrics.

### Reference screen vocabulary and observed thresholds

The Banana VCP screen observed in the authenticated reference UI uses these active filters:

- Market cap ≥ ₹500 crore; median turnover ≥ ₹5 crore/day.
- RS rating ≥ 70; price at or above 50-day and 200-day averages.
- Within 30% of the 52-week high; at least 3 weeks of base; maximum base depth 35%.
- Tightening ratio ≤ 0.90× and volume dry-up ≤ 0.90×.
- Other visible fields whose range is “any” are not active constraints until deliberately set.

The other reference preset ranges observed in the site bundle/custom-screen UI are:

| Reference screen | Preset thresholds observed |
|---|---|
| Blue sky | Structure level = 1 (all-time high), RS ≥ 70, current price within 20% below the trigger |
| Multi-year breakouts | Base age ≥ 52 weeks, current price within 20% below the trigger, price above 200-day average, RS ≥ 60 |
| IPO base | Listing age 2–50 weeks, base age ≥ 3 weeks, depth ≤ 35%, price above 50-day average, within 20% below the trigger; no RS requirement for young listings |

These are screen/filter thresholds. They do not by themselves specify the historical universe,
ranking tie-breaks, fill prices, or costs; those must be recorded separately for a backtest.

The reference screen also shows current-stage counts (Forming, Fresh breakout, Climbing, Played
out), sortable measures, and a custom-screen builder. Those are useful research inputs, not proof of
historical performance. The local implementation currently approximates the measurable daily-bar
rules; RS calculation/ranking and the broad historical liquid universe still need a verified data
set before claiming exact reference parity.

The custom builder can start from an existing preset, add/remove range filters, compose formulas
from fields such as RS, base age/depth, pivot distance, moving averages, ATR, volume and turnover,
choose units (number, percent, multiple, rupees, days or ratio), add a note, and save a named screen.
In the local application, routine threshold tuning must remain UI-configurable and stored in the
run snapshot; adding a new screen type remains backend work.

### Banana comparison procedure

To compare against the reference site, record the reference screen, period, entry, stop, winner
exit, risk, max positions, weak-market setting, capital, universe definition, and cost treatment.
Use the same calendar dates and the same data snapshot in both systems. At the recorded comparison attempt, the reference UI offered VCP, Blue sky, Multi-year/deep comeback and IPO base; its period controls are All or individual
years 2020–2025. Its page says the data begins in 2020 and the figures are provisional.

As of the last verified comparison attempt, the reference UI accepted the default VCP settings but
returned “The trade records are still building”; its API returned `ready: false` with a MongoDB
connection-refused error. Therefore no Banana numeric result was treated as authoritative.

The closest saved local comparison was (historical report; invalid pivot fills were later found, so this is not a trusted baseline):

- Dates: `2020-01-01` through `2025-12-31`.
- VCP, pivot entry, 8% stop, 50-day trail, 1.5% risk, five positions, weak-market filter off,
  zero costs, ₹5 crore/day liquidity floor.
- 47 symbols were usable after warmup; three newer symbols were excluded.
- 111 trades; final equity ₹24,43,363 from ₹10,00,000; +144.34% return; 22.32% maximum drawdown;
  42.34% win rate; profit factor 1.83. Run ID: `f9b80412c8b3`.

This is a local exploratory baseline, not a claim that the Banana site should produce the same
number. Exact equality requires Banana's full liquid-market universe, historical membership,
historical RS values/ranking, corporate-action treatment, pivot definitions, and portfolio-selection
implementation. If the reference endpoint becomes healthy, first compare trade dates and symbols,
then entry/exit prices, then sizing/cash allocation, and only finally aggregate returns.

### Historical execution investigation

Historical saved run `0e1267409e82` (3 June 2025–1 October 2026, ₹1 lakh) reported −4.26554%,
17 trades, 9.625% drawdown, 23.529% wins, profit factor 0.767. Four pivot fills exceeded the
entry-day high: BSE 13 Jan 2026 (₹2915 vs ₹2873.70 high), HINDALCO 6 Mar (₹1029.80 vs ₹971.65),
BEL 4 Mar (₹461.65 vs ₹460.85), BHARTIARTL 22 Jun (₹1953.80 vs ₹1924.50). Their combined loss
was ₹5875.66. Removing only the high-touch guard in an in-memory diagnostic reproduced the
saved ledger and equity curve exactly. The guarded replay at investigation time returned +1.42329%
with 13 trades. That number is diagnostic evidence, not a fixed expected output for later engines.

Saved slippage was ₹3375.67; actual modeled execution slippage was ₹586.82. The ₹2788.85
difference exactly equaled pivot premiums over entry-day opens. This was a metric-labeling error,
not an extra cash deduction. The documented +144.34% 2020–2025 baseline also had nine above-high
fills; an investigation replay returned +178.74%. Neither old report proves an edge. These are
historical observations; changes to execution conventions can change future replay results.

The latest run used legacy filter values because built-in selection originally changed only
the pattern. Fix: apply the full preset initially and on every selection; use one screen selector.
Keep results immutable. Additional same-day pivot/close-stop handling now follows the explicit
next-session convention above. When backend code changes, restart the server; refresh the page
for frontend changes. Record an engine hash/version with future runs as a proposed improvement;
current saved run metadata does not automatically contain one. Analytical artifacts live under
artifacts/; they are optional evidence and must not be needed to interpret this document.

<a id="banana-pattern-comparison"></a>

## Banana Patterns versus our breakout signals

Checked 8 October 2026. This is a read-only comparison; no screen settings,
paper checkpoints, data caches or orders were changed.

### Scope and evidence

Compare the production Swing paper portfolio's actual custom **Blue sky**
configuration with Banana Patterns' built-in **Blue sky** screen. The Banana
screen was inspected in the signed-in browser at https://bananapatterns.com/screens,
showing Updated EOD 07/10/2026. Its Fresh breakouts view was filtered by breakout
day to 1 and 5 October. These are the signal dates for our processed next-open
paper sessions of 5 and 6 October respectively.

Important limitation: Banana's list is its 7 October stage classification filtered
by historical breakout date, not an archived screen captured on 1 or 5 October.
Stocks may since have changed stage or failed. The comparison proves different
displayed selections and explains concrete local rejections; it is not a measured
historical recall rate or complete parity audit of all four screens.

Production cached eligible daily history ended on 6 October. An empty local result
for 7 October would mean missing input, not a completed scan with no signals.
No new provider fetch or paper cycle was submitted for this investigation.

### Observed selections

Our results below are raw pattern matches, before breadth, account sizing and
position limits. They were recomputed read-only inside the deployed container from
the portfolio's frozen Nifty 500 membership, listing-filtered cached history and
corporate-action-adjusted context as of each signal date.

| Signal date | Banana Blue sky Fresh list, viewed 7 October | Our custom Blue sky matches |
| --- | --- | --- |
| 1 October | D.P. Abhushan (DPABHUSHAN), Ram Ratna Wires (RAMRAT) | STLTECH, WELSPUNLIV |
| 5 October | Aditya Infotech, Marine Electricals, India Homes, TD Power Systems, Precision Wires India, Shukra Pharmaceuticals, Jaykay Enterprises, One Point One Solutions, Leela Palaces Hotels & Resorts | LGEINDIA, STLTECH |

There was no overlap in these displayed date-filtered lists. Both names on
1 October are outside our portfolio universe. On 5 October only Aditya Infotech
(CPPLUS) and TD Power Systems (TDPOWERSYS) belong to the portfolio's eligible
membership; the remaining seven names are outside it.

The two in-universe discrepancies have specific local causes:

| Stock, 5 October | Our close | Prior loaded-history intraday high | Volume / prior 50-session average | Local rejection |
| --- | ---: | ---: | ---: | --- |
| CPPLUS | 3,989.50 | 4,094.00 | 1.01 | Close does not exceed prior high |
| TDPOWERSYS | 812.90 | 817.55 | 4.17 | Close does not exceed prior high |

Both passed our trend/liquidity predicate and volume threshold. Banana listed
both as base-pivot breakouts. Thus universe differences alone cannot explain the
mismatch: our breakout threshold also differs.

Our other raw matches were CUPID on 30 September, and AETHER, BHEL and STLTECH
on 6 October. These are research signals, not new committed paper orders.

### Rules that differ

1. **Universe.** Banana covers liquid NSE and BSE stocks. Its current Blue sky
   drawer showed market cap at least 300 crore and median turnover at least
   1 crore/day. Our portfolio uses frozen Nifty 500 membership, no market-cap
   predicate and a minimum of 5 crore/day calculated as the prior 50-session
   mean of close times volume. Mean versus median and NSE-only versus combined
   exchange turnover are different measurements. Older Banana guides still
   mention a 500 crore / 5 crore floor; use dated observed settings rather than
   assuming those guides describe today's defaults.
2. **Breakout threshold and base identity.** Banana describes its pivot as a
   base's highest close, tracks bases and assigns stages. Its live Blue sky
   preset showed Structure level at most L1 and pre-breakout position between
   20% below the pivot and the pivot. Our `blue_sky` predicate requires today's
   close strictly above the highest prior intraday high within up to 5,000
   loaded sessions. It does not identify a proper base or its lifecycle. A close
   above a base pivot can remain below an older intraday wick, as the two local
   rejection examples demonstrate. Conversely a new high on several consecutive
   days can qualify repeatedly locally rather than represent one tracked base
   breakout. Limited loaded history is not proof of a lifetime all-time high.
3. **Relative strength.** Banana's observed preset requires RS at least 70.
   The paper portfolio has `min_rs_rating=0`, disabling this filter. Our optional
   RS implementation ranks 126-session price returns in the run's eligible
   universe; equivalence to Banana's RS recipe is unverified.
4. **Volume.** Our active rule requires signal volume at least 1x the prior
   50-session mean. Banana's displayed breakout-volume measure is relative to
   the prior 20-session median. Its Blue sky drawer had volume dry-up unrestricted;
   a displayed volume statistic is not by itself proof of a mandatory entry
   threshold. Do not invent an unobserved Banana volume gate.
5. **Dates, stages and execution.** A Fresh list includes up to five sessions;
   a raw local scan evaluates one signal day. Paper fills at the next session
   open, starts 5 October and advances only through unprocessed completed sessions.
   A screen match is not automatically an account fill. The old breadth gate
   blocked our four candidates for the two processed paper sessions. It is now
   disabled and applies to subsequent sessions, without replaying skipped ones.
6. **Data.** Banana identifies NSE/BSE and Accord as its feeds; ours uses Upstox
   daily candles plus explicit sourced listing/corporate-action reconciliation.
   Adjustment conventions and history coverage can change pivots. No full
   cross-provider candle reconciliation was performed, so data differences are
   a possible additional cause, not a demonstrated explanation for every name.

VCP is also an approximation: our predicate uses three fixed windows with
strictly falling high-low ranges and mean volumes. Banana's published anatomy
uses a detected base and an ATR contraction ratio between its halves. Identical
screen names do not establish equivalent algorithms. Multi-year and IPO screens
also lack verified reference-site parity; they were not stock-list audited here.

### Implication and next comparison

Our current screen names describe inspiration, not reproduced Banana outputs.
Changing only the weak-market setting cannot make the selections match. A fuller
comparison needs a chosen reference preset, the same universe and completed
signal dates, archived stage lists including failures, and documented base/pivot,
RS, liquidity and adjustment definitions. Record candidate-level rejection reasons
before comparing account trades. Any base-detector change would materially change
the research strategy and requires fresh backtests; do not silently rewrite the
running portfolio or historical ledger to force agreement.

Sources: [live screens](https://bananapatterns.com/screens),
[Blue sky guide](https://bananapatterns.com/learn/blue-sky-breakout-pattern),
[method](https://bananapatterns.com/how-it-works),
[site and pivot definition](https://bananapatterns.com/).
Local source: `strategies/swing_patterns/patterns/signals.py`,
`core/portfolio/paper.py`, and the deployed portfolio's configuration/cycle snapshots.

<a id="base-pivot-research"></a>

## Base-and-pivot research — 8 October 2026

Neither experimental variant passes the frozen research-candidate rule. Keep the
existing paper portfolio; do not promote either variant based on these results.
Owner decision: retired on 8 October 2026. The experimental UI option and runtime
support were removed after the failed comparison. It was never deployed. Completed
results, frozen inputs and replay code remain archived locally.

### Matched results after modeled costs

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

### Decision and learnings

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

### Frozen hypotheses and shared account assumptions

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

### Data and validation limits

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

### Reproduction and saved artifacts

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

<a id="fundamental-ranking-comparison"></a>

## Fundamental ranking comparison

Period: 2026-06-01 to 2026-10-01; five positions; ₹10 lakh starting capital.

Identical frozen prices, universe, costs, signal rules and exits within each pair. Ranking is the only changed setting. This comparison does not add the live score/coverage buy filter.

Nifty 500 snapshot: 389 eligible price histories; 111 excluded by the frozen reference/warmup. Costs: 10 bps slippage per side, 35 bps buy charges, 50 bps sell charges. Next-open entries, 8% initial stop, 1.5% risk per trade, +25% winner exit, and the saved market-breadth gate. VCP uses 10-session contraction windows and 0.9 final-volume multiple. Both pairs share the same price-manifest and financial-evidence checksums.

| Screen | Priority | Return | Max drawdown | Trades | Win rate | Trades with usable score | Mean entry score |
|---|---|---:|---:|---:|---:|---:|---:|
| blue_sky | alphabetical | -11.09% | 14.26% | 24 | 20.83% | 22/24 | 50.00 |
| blue_sky | fundamental_score | 1.04% | 5.84% | 25 | 36.00% | 25/25 | 62.00 |
| vcp | alphabetical | 0.42% | 5.87% | 16 | 37.50% | 12/16 | 48.75 |
| vcp | fundamental_score | -6.80% | 11.86% | 21 | 33.33% | 17/21 | 55.88 |

Downloaded retrospectively. Only filings published by the decision time are used. The archive is incomplete and may omit intermediate quarters or earlier revisions; current constituent survivorship and archival selection bias remain. Missing, stale or flagged scores rank last; score ties use coverage then symbol. Ranking does not change the fundamental eligibility filter.

Scores use publication dates and verified raw filing checksums. Intermediate historical quarters are incomplete. The short window and current constituents limit conclusions. A higher score is a financial quality preference, not a forecast of price returns.

Run IDs: e35cbccbd328, 4de96e51f267, 357dfbc435ba, e37151bf1fcc

<a id="momentum-deep-research"></a>

## Intraday momentum: research and experiment review

Research date: 8 October 2026. Scope: improve the existing NSE equity opening-range strategy. Practitioner descriptions are hypotheses; empirical papers establish results only for their own data and execution assumptions. This review uses authors' papers, their own websites and first-person interviews, rather than treating social-media popularity as evidence.

### Assessment

Our implementation has useful safeguards: same-clock relative volume, prior-session liquidity/ATR, completed-bar signals, conservative fills, costs, frozen inputs and compulsory intraday exits. It has not demonstrated a profitable edge. Its principal research gaps are stock selection beyond the top 50 by turnover, event context, higher-timeframe context, and execution realism. Adding more indicators alone does not resolve those gaps.

The earlier eight-session experiment lost 1.0548%; a 0.1 ATR buffer reduced that to a 0.5560% loss. VWAP entry confirmation made no difference. These observations motivate investigation, not a new default.

### Ideas from researchers and practitioners

| People / source | What the source actually proposes or finds | What it means for ours |
|---|---|---|
| Carlo Zarattini, Andrea Barbon, Andrew Aziz — [original ORB paper](https://concretumgroup.com/wp-content/uploads/2026/02/A-Profitable-Day-Trading-Strategy-For-The-U.S.-Equity-Market.pdf) | US stock ORB research, 2016–2023, uses opening direction, stop entries and relative opening volume. Ordinary ORB is substantially weaker than volume-selected stocks in play. The paper includes delisted stocks. Its illustrated protective distance is 0.1 daily ATR. | Our 0.5 ATR stop, completed-close entry, current constituents and narrow liquid scan are material departures. Test selection and timing; do not call ours a reproduction or transplant US returns. Copying the tight stop under our costs could be especially harmful. |
| Derek Melchin / QuantConnect — [replication and code](https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/p1) | Uses 1,000 liquid stocks and the top 20 by relative opening volume. Examines opening durations and ATR thresholds; its displayed backtest covers 2016. | Our top-50 prefilter may remove the very unusual stocks the method seeks. A broader scan needs additional frozen minute data. This replication shares the original hypothesis; it is not wholly independent evidence for India. |
| Ross Cameron — [Warrior Trading's own rules](https://www.warriortrading.com/momentum-day-trading-strategy/) | Emphasizes elevated relative volume, low float, strong daily structure, catalysts, bull flags/flat-top breaks, defined stops and partial profit-taking. | Relative volume thresholds are immediately testable. Historical float and time-stamped news are missing. US small-cap and premarket rules cannot be assumed to fit liquid NSE stocks; partial exits require separate accounting and execution tests. |
| Mike Bellafiore — [SMB first-person momentum example](https://www.smbtraining.com/blog/i-see-momentum-buying) | Describes aggressive buying on a news day and why an unusual stock can offer intraday and later opportunities. The description relies on observing offers and the tape. | Five-minute volume is only a proxy for participation. OHLCV cannot reconstruct aggressive buyers, order-book absorption or liquidity at the offer. Keep such claims outside our simulated signal until appropriate data exists. |
| Kristjan Kullamägi, crediting Pradeep Bonde — [episodic pivots](https://qullamaggie.com/how-to-master-a-setup-episodic-pivots/) | Describes large gaps, exceptional early volume, a surprising catalyst and opening-range-high entries. He discusses different opening durations, daily-low stops and stocks quiet for several months. | Catalyst continuation is a distinct hypothesis. A gap is not proof of news; a retrospective winner gallery is not an unbiased backtest. Intraday forced exits capture only part of the multiday repricing thesis. Need point-in-time event and earnings data. |
| Brian Shannon — [multiple-timeframe guidance](https://alphatrends.net/market-structure-chart-thank-you/) and [VWAP/pullback interview](https://alphatrends.net/archives/podcast/secrets-from-30-years-of-day-trading-trader-interview-08-06-23/) | Uses broader market structure for context, shorter charts for entries, and VWAP/anchored VWAP around meaningful price events. His timeframe guidance distinguishes context, risk assessment and execution. | Supports testing 10-minute signals with hourly context, not a mandatory timeframe. Event anchors must be selected using information available at entry; choosing a future low as the anchor creates look-ahead. Session VWAP confirmation alone is already redundant on our initial sample. |
| Linda Bradford Raschke — [first-person Active Trader interview](https://lindaraschke.net/wp-content/uploads/2026/03/raschke_pt2_0304.pdf) | Describes trend pullbacks to a 20-period EMA after strong momentum, with a 14-bar ADX above 30 on the relevant timeframe; discusses a sequence across 15-, 30-, 60- and 120-minute charts. | A trend-pullback strategy is different from entering the first opening breakout. ADX measures strength, not long/short direction. Requires warmed-up indicators and an explicit resumption trigger; use a separate strategy hypothesis rather than stacking every filter on ORB. |
| Lei Gao, Yufeng Han, Sophia Zhengzi Li, Guofu Zhou — [author publication page and paper link](https://sites.google.com/site/szlwebpage/) | Market intraday momentum concerns prediction of the last half-hour from the return measured from the previous close through the first half-hour. | Overnight and opening returns must remain separate in any implementation. This is a market-level late-session strategy, not evidence that the first five-minute stock breakout works. Our 15:00 cutoff prevents testing the NSE final half-hour. |
| Guido Baltussen, Zhi Da, Sten Lammers, Martin Martens — [published author-hosted paper](https://academicweb.nd.edu/~zda/intramom.pdf) | Across more than 60 futures, 1974–2020, the return from the previous close up to the final half-hour predicts that half-hour. It generally outperforms the early-return predictor and links the effect to hedging demand. | A late-session index strategy deserves its own experiment. Individual equities, NSE closing arrangements, product choice and fees differ. Do not infer an option-dealer gamma state from equity candles. |
| Steven Heston, Robert Korajczyk, Ronnie Sadka — [intraday cross-sectional patterns](https://arxiv.org/abs/1005.3535) | Finds same-clock half-hour return continuation across days alongside reversals over intervals shorter than an hour. | Supports accounting for clock time and cautions against assuming every short-term price rise persists. Same-clock historical return ranking differs from today's ORB and today's relative volume. |
| Tobias Moskowitz, Yao Hua Ooi, Lasse Pedersen — [AQR original research](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum) | Own-return momentum across futures/forwards at longer horizons differs from cross-sectional stock momentum. | Useful context, but a monthly trend result does not validate intraday RSI, ROC or MACD. Match each indicator's horizon to the return horizon being predicted. |
| David Bailey, Jonathan Borwein, Marcos López de Prado, Qiji Zhu — [backtest-overfitting paper](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf) | Selecting among many historical trials creates selection bias; a holdout alone does not account for how many configurations were tried. | Declare the trials, keep failures and count repeated tests. Neither eight sessions nor one additional month supports reliable Sharpe-based model selection. |

These sources converge on a useful hypothesis: unusual participation plus a coherent trend/catalyst can matter more than the name of an oscillator. They do not establish a universally best momentum strategy.

### The 10-minute and hourly candle question

Three concepts need separate controls:

1. **Opening range:** the first 5/10/15/30 minutes determines the initial high, low, direction and relative-volume interval.
2. **Signal confirmation:** a completed 5/10/15/30/60-minute close confirms a break of that range. Larger candles can reject short spikes but enter later and give up movement. This is now implemented independently of the opening range.
3. **Trend context:** for example, the last completed hourly close relative to a warmed-up hourly EMA, its slope, or ADX plus directional confirmation. This was a research proposal at that review. Later completed EMA/MACD implementations and their results are recorded in the indicator study; ADX remains unimplemented.

We can derive larger OHLCV candles from complete five-minute inputs: first open, maximum high, minimum low, final close, summed volume. Volume-weighted measures should retain their original five-minute calculation rather than change solely because the display timeframe changes. [Upstox's V3 documentation](https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/) also supports minute/hour intervals; local aggregation gives comparisons a common input source and avoids unnecessary downloads.

Session alignment is explicit: a 10-minute candle starts 09:15 and closes 09:25; an hourly candle starts 09:15 and closes 10:15. Neither is usable before its close. Our confirmation implementation checks the final five-minute constituent at those boundaries and fills at the next five-minute open. It retains five-minute stop/target handling throughout. It does not use the eventual high/low of an unfinished hour.

A 20-bar hourly EMA needs prior sessions; twenty five-minute bars are a different horizon. Define whether shortened final-session candles are included, how missing/special sessions are handled and how much initialization history is required. Until that is implemented and tested, hourly breakout confirmation must not be described as hourly trend confirmation.

### Experiments declared before reviewing new trial outcomes

Twelve one-factor trials: baseline replay; 10-minute confirmation; hourly confirmation; 10-, 15- and 30-minute opening ranges; relative volume thresholds 2 and 3; last entry 10:00; long only; short only; 0.1 ATR breakout buffer. All preserve the reference capital, risk, universe, cost assumptions and frozen daily/minute inputs. There is no parameter grid or automatic best-configuration promotion.

The Momentum dashboard's **Research ideas** button runs this suite; **Compare refinements** retains the earlier six-trial suite. The CLI equivalent is:

```powershell
.venv\Scripts\python.exe scripts/run_momentum.py --compare <reference-id> --suite research
```

March 2026 was chosen as an additional calendar-month check after daily data passed the quality audit, before inspecting intraday returns. It is a separate exploratory period, not a statistically sufficient untouched holdout. Current Nifty 500 membership remains a survivorship limitation. The unresolved September 2026 HEGAM discontinuity is not silently patched or excluded to make a later test pass.

### Completed local results

Two frozen-input suites completed: `85ae3e8075b3` against March control `28d677c85493`, and `3781a3169343` against initial control `ebef4eacf96f`. All 24 trials are retained as dashboard reports. Requested March dates were 2–31 March 2026; the input contains 19 observed sessions, 2–30 March. The original window contains eight observed sessions, 26 August–4 September. No annualized performance claim is made.

| Trial | March net return | March drawdown | March trades | Aug/Sep net return | Aug/Sep trades |
|---|---:|---:|---:|---:|---:|
| Baseline replay | -5.1040% | 5.1040% | 54 | -1.0548% | 21 |
| 10-minute confirmation | -4.6059% | 4.6059% | 50 | -1.1040% | 21 |
| Hourly confirmation | -2.7755% | 2.7755% | 34 | -0.5955% | 17 |
| 10-minute opening range | -2.7584% | 3.1472% | 52 | -0.7702% | 24 |
| 15-minute opening range | -2.5789% | 2.5789% | 50 | -1.0089% | 21 |
| 30-minute opening range | -2.9235% | 2.9235% | 45 | -0.7668% | 15 |
| Opening relative volume >= 2 | -4.8319% | 4.8319% | 36 | -0.5605% | 16 |
| Opening relative volume >= 3 | -2.7804% | 2.7804% | 17 | +0.1494% | 8 |
| Entries through 10:00 | -4.3863% | 4.3863% | 45 | -1.2241% | 18 |
| Long only | -1.9760% | 1.9760% | 30 | -0.9738% | 18 |
| Short only | -3.8862% | 3.9482% | 44 | -1.3909% | 15 |
| 0.1 ATR breakout buffer | -3.7189% | 3.7189% | 43 | -0.5560% | 18 |

Every March variant is negative overall and in both chronological segments. Relative volume >=3 is positive in the eight-session window but negative in March: a concrete example of why we must not promote the best short-sample result. Ten-minute confirmation is slightly worse than baseline in the original window despite improving March. Hourly confirmation and the ATR buffer reduce losses in both windows, but have not demonstrated positive expectancy.

March control: 489 daily symbols eligible (11 excluded by preparation), at most 50 scanned daily. 1,917 stock-sessions were required including relative-volume context; 30 were reused and 1,887 missing sessions were fetched in 125 batches. Net P&L was -₹51,040.14; modeled fees plus slippage were ₹28,680.37. Adding their recorded impact back leaves -₹22,359.77. This is attribution on actual fills, not a separate zero-cost simulation. Costs matter, but removing them does not explain away the control loss.

Long-only/short-only trials reselect and rank candidates under the direction restriction; they are not simply sums of the baseline long/short ledger. Fewer trades also changes exposure. Compare expectancy, opportunity counts and drawdown alongside return, rather than interpreting a smaller loss as greater alpha.

The first comparison attempt (`47dc781a74ed`) failed on its second trial with the generic local-integrity error; its completed control remains recorded. Frozen hashes subsequently verified and the entire suite completed on retry. A server restart temporarily marked the March download job failed while its CLI worker continued; the worker ultimately saved a successful report. Neither operational interruption was hidden as a strategy result.

The two windows total only 27 observed sessions and use present-day constituents. They establish implementation behavior and reject a confident profitability claim; they do not establish the absence of an edge across all regimes. Full exchange-calendar completeness, intraday equity drawdown and executable short/circuit behavior remain unverified. Defaults remain unchanged.

### Priorities after these checks

| Priority | Proposed experiment | Required evidence/data | Decision rule |
|---|---|---|---|
| 1 | Wider eligible scan, then same-clock RV ranking | Minute warmup for the broader daily liquidity universe; historical constituents/delistings where available | Compare against the narrow scan on identical dates and costs. Check participation and concentration. |
| 2 | Ten-minute confirmation plus independent hourly trend context | Session-aligned hourly history, initialized EMA/ADX, missing-bar checks | Test each component separately before combinations. Verify all feature timestamps precede entry. |
| 3 | Catalyst/gap continuation | Historical announcement timestamps and earnings surprises; corporate-action verification | Separate verified catalysts from price-only gap proxies. Include failed events, not only winners. |
| 4 | Cost/stop and capacity gates | Broker charge model, spread/fill observations and interval volume | Reject economically too-small moves; retain conservative cost stresses. Lowering assumed costs is not a discovered signal edge. |
| 5 | Noise-band trend with completed-bar VWAP exits | Same-clock historical movements; explicit entry/exit cadence | A separate Concretum-style strategy, not simply another ORB checkbox. Their [SPY paper](https://concretumgroup.com/wp-content/uploads/2026/02/Beat-the-Market.pdf) uses time-varying bands, half-hour decisions and different sizing, including leverage in its final version. |
| 6 | Final-half-hour market momentum | Tradable index/ETF/futures minute history, product costs, close/auction and cutoff rules | Separate signal research from executable returns. Do not extend equity short holding assumptions implicitly. |

Default strategy settings should change only after repeatable positive net expectancy across additional periods, tolerable drawdowns, realistic costs and operational validation. The minimum meaningful improvement is better evidence; fewer trades or a smaller historical loss alone does not establish a profitable strategy.

<a id="momentum-stronger-rules"></a>

## Stronger momentum entries — 8 October 2026

This variant addresses the marginal TCS breakout discussed in the recorded March trade. Stronger means stricter evidence at entry, not a proven increase in profitability. Existing saved runs remain unchanged and the default ORB config remains the control.

### Fixed candidate rules

- Keep the five-minute opening range and prior liquidity/ATR selection.
- Wait for a complete hourly confirmation candle, aligned to 09:15 IST. Earliest fill is 10:15; entries remain allowed through 11:30.
- Require a close beyond the opening high/low **plus 0.1 prior daily ATR** in the trade direction.
- Require the close above cumulative session VWAP for longs, below for shorts. VWAP uses five-minute typical-price/volume inputs.
- Require a close in the **top 30% of the completed hour's range** for longs, bottom 30% for shorts. This discourages buying after a large retracement from the hour's high or shorting after a large rebound.
- Require directional movement from the hourly open to its close of at least **0.1 prior daily ATR**. This rejects a negative long candle or a tiny positive body despite a nominal breakout.
- Keep five-minute fills and protective exits, 0.5 daily ATR stop, existing risk/capital limits, mandatory 15:00 exit and the reference's modeled charges/slippage. No leverage, re-entry or target changes.

The two new candle-quality fields default to disabled. Aggregate hourly open/high/low/close come only from the twelve completed five-minute constituents. Future candles cannot alter them. Filters can defer an entry to a later eligible hour; rejecting one signal does not necessarily eliminate that stock's whole session.

### Predeclared comparison

Seven trials: reference replay; hourly control; hourly + VWAP; hourly + buffer; hourly + close-position filter; hourly + directional-body filter; combined stronger hourly rules. Run the same seven trials on both frozen reference windows, retaining every result. No threshold sweep or winner selection.

Dashboard: **Test stronger entries** on a baseline report. CLI:

```powershell
.venv\Scripts\python.exe scripts/run_momentum.py --compare 28d677c85493 --suite stronger
.venv\Scripts\python.exe scripts/run_momentum.py --compare ebef4eacf96f --suite stronger
```

Limitations remain: just two short periods, current-constituent bias, approximate VWAP, assumed costs, unverified short/circuit/participation constraints and session-end drawdown. Filtering away trades can reduce losses merely by reducing exposure. Inspect trade counts and expectancy as well as return; zero trades is not evidence of an edge.

### Completed results

Frozen-input comparison IDs: March `e9723b9dbb6f`; August/September `aeb6eab8c0cf`. All fourteen trials are retained in the dashboard.

| Trial | March return | March trades | Aug/Sep return | Aug/Sep trades |
|---|---:|---:|---:|---:|
| Baseline replay | -5.1040% | 54 | -1.0548% | 21 |
| Hourly control | -2.7755% | 34 | -0.5955% | 17 |
| Hourly + VWAP | -2.2892% | 32 | -0.5955% | 17 |
| Hourly + 0.1 ATR buffer | -0.9464% | 19 | -0.4188% | 14 |
| Hourly + close in trend-side 30% | -1.4501% | 25 | -0.5955% | 17 |
| Hourly + directional body >= 0.1 ATR | -2.4605% | 32 | -0.5955% | 17 |
| Stronger hourly confirmation | -1.2620% | 17 | -0.4356% | 12 |

All variants remain negative in both windows. The combined filters reduce loss and activity relative to the original control, but hourly + buffer alone has better net return than the combined variant in both windows. The combined March trial also has negative expectancy (-0.3639 R), not merely a smaller total loss. Additional filters cannot be described as a proven improvement in edge.

Carry forward hourly + 0.1 ATR buffer as the simpler research candidate alongside the full-quality variant, preserving the original control. No default changes or live/paper enablement follow from these short samples. Tests do not include hourly EMA/ADX context, verified catalysts, broader stock selection or calibrated broker fills.

For the TCS 30 March 10:15 signal, the completed-hour open/high/low/close were 2375.10 / 2398.00 / 2355.00 / 2379.80. The new long buffer requires a close above 2384.46; VWAP was 2383.06; close position was 57.67% versus the required 70%; directional body was 0.0802 ATR versus 0.1. All four gates fail. No TCS trade was taken that day by the combined variant. This is a retrospective explanation of that recorded example, not the basis for optimizing thresholds.

<a id="momentum-indicator-research"></a>

## Momentum indicator loop — declared 8 October 2026

Existing opening-range variants have no reliable positive after-cost result. The March 2026 and August–September 2026 windows are already inspected; results from them are development diagnostics, not independent validation.

### Primary-source research

- [Ross Cameron's MACD video](https://www.youtube.com/watch?v=mfGQr2tHoX0) was located through web search. Accessible video metadata does not provide a full transcript; this research does not claim to have watched or reproduced every rule.
- [Warrior Trading's own indicator documentation](https://support.warriortrading.com/support/solutions/articles/19000141884-4-chart-indicators-wt) lists 9/20 EMAs and MACD. It motivates explicit trend/momentum hypotheses; the particular filters below are our adaptations, not a verified Cameron system.
- [SMB's Fashionably Late Scalp rules](https://www.smbtraining.com/blog/wp-content/uploads/2024/04/The-Fashionably-Late-Scalp-Cheat-Sheet.pdf) describe a rising EMA9 crossing VWAP with measured-move risk/target rules. This is a different entry setup, worth a separate experiment. Its advertised success figures are not evidence for NSE returns.
- [StockCharts MACD histogram documentation](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/macd-histogram) supplies the indicator definition: EMA12 minus EMA26, signal EMA9 of MACD, histogram MACD minus signal.

### Fixed experiments before results

Seven trials: original control; 10-minute confirmation with 0.1 prior-ATR buffer; that control plus EMA9/20; plus MACD; plus both; hourly buffered control; hourly control plus EMA9/20. All other selection, stops, sizing, cutoff, and cost assumptions stay inherited from the reference. Run the suite on original baseline references to avoid inheriting unrelated tuned fields.

EMA gate for long: completed candle close above EMA9, EMA9 above EMA20, EMA9 rising from its previous completed candle. Reverse every inequality for shorts. MACD gate: directional MACD, directional positive histogram, and histogram increasing in the trade direction. The two-filter trial requires both gates.

Aggregate cached five-minute OHLC into bins aligned to 09:15 IST, separately per session. Only full bins update the indicator; incomplete bins cannot signal. Carry EMA state across regular sessions, with SMA seeds and at least 60 prior candles for EMA or 100 for MACD. Warmup uses the existing prior opening-volume sessions, bars through 15:00, dropping terminal partial bins. This deliberately omits the final half hour from warmup; do not compare directly with broker charts using full-session inputs. Price-basis verification for corporate-action crossings is required, so these trials halt rather than infer adjustment factors. Entry remains next five-minute open and stops remain five-minute; indicator and confirmation timeframes are separate.

### Validation criteria and next windows

Before viewing new-period minute results: test February 2025, then May 2025 and November 2025, subject to source coverage and daily data audit. Keep every trial including operational or data-quality failures. New periods become research data once inspected; reserve another untouched period for any selected candidate. Start with the same prior-turnover top-50 scan to isolate indicators; broaden selection separately.

A candidate is eligible for further validation only if net return is positive in each of at least three additional windows, aggregate trades number at least 100, no window's session-end drawdown exceeds 5%, and aggregate net return stays positive with 50% higher assumed charges and slippage. These are screening thresholds, not statistical proof. Fewer trades, mixed periods, or failure after costs means no good indicator yet. Do not optimize these thresholds after seeing results. An eligible candidate still needs an untouched final period, liquidity/fill checks, and paper observation before deployment.

No strategy is promoted automatically and no live orders are authorized.

### Audit log and additional windows

May 2025 halted before minute testing: SIEMENS's 7 April 2025 discontinuity is in the daily warmup. [NSE's official circular](https://nsearchives.nseindia.com/content/circulars/FAOP67393.pdf) confirms a demerger on that date. A demerger is not a simple share split; this code does not invent a price adjustment. November 2025 halted for TMPV's 14 October 2025 discontinuity. Both blocked windows remain in the research log and do not count as successful tests.

Before inspecting their minute returns, add June 2025 (2–30 June) and January 2026 (2–30 January) as further windows using the same seven declared trials and assumptions. Their daily audits pass. The initial February 2025 control downloaded 1,895 missing stock-sessions, reused five, and returned approximately −4.06% after costs over 53 trades. Every indicator variant in February also loses money; the hourly EMA variant returns approximately −0.99% over 14 trades. No candidate passes the screening gate.

March comparison: `497e425172e6`. February comparison: `2560dd357cdd`. Full precision, individual run IDs, frozen data, and all trial metrics are saved in the dashboard's local reports.

### Next loop: fixed pullback setup

Declared before any pullback results: seven trials on the original February, June and January controls. Original replay; 10-minute buffered control; flag with ATR stop; flag with pullback-extreme stop; flag with pullback stop and 2R target; the latter plus EMA; the latter with opening relative volume >=2. Same costs, stock-selection framework, cutoff, capital and frozen data throughout.

[Cameron's published momentum discussion](https://www.warriortrading.com/momentum-day-trading-strategy/) describes a directional move, a short pullback, then renewed buying, with the pullback low as a stop. Our mechanical India adaptation requires a completed directional impulse body >=0.25 prior ATR, exactly two adverse candles with declining directional closes, a pullback retracement <=50% of the impulse body, and a directional resumption close beyond both pullback candles and the buffered opening range. Mirror for shorts. These numeric definitions are our research choices; the US float/news/small-cap selection is not reproduced. Optional pullback stops are known at signal close and risk sizing uses the actual next-open slipped fill-to-stop distance; a gap leaving nonpositive risk distance cancels entry.

These windows have already been inspected for other strategies. Pullback results are exploratory too; they cannot become an untouched final validation merely because this pattern is new.

### Results of these two loops

All 28 indicator trial runs lose after the modeled costs across March 2026, February 2025, June 2025 and January 2026. The three newly downloaded windows reused existing cached inputs and fetched 1,895, 1,964 and 1,865 missing stock-sessions respectively (5,724 total). The seven-rule suite always uses matching inputs within each window.

| Rule | March 2026 | February 2025 | June 2025 | January 2026 |
|---|---:|---:|---:|---:|
| Original control | −5.10% | −4.06% | −5.72% | −3.62% |
| 10-minute buffered control | −2.91% | −3.50% | −2.68% | −1.65% |
| 10-minute EMA9/20 | −1.88% | −2.61% | −2.10% | −1.54% |
| 10-minute MACD | −1.26% | −2.49% | −2.38% | −1.64% |
| 10-minute EMA + MACD | −1.26% | −2.49% | −2.38% | −1.64% |
| Hourly buffered control | −0.95% | −1.86% | −2.38% | −3.32% |
| Hourly EMA9/20 | −0.46% | −0.99% | −1.35% | −3.33% |

The 10-minute EMA variant totals 125 trades and −₹81,371.77 net across the four independent capital resets; its before-cost attribution is still −₹6,717.41. The MACD variant totals 109 trades and −₹77,687.58 net, with −₹12,088.63 before-cost attribution. The hourly EMA variant totals 65 trades and −₹61,218.78 net, with −₹21,728.04 before-cost attribution. Adding independent-window rupee P&L is a diagnostic, not a compounded portfolio simulation. The negative aggregate before-cost attribution means assumed charges alone do not explain these losses; it is not a zero-cost rerun.

All five active flag variants make zero trades in each of February, June and January. Thus the 21 pullback-suite runs consist of six losing control replays and fifteen zero-trade trials. Zero trades is insufficient evidence. Rejection-funnel replays retain the same signal logic and save separate diagnostics: most candidate candles fail the fixed impulse threshold (177 February, 157 June, 215 January); others fail two adverse candles or have insufficient completed current-session candles. Counts are evaluated candidate candles, not distinct stocks or independent trades.

Pullback comparisons: `36fd1389ee15`, `80caf606e4a8`, `ca6498746fc0`. The first CLI briefly showed interrupted after another dashboard process restarted; its worker finished and all seven reports were saved successfully. The CLI now waits for its actual worker rather than trusting a transient persisted interruption marker.

Next declared experiment: expand the prior-turnover scan from 50 to 200 stocks on the same three additional windows, then repeat the fixed suites on each new frozen reference. This tests selection coverage separately; it does not relax the impulse threshold to manufacture trades. A distinct EMA/VWAP crossover setup remains a separate research direction. No candidate has passed the validation gate or been promoted.

<a id="momentum-fundamentals-research"></a>

## Fundamentals before momentum entry

Implemented at the user's request. New dashboard momentum forms enable the fundamentals filter; old saved configurations retain their original behavior for faithful replay. The dashboard's **Test fundamentals filter** action runs a matched pair: the chosen reference configuration without the gate and the identical configuration with it. Prices, costs, capital, stock selection and one frozen fundamental archive are shared.

Entry requires score >=60, evidence coverage >=80%, financial period age <=180 days, and no scorer risk flags. The score reuses the project's transparent earnings/revenue growth, profitability, debt, interest coverage, cash generation, pledge and concern checks. Thresholds are editable and saved per experiment. The same quality gate applies before either a long or short position; this is a universe-quality screen, not a bearish fundamentals thesis. Blocked selected slots are not replaced.

Only verified archived NSE filing bytes are used, with checksum and identity validation. Historical snapshots are reconstructed in publication order. The exact entry time in IST determines which version is available, including same-day releases. Today’s score never substitutes for a missing historical score. These are retrospectively reconstructed research snapshots, not evidence of a contemporaneously made trading decision. The archive lacks some historical quarters/revisions and financial-sector coverage; that can materially bias the subset that trades.

### Matched results

| Window | Without gate | With gate | Allowed / checked |
|---|---:|---:|---:|
| March 2026 | −5.1040%, 54 trades | 0.0000%, 0 trades | 0 / 54 |
| 26 August–4 September 2026 | −1.0548%, 21 trades | +0.1161%, 3 trades | 3 / 21 |

March: 25 entries lack historical financial evidence. The other 29 have stale, incomplete evidence and fail the score/coverage thresholds. Zero trades is not validation of an improvement.

August–September: 18 entries blocked, including nine with missing historical scores. Allowed trades: HINDCOPPER long on 26 August (score 80, coverage 80%, +₹3,047.35); LT short on 26 August (score 60, coverage 85%, +₹388.40); MARUTI long on 2 September (score 60, coverage 80%, −₹2,274.75). Net +₹1,161.00 on ₹10 lakh starting capital after assumed charges and slippage. Different sizing under the evolving equity curve is recomputed by the backtester, rather than subtracting blocked trades from the original ledger.

This is an exploratory three-trade positive result, far below the research requirement of 100 trades and multiple positive windows. No strategy has been promoted. No February 2025 archived versions exist, so a strict February fundamental gate would block every entry; later filings must not be backfilled into that period.

March comparison `89ca875c2cee`, filtered run `47ecdcf8d557`. August–September comparison `bce9e414edbb`, filtered run `92aa48f278b7`. Each saved report includes every proposed entry's pass/block reasons, scores, coverage, period age, filing availability and check time; both matched reports retain the archive hash and frozen evidence.

<a id="momentum-reverse-research"></a>

## Reversed intraday momentum experiment

Original net return **-50.356%**; reversed net return **-54.422%**. Difference: -4.066 percentage points. These are reduced-universe, modeled-cost results.

Requested window: **2024-10-08–2026-10-07**. Observed sessions: 496, 2024-10-08–2026-10-07.

Original signals, opening-volume ranking and next-bar entry timing are preserved. Reverse execution shorts buy signals and buys sell signals. Protective stops/targets use the actual position direction. Fees and adverse slippage are recalculated; this is not a sign flip of old P&L.

Universe: current nifty500; 444 eligible daily symbols. Explicit event exclusions: HEGAM, SIEMENS, TMPV, VEDL. The unfiltered attempt failed its price-gap audit (job `77fdb4d0c2a5`); these four exclusions apply to both runs before liquidity ranking. Another 52 symbols lacked eligible daily inputs. This reduced-universe result does not establish the full-universe result.

Control `836c4463d21b`; reverse `84ac8b96d58b`. Daily manifests, minute snapshot hashes, costs and all configuration fields except name/execution mode/reference are identical.

Regular-opening candle exclusions: ITC:2025-01-06, HINDUNILVR:2025-12-05. Both runs skip these stock-sessions and any candidate whose opening-volume history uses them; the rest of each stock’s history remains eligible.

Matched entries: 1316; control-only: 0; reverse-only: 0.

| Measure | Original | Reversed |
|---|---:|---:|
| Starting capital (INR) | 1,000,000.00 | 1,000,000.00 |
| Final equity (INR) | 496,441.40 | 455,782.83 |
| Net return (%) | -50.356 | -54.422 |
| Maximum session-end drawdown (%) | 51.725 | 54.422 |
| Trades | 1,316 | 1,316 |
| Win rate (%) | 35.71 | 33.13 |
| Profit factor | 0.546 | 0.476 |
| Expectancy (R) | -0.285 | -0.314 |
| Modeled fees (INR) | 289,457.72 | 256,036.83 |
| Modeled slippage (INR) | 289,457.79 | 256,036.80 |

| Calendar portion | Original return | Reversed return | Original / reversed trades |
|---|---:|---:|---:|
| 2024 | +0.286% | -9.126% | 125 / 125 |
| 2025 | -32.328% | -32.484% | 667 / 667 |
| 2026 | -26.850% | -25.713% | 524 / 524 |

![Matched equity curves](artifacts/momentum_reversal_equity.png)

Cost attribution on actual trades: P&L with modeled fees/slippage added back is INR 75,356.91 for the original and INR -32,143.55 for the reversed strategy. This adds costs back to recorded fills, not a separate zero-cost backtest; costs also influence sizing and stops.

Parameters: five-minute opening range/confirmation; relative opening volume ≥1.5; top 50 prior-turnover stocks; up to five positions; 0.25% risk; 0.5 ATR stop; no profit target; last entry 11:30; square-off 15:00 IST. Starting capital INR 1,000,000. Slippage 10 bps each side; buy and sell charges 10 bps each.

Special sessions are omitted from normal-clock momentum eligibility, including any candidate whose 14-session opening-volume context contains one. Added 1 November 2024 Muhurat timing from [NSE circular CMTR64628](https://nsearchives.nseindia.com/content/circulars/CMTR64628.pdf); the existing 21 October 2025 special-session policy also applies. These days remain in the equity calendar with zero trading activity where ineligible.

Exploratory results: current constituents and retrospective exclusions introduce bias; corporate-action checks remain incomplete. Costs are assumptions, short eligibility/circuits/participation are unverified, and drawdown is measured at session ends. The entire historical window is exploratory. Defaults and live/paper behavior remain unchanged.

Reproduce the report: `.venv/Scripts/python.exe scripts/report_momentum_reversal.py 836c4463d21b 84ac8b96d58b`.

<a id="nse-intraday-strategy-review"></a>

## NSE intraday long and short strategy review

Reviewed 9 October 2026. This is a research assessment, not a new profitable backtest or a change to trading defaults. Public performance numbers below are publisher claims, not independently reproduced results. Scope is principally NSE cash equities; index spot, futures and options results are not interchangeable.

### Conclusion

Prioritize cost calibration, stock selection and intraday setup design over adding more indicators. The saved research already tests several indicator refinements without establishing positive net expectancy. Keep daily swing screens as watchlists if useful, but test completed intraday confirmation rather than assuming yesterday's breakout predicts today's open-to-cutoff return. Evaluate long and short portfolios separately before combining them.

### What the local project actually shows

`core/research/intraday_long.py` and `intraday_short.py` qualify stocks on the previous daily session and enter at today's first bar open. They inherit percentage exits (8%, 15%, 25%) and daily moving-average trails from swing research. `core/research/config.py` has an 8% stop default. Actual saved configuration matters: these defaults do not prove that every losing report used them. This is a horizon mismatch worth testing, not a demonstrated explanation of every loss.

The dedicated `core/research/momentum.py` is different: it already implements opening relative volume, intraday confirmation, ATR risk, next-bar execution and optional VWAP/indicator filters. The scalping engine is a third strategy. Avoid treating their results as one system.

Verified directly against saved momentum reports `836c4463d21b` and `84ac8b96d58b`, covering 8 October 2024–7 October 2026:

| Measure | Original momentum | Reversed execution |
|---|---:|---:|
| Trades | 1,316 | 1,316 |
| Net return | -50.36% | -54.42% |
| Profit factor | 0.546 | 0.476 |
| Modeled fees | Rs 289,457.72 | Rs 256,036.83 |
| Modeled slippage | Rs 289,457.79 | Rs 256,036.80 |

Original direction attribution, from the same shared-capital run:

| Direction | Trades | Net P&L | Win rate | Profit factor |
|---|---:|---:|---:|---:|
| Buy/long | 687 | -Rs 284,087.51 | 33.92% | 0.531 |
| Sell/short | 629 | -Rs 219,471.09 | 37.68% | 0.564 |

These are trade attribution figures, not separately sized standalone portfolios. Neither side is profitable. Adding the original run's fees and slippage back to net P&L gives approximately +Rs 75,356.91. That is cost attribution on recorded trades, not a zero-cost simulation: costs affect sizing, stops and subsequent capital.

`MOMENTUM_INDICATOR_RESEARCH.md` records 28 negative indicator trials across March 2026, February 2025, June 2025 and January 2026. EMA and MACD subsets also have negative aggregate before-cost attribution. Thus friction is material, but cannot explain every variant. Fixed flag trials produced no trades; that is insufficient evidence. `MOMENTUM_STRONGER_RULES.md` similarly shows less loss and fewer trades, without positive expectancy. These periods are inspected development data, not untouched validation.

The two-year reports use current constituents, reduced eligible inputs and explicit event exclusions. Historical membership, corporate actions, executable liquidity and short eligibility remain limitations. Session-end drawdown understates possible intraday extremes.

### Online claims and their evidential limits

| Source | Published result or approach | Assessment |
|---|---|---|
| [Intraday Lab: Nifty ORB](https://intradaylab.com/blog/nifty-orb-breakout-strategy-backtest) | Reports 2,122 trades, 48.7% winners, profit factor 1.23 and +91.6%; says shorts contribute 75% of profits. | Uses index spot and excludes costs. Its published code skips stop/target checks on the entry candle, prioritizes a long if both boundaries break, and uses the final available close despite the stated 14:30 exit. Timestamp convention and sizing also need verification. Useful hypothesis, insufficient executable evidence. |
| [DailyBulls: four ORB exits](https://dailybulls.in/orb-intraday-trading-strategy-backtest/) | 42 long Nifty-futures signals, July–October 2025. RSI exit has 71.4% winners and 1.54% return; fixed 1.5R exit has 57.1% winners and 2.88% return. | Small sample; highest win rate is not highest return. Does not establish a short-side edge or independently reproducible after-cost performance. |
| [MarketNetra: VWAP setups](https://marketnetra.in/blog/vwap-trading-strategy-indian-stocks-intraday-nse) | Describes trend pullbacks, gap-day rejection, band breakout and RSI-divergence reclaim; quotes win rates around 55–65%+. | No auditable trade ledger, holdout or full costed study supports those figures on the page. It explicitly labels sample figures illustrative. Institutional-flow explanations are hypotheses, not evidence obtainable from OHLCV. |
| [LeadFinn: basic ORB](https://leadfinn.co/strategies/opening-range-breakout) | Reports RELIANCE 15-minute ORB, 2021–August 2026: 629 trades, -21.76% after charges, PF 0.67. | Counterexample to universal ORB profitability. Single stock; entry at signal close needs execution scrutiny. Proposed filters were not part of its reported run. |
| [LeadFinn: VWAP](https://leadfinn.co/strategies/vwap) | Reports 2,894 trades and -66.48% for its mechanical VWAP baseline after charges. | Shows that VWAP alone need not create an edge. The article's assertion that filters improve expectancy is not a published validation of a profitable filtered variant. |
| [LeadFinn: previous-day levels](https://leadfinn.co/strategies/previous-day-high-low-breakout-strategy) | Reports 1,623 trades over 15 stocks, 42% winners, -27.9% after charges. | Basic PDH/PDL breakouts are not established as profitable. Independently verify unusual result/accounting relationships before relying on figures. |
| [LeadFinn: Supertrend](https://leadfinn.co/strategies/supertrend) | Describes Supertrend with trend/VWAP filters, but says its exact strategy has no published engine result. | Claims of optimal settings are not supported by a demonstrated optimization/holdout on this page. Low priority after our unsuccessful EMA/MACD work. |
| [Public VWAP/EMA report](https://huggingface.co/spaces/aru21/nse-indices-bot-live-dashboard/blob/main/vwap_strategy/results/REPORT.md) | A 13-session cash-equity study with stated Indian charges reports negative results across its tested families. | Short window, overlapping configurations and close fills limit inference. Aggregate trades across variants are not independent observations or one deployable portfolio. Useful negative evidence, not proof that every VWAP strategy fails. |
| [Wang and Gangwar: NSE breakout research](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5198458) | Search-accessible author abstract calls for better data coverage, cost modeling and significance tests. | Full paper access failed during this review. Do not claim its methods or complete results were audited. Its abstract does not establish a ready-to-trade profitable system. |

The CastleGate/Wizzer post surfaced in search but its page failed to load. Its promotional return claim is excluded from verified findings. Anonymous forum claims and retrospective winner charts are discovery leads, not performance evidence.

### Costs: first diagnostic to improve

The verified original momentum config uses 10 bps slippage per side plus 10 bps charges per side: approximately 40 bps round-trip friction. The paper fill adapter applies flat percentage charges; it does not calculate capped brokerage and separate dated levies.

For illustration, [Zerodha's published cash-intraday schedule](https://zerodha.com/charges/) gives roughly Rs 82.68 total charges on one Rs 100,000 buy and one equal-value sell, before spread/slippage, rounding and tiny additional levies. This is 8.27 bps of one-way notional. It is an example, not the user's Upstox tariff or a historical cost schedule. Slippage must be measured separately, not reduced until the curve turns green.

For the scalping defaults, 0.05–0.5% price stops and 1.5R targets imply target moves of only 0.075–0.75%. A 0.40% friction assumption overwhelms the smaller targets. Reject trades with insufficient movement relative to measured costs; a tighter stop is not automatically better.

Add dated broker fees, buy/sell taxes, brokerage caps and adverse execution assumptions. Compare fixed-size gross attribution with full costed reruns; the latter are necessary to account for different sizing and capital paths. Show gross edge, fees, spread/slippage and net edge separately.

### Three strategy candidates worth testing

These are proposed hypotheses, not validated recommendations. Numeric settings should be declared before new outcomes are inspected.

1. **Stocks-in-play breakout/retest.** Select a wider *liquid* universe by unusual opening volume relative to the same clock interval, then compare against the existing top-turnover prefilter. Long: completed opening-high breakout and successful retest; short: opening-low breakdown and failed rebound. Add index/sector direction as a separate experiment. Use current information only; full-day volume and future event labels would leak information.
2. **VWAP trend pullback/rejection.** Long: established upward structure, rising session VWAP, pullback that holds/reclaims it and a completed resumption trigger. Short: declining structure, falling VWAP and a rebound rejected below it. Stop beyond the observed pullback extreme. This is a separate entry pattern, not another Boolean filter on every ORB signal. Define flatness, touch tolerance, slope and resumption mechanically.
3. **Failed-breakout reversal.** Short: break above a known opening/prior-day high, completed close back inside, then failed retest. Long: break below support, reclaim, then hold. Stop beyond the failed extreme. Test separately from continuation; reversing all old signals has already failed. Distinguish genuine event-driven continuation from a failed auction using only information available then.

Use session VWAP for location/direction, same-clock relative volume for unusual participation, ATR for volatility/risk and at most one explicit trend filter. RSI, MACD and Supertrend deserve an additional role only if an ablation demonstrates incremental net benefit. Spot indices lack traded volume: use a documented tradable volume source if calculating an index VWAP.

Cash-equity shorts need dated broker/product eligibility, circuit and cover assumptions. [SEBI's short-selling framework](https://www.sebi.gov.in/legal/circulars/jan-2024/framework-for-short-selling_80448.html) is the regulatory reference; the broker's actual allowed instruments and operational cutoff still need verification. Index spot cannot be bought or shorted directly; futures and options require their own executable prices, margin and cost models.

### Experiment order and acceptance

First audit costs and direction attribution on existing frozen reports. Then compare selection changes alone. Only then compare the three distinct entry patterns, each long-only and short-only, with a shared control and identical inputs/cost assumptions. Examine rejection funnels when there are no trades.

Use chronological development and untouched test periods, followed by forward paper observation. Require positive net expectancy and profit factor above one on unseen data, report uncertainty with session-block resampling, and stress costs by at least 50%. A preferred additional safety margin such as PF 1.2 is a research choice, not a guarantee. Check yearly/regime concentration, symbol concentration, trade count, capital concurrency, turnover, intraday marked drawdown and participation feasibility. Preserve every trial and failure; do not select a favorable weekday or stock retrospectively and call it validation.

No new strategy was backtested in this review. Existing code and saved settings were left unchanged. The strongest current conclusion is that we have not demonstrated a deployable intraday edge, and further indicator stacking has lower priority than these diagnostics.

## Deployment and database operations

The runbook retains dated deployment evidence. Current deployment/database summaries follow it. Local source changes do not prove deployment. Application and database backups are independent; neither substitutes for off-server recovery. Restore into an isolated target and validate checksums/accounting before deliberate replacement.

### Environment boundaries and final decisions

| Concern | Local | Production |
|---|---|---|
| Source | Shared repository main | Same shared source main |
| TRADER_ENV | local (default) | production, explicitly set by Compose |
| Market data, screens, backtests, jobs | Independent local files | Independent production files |
| Swing paper/API/scheduler | Hidden/blocked; no weekday scheduler | Enabled capability; owner creates/configures portfolio |
| Token | Own Settings save/private file | Own Settings save/private file |
| Data root | repository/data by default | Host /srv/trader/data → container /state/data |
| Private root | DATA/private by default | Host /srv/trader/private → container /state/private |
| URL | http://127.0.0.1:8765 | https://trader.manojmathivanan.com |
| Login | Optional Basic Auth, normally unset | No website authentication, explicitly owner-selected |

Production starts fresh. Do not seed it from local candles, screens, settings, runs, paper
ledgers or credentials. Subsequent deployment updates retain production files. Trader still uses independent JSON; the separately authorized PostgreSQL archive imports existing market inputs without merging application/portfolio state. No automatic application-state synchronization exists. Both environments use the same algorithms, schemas and UI source. Local research/backtests
may run independently; only the production process owns paper activity. Do not infer runtime mode
from the hostname: TRADER_ENV controls paper availability; TRADER_PUBLIC_ORIGIN controls proxy
hostname/origin acceptance. Neither variable establishes authentication.

GitHub contains code, tests, pinned dependencies, vendored licensed frontend library, architecture
and deployment configuration only. Exclude data/, artifacts/, .env/other environment secrets,
.local-key, private keys, provider tokens, paper ledgers, downloaded candles and backups. There is
no server-data branch in the final design and no nightly Git commit/push. Only shared-source
updates are committed. The server pulls the public repository over HTTPS without a GitHub secret.
The proposed write deploy key was never registered and is not needed.

### Deployed infrastructure inventory (observed 4 October 2026)

| Item | Recorded value |
|---|---|
| Public source repository | https://github.com/manoj-mathivanan/trader_all |
| Deployed source baseline before this documentation reconciliation | bfdc756e483abd58faa98fd08b86fcc3e32df9be |
| DigitalOcean Droplet | manoj-projects, ID 605977148 |
| Region / OS | Bangalore BLR1 / Ubuntu 24.04 LTS x64 |
| Plan | Basic Regular shared CPU; 1 vCPU, 1 GB RAM, 25 GB SSD |
| Recorded price | USD 6/month before taxes/additional charges; historical quote, not a guaranteed future price |
| Public / private IPv4 | 143.244.142.226 / 10.122.0.2 |
| SSH | root, port 22; ED25519 login verified |
| Swap | 2 GB /swapfile, persisted in /etc/fstab |
| Domain | manojmathivanan.com, Cloudflare registrar and DNS |
| DNS | A, name trader, IPv4 143.244.142.226, DNS-only, TTL Auto |
| Application | https://trader.manojmathivanan.com |
| Parent domain / www | Reserved for future personal site and multiple projects; not routed by this deployment |
| Domain expiry / renewal | 4 October 2027; auto-renew scheduled 4 September 2027; recorded renewal USD 10.46/year |
| Supervision | docker.service and caddy.service enabled; Compose restart unless-stopped |
| Firewall | UFW enabled; allow TCP 22, 80, 443 and UDP 443; equivalent IPv6 rules |
| Provider backups / monitoring | Paid automated Droplet backups not enabled; free monitoring enabled |

Provider account payment methods were added by the owner, and domain payment was completed by
the owner. This document contains no payment information or account authentication credentials.
Rebuilding or replacing a Droplet may change its IP and SSH host key; update DNS and verify the
new host fingerprint instead of treating the recorded identities as permanent.

### SSH access and account recovery

Existing local private key: C:\Users\maman\.ssh\manoj_projects_ed25519; public key is the
same path with .pub. Registered name: manoj-projects-deployment. Login-key fingerprint:
SHA256:O/fcFIlXPeA+8cFT9Qwej1Sps2BWqX4IahLYYC9wR/g. The key has no passphrase;
preserve the private key separately in protected storage. A public key/fingerprint cannot log in.
Recorded server ED25519 host fingerprint:
SHA256:8Hf+8ajN6hE5PN/5fDOPF5z45TtYXkUfNVgENk2wRRQ.

For replacement infrastructure without a surviving login key, generate a new ED25519 pair
with ssh-keygen, choose its passphrase interactively, and register only its public .pub file
when creating the new Droplet. Do not overwrite a surviving key. The new key/fingerprint will
differ from this record; preserve it securely and update the recorded identity. A new key alone
does not restore access to the existing server without console/account recovery authorization.

```powershell
ssh -i "$env:USERPROFILE/.ssh/manoj_projects_ed25519" -o IdentitiesOnly=yes root@143.244.142.226
```

On another computer restore the protected private key, restrict access to its owner (chmod 600
on Linux/macOS), and use ssh -i /path/to/key -o IdentitiesOnly=yes root@143.244.142.226.
Preserve DigitalOcean/Cloudflare account access, registered email and two-factor recovery codes
separately. If the SSH key is lost, use DigitalOcean console/recovery access to replace the
Droplet's authorized key. Adding a key only to the DigitalOcean account does not retrofit the
existing Droplet. Never embed a private key, token, password or recovery code into this document.

### Exact application changes required for the two environments

At module startup dashboard/api/main.py reads TRADER_ENV, default local; accept only local or
production, otherwise raise RuntimeError. Set PAPER_ENABLED = (ENVIRONMENT == 'production').
PUBLIC_ORIGIN is TRADER_PUBLIC_ORIGIN with trailing slash removed; if supplied it must be an
HTTPS origin with a hostname, no path/query/fragment/username. Optional Basic Auth requires
both administrator variables or neither; supplying only one fails startup.

Lifespan always runs jobs.recover(). Only production runs scheduler.recover_interrupted() and
scheduler.start(). Hold the returned Event/thread; on shutdown set the Event and join(timeout=2).
Local must not recover schedule claims or create/start a schedule thread. Tests can exercise the
shared engine directly in isolated fixtures; that is not local runtime paper enablement.

Before dispatch, local middleware returns 403 with detail 'Paper trading is available only in
production.' for /api/paper/*, /api/jobs/paper and /api/strategies/*/paper/*, including GET.
Bootstrap additionally returns environment, paper_enabled and remote_enabled. In local mode
paper_portfolio is null and paper_portfolios is {}; schemas remain available for shared code.
Production returns its own stored portfolios. paper_enabled does not mean auto_run is true.

The frontend filters Paper trading from navigation when paper_enabled is false; direct #paper
falls back to Overview. Overview's local execution hint says paper trading runs in production.
Render the .local-status label as Production workspace or Local workspace using environment.
The paper form describes automatic cycles running while the production server is running.
Settings reports local/remote workspace, configured login status and simulated execution.
Preserve responsive navigation; tested phone viewport was 390×844, with no page-width overflow.

Uvicorn listens on loopback only. Production uses host networking so host Caddy can reach it.
Trust proxy headers solely from 127.0.0.1. Caddy strips X-Forwarded-For so middleware sees the
loopback peer while retaining the forwarded HTTPS scheme. Allow the configured public hostname
alongside local/test hosts. Mutating requests require X-Trader-Request: local-ui and, if Origin
is present, the exact public HTTPS origin for the public host or base origin for a local host.
Keep nosniff, DENY frames, no-referrer/no-store and safe validation errors. These controls do not
prevent an unauthenticated visitor from using the public UI or its allowed APIs.

### Exact private-token persistence contract

store.private_dir() dynamically resolves TRADER_PRIVATE_DIR or DATA/private. save_token(value)
uses the process RLock, creates the private directory, writes upstox.tmp as UTF-8 JSON with
{access_token: value, saved_at: UTC ISO timestamp}, chmods the file 0600, flushes/fsyncs, and
atomically replaces upstox.json. The production directory is mode 0700 and UID/GID 10001.
The filesystem, not new encryption, protects newly saved plaintext tokens. Windows private-file
ACLs also depend on the user profile/filesystem; POSIX mode numbers are not a Windows ACL promise.

token_saved() reports presence only. token() reads the private file, falling back to legacy
DATA/private/upstox.json; returns access_token if present, otherwise decrypts encrypted_token
with the original Fernet .local-key/TRADER_KEY_FILE. Keep cryptography only for legacy support.
No new Fernet token record is written. The UI gets saved status, never the token. PUT connection
reports that the token is saved and will be validated on the next data fetch. A saved token is
not proof it is valid. Owner's Upstox token expires daily; replace it through production Settings.
No automatic broker login/refresh or live order path exists. Production did not inherit the
local token. Private credentials are excluded from images, Git and data backup archives.

### Fresh-server installation sequence

Recreate the application and support files from this document first (or clone the public source).
Generate the frontend vendor files before building the Docker image if they are missing; the
image copies dashboard/web but does not execute npm. Python 3.13 and Node 22 were used for checks;
KLineChart is pinned to 9.8.12 and the Python dependency list is specified elsewhere in this doc.
On a fresh Ubuntu 24.04 server, after authorizing its SSH key and adding the DNS record:

```sh
apt-get update
apt-get install -y docker.io docker-compose-v2 caddy rsync python3 git ufw
git clone https://github.com/manoj-mathivanan/trader_all.git /opt/trader
cd /opt/trader
bash deploy/bootstrap.sh
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable
cp deploy/Caddyfile /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy
docker compose up -d --build
install -m 755 deploy/backup.sh /usr/local/sbin/trader-backup
cp deploy/trader-backup.service deploy/trader-backup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now trader-backup.timer
```

Allow SSH before enabling the firewall. Adapt the hostname/IP for replacement infrastructure.
Caddy obtains and renews the public HTTPS certificate; public DNS and inbound 80/443 must work.
No Cloudflare proxy, external database, Redis, GitHub token, GitHub deploy key or SSH agent on the
server is required. bootstrap.sh retains an unused snapshots directory from earlier preparation;
its existence does not enable a Git snapshot service. Do not install the abandoned snapshot timer.

Confirm health using curl -fsS https://trader.manojmathivanan.com/api/bootstrap and Docker/Caddy
logs. Expect environment=production, paper_enabled=true, auth_enabled=false; a fresh installation
has token_saved=false, zero runs and zero loaded instruments. Defaults are schema settings, not
downloaded history. In Settings save a production token and desired research universe, then
Refresh universe → Fetch missing data. Only after real coverage exists create a production
paper portfolio with explicit capital/acknowledgment; enable auto_run only if chosen by the owner.
No code deployment automatically allocates capital, creates a portfolio or enables automatic runs.

### Backups, archive format and restore

The systemd backup timer runs at 20:00 UTC (01:30 IST the following calendar day), randomized by
up to 120 seconds, Persistent=true. This is unrelated to the weekday paper schedule. The oneshot
service timeout is 3600 seconds. A flock on /run/trader-backup.lock prevents overlapping backups.
The script checks jobs.json and defers with a nonzero exit if a job is queued/running; it does not
automatically retry immediately. After completion run systemctl start trader-backup.service.
The pre-stop active-job check is not an atomic admission lock: avoid initiating work during the
backup window; a job queued between the check and stop can be interrupted and recovered normally.

For a consistent file copy, stop the trader container, install an EXIT trap to restart it, and
export non-secret JSON and archived financial source HTML into /srv/trader/backup-state.
Ignore private paths and ephemeral .tmp/.lock files. HTML is allowed only at
company/filings/<sha256>.html and its bytes must match that filename; reject other file types.
Hash exact file bytes with SHA256. manifest.json is
{version: 2, files: {relative_filename: lowercase_64_character_sha256}}; blobs/<sha>.json.gz
or blobs/<sha>.html.gz holds the original bytes compressed with empty gzip filename and mtime=0.
Identical bytes of the same file type share one blob. JSON must parse; both types pass
credential-key/JWT scans. Write blobs/manifest via temporary files and atomic replace; remove
unreferenced blobs. Restore supports legacy version 1 JSON archives and version 2 mixed archives,
requires an empty destination, confines paths, excludes private files and verifies every hash.
These scans are safeguards, not a general guarantee that arbitrary text contains no sensitive data.
The first backup after the October 9 fundamentals pull exposed the old JSON-only rejection of
financial HTML. The version 2 format fixes that failure without changing live data formats.
Regression tests cover mixed-file round trips, legacy restore, credentials, corrupt blobs,
unsafe paths and invalid filing names/checksums.

Archive that complete staging set to /srv/trader/backups/data-<UTC timestamp>.tar.gz. Cleanup
removes matching archives older than seven days using find -mtime +7 (mtime-day semantics, not
an exact seven-archive count). The script makes no Git call and never copies the private token.
Only backups deduplicate/compress inputs; live run_data/<run_id>.json still saves full candle
inputs per backtest. Do not silently change live formats while rebuilding from this document.

Backups currently reside on the same VPS, so server/disk loss can lose both data and backups.
No off-server destination or paid provider backup was configured. Download selected archives
separately until an off-server plan is selected. Local research backups are independent and not
scheduled by the production timer. Re-enter credentials after disaster recovery.

```sh
systemctl start trader-backup.service
journalctl -u trader-backup.service -n 50 --no-pager
systemctl list-timers trader-backup.timer
```

To restore, select a trusted complete archive and extract it into an empty staging directory.
Keep the application stopped when switching data. Never overwrite the current live ledger as a
deployment troubleshooting shortcut. Check capacity and preserve current state before switching:

```sh
mkdir -p /srv/trader/restore-snapshot
tar -xzf /path/to/chosen-data-archive.tar.gz -C /srv/trader/restore-snapshot
cd /opt/trader
python3 deploy/data_snapshot.py restore /srv/trader/restore-snapshot /srv/trader/restored-data
docker compose stop trader
mv /srv/trader/data /srv/trader/data-before-restore
mv /srv/trader/restored-data /srv/trader/data
chown -R 10001:10001 /srv/trader/data
docker compose up -d
```

Use fresh empty restore directories, not directories from a previous restore attempt; ensure
data-before-restore does not already exist, or choose a distinct dated preservation path. The
restorer accepts manifest version 1, validates filename containment, excludes private paths,
requires .json destinations and 64-character hexadecimal hashes, decompresses files and checks
every output SHA256. Existing nonempty restore destinations are rejected. This verifies archive
content integrity, not authenticity of an untrusted archive. Original private credentials remain
separate; do not copy local ones implicitly. Retain the old data until restored health/history
is verified; move it off-server first if there is insufficient disk space for two copies.

### Source updates, operation and verification

Normal source update: run a successful backup, pull main with --ff-only and rebuild. Keep data
and private bind mounts outside /opt/trader. Do not deploy unrelated local work or replace the
production data directory from a checkout. There is no automatic GitHub-to-VPS deployment.

```sh
cd /opt/trader
git pull --ff-only origin main
docker compose up -d --build
docker compose ps
docker compose logs --tail 100
systemctl status caddy --no-pager
df -h /
free -h
```

GitHub Actions runs Python tests and npm checks/tests on main pushes and pull requests, with no
deploy job or credential. Deployment-thread evidence: 47 Python tests passed locally and in the
Linux Docker image; npm syntax and screen-preset tests passed. Tests explicitly assert that local
paper routes return 403, local scheduling is never started/recovered, and production starts/stops
one scheduler. Remote-origin/private-token separation is tested without leaking tokens. Public
HTTPS bootstrap, desktop/390×844 mobile UI, production paper controls, container rebuild/restart
and a manual empty-state production backup were verified. The manual backup exited successfully
and restarted the container; no funded portfolio cycle or populated production restore was run.
Do not describe unobserved GitHub CI status or a populated disaster-recovery rehearsal as passed.

At deployment cutover local research retained 112 backtests and 500 instruments; production
started with no history/token/portfolio. These are dated observations, not fixed UI values or
promises that production will remain empty. Local source update preserved its existing files.

Size investigation: local candles were approximately 0.164 GiB, run reports 0.025 GiB, and 112
run-input files 12.019 GiB. Those input files contained 16 unique byte-identical datasets totaling
1.800 GiB, with 10.219 GiB duplicate bytes. The audit did not deduplicate live application files.
Git source objects were only about 291 KiB at that measurement. This motivated excluding data
from Git, not a shared database. Large backtests/history can exceed the smallest VPS's RAM/disk;
monitor capacity before expanding. Last fresh-state server check had approximately 19 GiB free
disk and 2 GiB swap; these figures change with usage and are not resource guarantees.

Operational evidence/access notes live in ignored artifacts/server-access.md and screenshots;
they are conveniences, not prerequisites to rebuild. Temporary local migration copies were
prepared before the owner selected a fresh production start; none were transferred into
production or published. Cleanup of that generated copy/partial archive was blocked by automatic
approval review, and the copies remained ignored under artifacts/migration and
artifacts/trader-data.tar.gz. An optional empty-body public token-write check was also blocked;
no credential was changed. These tool outcomes do not imply a failing application endpoint.

<a id="deploy-readme"></a>

## Trader MVP deployment

### Environment separation

The owner authorized remote research/paper hosting on 4 October 2026. Live broker execution remains deferred. Trader continues to read its environment's JSON data and private credentials. On 9 October 2026 the owner authorized a separate shared PostgreSQL market-data database on the same VM and an import of existing local/production market inputs. See [database deployment and import notes](architecture.md#deploy-market-data-readme). Completed market refreshes now sync automatically from local and production. Trader's source files and paper ledgers remain preserved; database-backed application readers are not enabled yet.

`TRADER_ENV=local` is the default. Local runs support market data and backtests, hide paper trading, reject paper API requests and never start the paper scheduler. `TRADER_ENV=production` explicitly enables paper APIs and the scheduler. Compose sets this for the VPS. A portfolio still must be created and configured in the production UI; no portfolio or automatic cycle is enabled merely by deploying.

### Runtime

DigitalOcean `manoj-projects`, Bangalore, Ubuntu 24.04, 1 vCPU / 1 GB RAM / 25 GB disk. Caddy terminates HTTPS for `trader.manojmathivanan.com`. Docker Compose runs one application process with the worker and production paper scheduler. Uvicorn binds only to `127.0.0.1:8765`; Caddy strips forwarded client IPs. Host and browser origin checks remain enabled. The website has no login by owner choice, so its research and paper actions are public. These checks are not authentication.

Install Docker, Compose, Caddy, Git and Python. Run `deploy/bootstrap.sh` and clone the public repository into `/opt/trader`. No GitHub credential or write deploy key is needed by the server. Copy `deploy/Caddyfile` to `/etc/caddy/Caddyfile` and reload Caddy. Cloudflare's DNS-only A record `trader` points to the VPS. The root domain remains reserved for future projects.

```sh
cd /opt/trader
docker compose up -d --build
```

### Files and credentials

- `/srv/trader/data`: production JSON research and paper state, owned by UID/GID 10001.
- `/srv/trader/private/upstox.json`: production plaintext UI-saved token, mode 600; directory mode 700. Enter a fresh token in the production Settings UI. It is excluded from Git, images and data backups.
- Local defaults remain `data/` and `data/private/` in the local checkout. Existing local histories remain intact; legacy encrypted token records are still readable with their original `.local-key`.
- GitHub `main` contains shared source, tests, dependencies, architecture and deployment configuration. No data branch, history, ledgers, backups, environment secrets or private keys are published. No server process commits or pushes to GitHub.
- Python does not load `.env` automatically. Supply process environment explicitly. Compose supplies production variables. Optional Basic Auth remains supported, but is not configured.

### Production backups

Install `deploy/backup.sh` as `/usr/local/sbin/trader-backup`, with the provided backup service/timer under `/etc/systemd/system`, and enable the timer. It runs around 01:30 IST, briefly stopping the container and restarting it with an EXIT trap. Active jobs defer the backup; run it manually after completion. The exporter checks JSON and rejects credentials, storing immutable content-addressed gzip blobs and a filename manifest. Identical candle snapshots share a blob; live application files retain their original format. Archives remain under `/srv/trader/backups` for seven days.

```sh
systemctl start trader-backup.service
systemctl status trader-backup.service
systemctl list-timers trader-backup.timer
```

Backups currently share the server's failure domain. They are not off-server disaster recovery. Provider backups were not purchased; download archives periodically until a separate backup destination is selected. Re-enter the Upstox token after a restore. Check `df -h` and `free -h` as datasets grow; large backtests may need a larger server.

### Updates and restore

Code updates leave live data directories intact. Back up before updating; fast-forward the public source branch and rebuild:

```sh
cd /opt/trader
git pull --ff-only origin main
docker compose up -d --build
```

For restore, extract the chosen archive into a temporary snapshot directory. Run `python3 deploy/data_snapshot.py restore /path/to/extracted-snapshot /srv/trader/restored-data`. The destination must be empty and every file's checksum is verified. Stop Trader, preserve current live data separately, move restored data into place, restore ownership to 10001, then restart. Never overwrite a current paper ledger simply because a code deployment failed.

Verify `/api/bootstrap`, Settings, charts, reports, production paper controls and mobile rendering after changes. Run exactly one server process without reload or multiple workers. Local research can run independently because local mode never schedules paper cycles.

<a id="deploy-market-data-readme"></a>

## Shared market-data database

### Automatic refresh synchronization — 9 October 2026

Completed `market_fetch.json` results trigger background database synchronization
in both environments. The server's `market-data-refresh.timer` checks every minute;
the Windows task `Trader Market Database Sync` does the same while the user session
can run tasks. Local bundles upload over SSH; only the server worker holds database
credentials. Transfers and imports add latency beyond the polling interval.
Existing provider downloads and JSON application/backtest readers are unchanged.

The worker selects market JSON written during the completed refresh, excludes frozen
run inputs, and normalizes only the requested daily/five-minute windows. Refreshed
files remain archived exactly. Partial provider results are retained; successful
observations still import. Failed transfers/imports retry. Identical completed
refreshes are not imported twice.

`market.refreshes` records environment, job ID, provider refresh start/completion,
database synchronization time and the original result. Candles retain `fetched_at`.
`market.fundamentals` stores each current full record with `last_checked_at` and
`last_pulled_at`; older checks cannot overwrite newer ones. Earlier fundamentals
were backfilled from the verified original database archives.

Server receipts/status live under `/srv/market-data/sync`; local receipts/status
live under `data/private/market-db-sync`. Inspect `progress.json`, `last-error.json`
and server `reports/`, or `journalctl -u market-data-refresh.service`. Completed
manifests/receipts remain; transfer payloads are removed after verification.
These workers do not initiate provider downloads or paid research.

Both last completed refreshes were synced and independently verified on 9 October:
production job `381c05672afa` and local job `b8b503e6e1b7`, with zero unmatched candles.
All 750 queryable fundamental records matched their source archives and timestamps.
Repeated observer runs left four completed imports total (two original bulk imports
and two refresh imports). Evidence: `artifacts/market-db/refresh-sync-verification.json`.

Install the supplied refresh service/timer under `/etc/systemd/system`, then run
`systemctl enable --now market-data-refresh.timer`. Run
`deploy/market-data/install_local_sync.ps1` on Windows with the appropriate SSH
target/key and data directory. The observer syncs the latest completed refresh;
it is not a durable queue of multiple refreshes completed while it is offline.

**Verified imported snapshot — 9 October 2026.** The completed local and production
imports cover 750 instruments, with overlapping identical provider candles deduplicated.
There are 1,429,437 daily candles (2016-10-03 through 2026-10-08) and 3,747,161
five-minute candles (2024-09-17 through 2026-10-08). These ranges describe available
cached observations, not continuous coverage for every instrument. The database
occupies approximately 2.44 GiB after import. Import reports and the independent
archive audit are retained under `/srv/market-data/imports`; original JSON remains
in place. The independent audit verified all 60,986 stored archives against their
source SHA256 and byte lengths; both imports have zero unmatched candles. The
streaming audit completed with a 145.5 MiB memory peak. Its local report is
`artifacts/market-db/database-verification.json`. Future data, maintenance and
backups need additional disk space.
The full post-import backup completed successfully at
`/srv/market-data/backups/market-data-20261009T111908Z.dump` (1,312,906,179 bytes).
Its archive listing passed `pg_restore --list`; a full restore has not been tested.
Normal server memory limits were restored, and Trader's bootstrap returned HTTP 200.

PostgreSQL runs independently of Trader on the existing DigitalOcean VM.
Deploy files live at `/opt/market-data`; persistent state lives at
`/srv/market-data/postgres`. The Trader container and its JSON source files are
preserved. Completed market refreshes sync into PostgreSQL automatically. Application/
backtest readers remain on JSON; provider downloads use the existing refresh flow.

The service binds **127.0.0.1:5432** only. Memory is capped at 320 MiB (448 MiB
including permitted swap), with 64 MiB shared buffers, 2 MiB work memory and
12 connections. Keep client pools small. Database passwords are generated on
the server in root-only `/srv/market-data/private` files; they are never in
Git, bundle exports or shell arguments.

### Contents

- `market.instruments`: current cached provider instrument metadata, keyed by ISIN.
- `market.candles`: validated daily (1440 minutes) and five-minute OHLCV bars,
  uniquely keyed by ISIN, interval and source timestamp in milliseconds.
- `market.daily_bars`, `market.five_minute_bars`, `market.coverage`: query views.
- `market.candle_revisions`: differing overlapping cached prices from either
  environment. The newest source `fetched_at` wins the current candle; equal
  timestamps keep the existing value. Conflicting versions remain inspectable.
- `market.blobs` and `market.source_files`: original market JSON bytes stored as
  SHA256-addressed gzip blobs and per-environment import manifests. This includes
  the cache source records, frozen daily/minute/fundamental backtest inputs,
  company/fundamental data, universe snapshots, metadata and provider repair
  evidence. Frozen derived prices never replace the provider candle tables.
- `market.imports`: source manifest, expected counts, checksums, coverage and
  completed verification record. A source universe snapshot is marked as the
  snapshot it actually is; it does not invent historical membership.

Tokens, private credentials, settings, paper portfolios, jobs, research report
outputs and application state are excluded. These continue to live in their
existing files. Retained source files make provenance and future migration
possible without losing repair/adjustment metadata.

### Provision and import

Copy this directory's files and `scripts/market_data_bundle.py` plus
`scripts/import_market_data.py` to `/opt/market-data`. Install `python3-venv`
if needed, then:

```sh
python3 /opt/market-data/provision.py
python3 -m venv /opt/market-data/venv
/opt/market-data/venv/bin/pip install -r /opt/market-data/requirements.txt
python3 /opt/market-data/market_data_bundle.py /srv/trader/data /srv/market-data/imports/production --environment production
/opt/market-data/venv/bin/python /opt/market-data/import_market_data.py /srv/market-data/imports/production --report /srv/market-data/imports/production-verification.json
/opt/market-data/venv/bin/python /opt/market-data/create_reader.py
```

Local export needs only standard-library Python:

```powershell
.venv/Scripts/python.exe scripts/market_data_bundle.py data artifacts/market-db/local --environment local
```

Transfer the bundle privately over SSH, then import it with the same importer.
For a large tar bundle, `import_uploaded_bundle.py` can run as a transient systemd
job, wait for its known byte size, safely unpack the five allowed payload files,
and continue independently of the SSH connection. Run it with the bundle's
directory name and tar byte size; inspect progress with `journalctl -u
market-data-import-local.service`. The initial import job is limited to 256 MiB
plus up to 256 MiB swap and runs with lower CPU priority.

If an SSH upload drops, `resume_upload.py inspect` reports its byte count and
SHA256. Compare that prefix against the local original, transfer only the
remaining suffix, then use `finish` with prefix/suffix/full-file checksums.
It assembles and fsyncs a new file, checks the complete SHA256, and publishes
it atomically. Never append unverified bytes to a market bundle.

Export destinations must be empty. Checksums cover source bytes and all CSV
payloads. Source files changing during an export halt it. Imports use a database
advisory lock. Archives commit in bounded resumable batches; canonical candles,
coverage verification and completion commit together. Duplicate source candle
keys, invalid OHLCV or incomplete verification abort the candle transaction.
Re-running an already completed identical manifest returns its stored result.

### Read access and queries

`market_reader` is a read-only role group. `market_research` is a verified login
in that group with default read-only transactions and a 120-second statement
timeout. Its password lives at `/srv/market-data/private/reader_password`.
Additional projects should receive their own login/password or authenticated
API key when their integration is implemented. Do not expose PostgreSQL publicly.

An SSH tunnel supports private local access before the shared HTTPS API exists:

```powershell
ssh -N -L 15432:127.0.0.1:5432 -i "$env:USERPROFILE/.ssh/manoj_projects_ed25519" root@143.244.142.226
```

Connect a PostgreSQL client to `127.0.0.1:15432`, database `market_data`, using
the read-only login. Keep credentials outside code. Example SQL:

```sql
SELECT session_date, timestamp_ms, open, high, low, close, volume
FROM market.five_minute_bars
WHERE isin = 'INE001B01026'
  AND timestamp_ms >= 1790567100000 AND timestamp_ms < 1790653500000
ORDER BY timestamp_ms;

SELECT * FROM market.coverage WHERE isin = 'INE001B01026';
SELECT environment, status, verification FROM market.imports;
```

The timestamp range uses the primary index; batch reads into local memory/cache
for simulation rather than issuing one remote query per candle.

### Backups

`backup.sh` creates a consistent PostgreSQL custom-format dump while the app
continues running, checks its archive listing, and keeps about three days of dumps.
The dump client runs in a separate container capped at 256 MiB (384 MiB with swap).
For PostgreSQL's large BYTEA COPY buffers, the server temporarily permits 512 MiB
(768 MiB with swap); an exit trap restores its normal 320/448 MiB limits. This
maintenance window still runs on the existing 1 GB VM using its configured swap.
Install it as `/usr/local/sbin/market-data-backup` with the accompanying systemd
service/timer. The timer runs at **02:30 IST** (21:00 UTC on the preceding day).
This timer backs up PostgreSQL; it does not download fresh market data.
Backups remain on the VM until an off-server destination is configured.

```sh
systemctl start market-data-backup.service
docker compose -f /opt/market-data/compose.yaml ps
docker compose -f /opt/market-data/compose.yaml logs --tail 30 postgres
df -h /
free -h
```

Keep the imported manifests and verification reports. Compressed transfer
bundles can be removed after database checksum verification and a successful
backup, preserving all original local/production JSON files. A restore should
target a separate database for validation before any deliberate replacement.

<a id="core-market-data-readme"></a>

## Upstox feed schema

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

## Proposed restructuring and future scope (not implemented)

The 9 October review recommends incremental improvements: separate workspace navigation from strategy selection; prioritize freshness/connection/jobs/exposure on Overview; bookmark experiment/report/trade flows; group forms by dataset, signals, sizing, exits and costs; compare parameter/input differences; retain saved-screen access on mobile. No framework rewrite is required.

Split frontend into shell/routing/state, shared API/formatting/forms/tables/charts and feature modules. Extract FastAPI routers. Move strategy-specific config/signals/simulation under strategies, shared services under core. Introduce candle/run/evidence/portfolio repositories. Extend registry capability declarations for scan/backtest/paper/timeframe/environment support. Preserve shared execution/risk, atomic writes, locks, frozen inputs and provenance.

Long-term requirements retained from the original roadmap:

- Personal single-owner NSE/BSE platform, no SaaS/managed money/colocated HFT. Futures/options require distinct executable inputs/models.
- One independent portfolio per strategy with its own capital/sizer/broker/ledger. Future paper-to-live transition would preserve one record and mode-tagged history; transfers/live transitions remain unimplemented.
- Shared instrument/provider interfaces across daily/intraday/ticks/options, delisted/merged identity and dated membership; pluggable percent-risk and later Greeks/premium-risk sizing.
- SQLAlchemy/Alembic application storage, evaluate Timescale only when justified. Separate plain PostgreSQL market archive is an initial phase, not full migration.
- Proposed entities: instruments/subtypes, daily/intraday/ticks/option chains, strategy/config versions, portfolios/broker accounts, orders/positions/trades/equity and jobs/logs/membership.
- Optional Redis events/RQ queues with separate API/worker/batch/market-hours streaming services and structured tracked manual/timer jobs. Existing quote paper does not imply Redis/RQ.
- Schema-driven per-strategy config/portfolio/data/jobs; routine tuning without deployment. A combined-strategy tab is a separate future feature.
- Per-portfolio broker adapter place/modify/cancel/status/positions; account-level capacity if independent portfolios share a live broker account.
- Shared risk/stop/cost code per strategy's backtest/paper/live with independent parameters/capital; dated brokerage/taxes/caps and measured adverse fills.
- Live protection requires resting exchange/broker stop orders, mandatory restart and periodic reconciliation, halting on mismatches. Software polling alone is insufficient.
- Future encrypted broker credentials/authentication/optional 2FA/rate limits/Telegram alerts need explicit decisions. Public hosting does not authorize new paid/live exposure; production paid company research already requires Basic Auth.
- Phases: honest reproducible data/research, frozen validation, forward paper, explicit storage/queue migration, separately authorized live adapters, then further products. Backtests never auto-promote strategies.
- Cheap single VPS remains target; monitor memory/disk, preserve histories and establish off-server backups. Root domain/other projects remain separate.
- Pending: Momentum paper/live, options, shared market API/database-backed readers, complete demerger entitlements, historical membership, executable liquidity and off-server recovery.
- Future-only DATABASE_URL/REDIS_URL/live broker/Telegram names do not configure current app; no placeholder credentials/runtime services are implied.

<a id="intraday-cost-diagnosis"></a>

## Intraday momentum cost diagnosis — 9 October 2026

Twenty-one full simulations on identical frozen inputs, 8 October 2024–7 October 2026. Reference `836c4463d21b`. No downloads or default changes. Baseline replay matches recorded equity, fees, slippage and every trade exactly.

Direction-only portfolios select their own qualifying stocks and size from their own capital. They are not the buy/sell attribution of the combined portfolio. Every run starts at Rs 1,000,000.

| Cost scenario | Combined return | Buy-only return | Short-only return |
|---|---:|---:|---:|
| Original flat costs; 10 bps slippage/side | -50.36% | -39.23% | -30.64% |
| Zero fees and zero slippage | +10.49% | +6.96% | +17.24% |
| Public Upstox fees; zero slippage | -3.74% | -2.86% | +7.13% |
| Public Upstox fees; 2 bps slippage/side | -11.51% | -7.98% | +1.04% |
| Public Upstox fees; 5 bps slippage/side | -22.25% | -16.01% | -7.12% |
| Public Upstox fees; 10 bps slippage/side | -38.32% | -28.72% | -19.25% |
| 150% public fees; 15 bps slippage/side | -52.64% | -40.63% | -31.68% |

### Profit factor and trade counts

| Scenario | Combined PF / trades | Buy-only PF / trades | Short-only PF / trades |
|---|---:|---:|---:|
| Original flat costs; 10 bps slippage/side | 0.546 / 1316 | 0.539 / 916 | 0.590 / 843 |
| Zero fees and zero slippage | 1.083 / 1316 | 1.079 / 916 | 1.232 / 843 |
| Public Upstox fees; zero slippage | 0.969 / 1316 | 0.967 / 916 | 1.097 / 843 |
| Public Upstox fees; 2 bps slippage/side | 0.905 / 1316 | 0.908 / 916 | 1.014 / 843 |
| Public Upstox fees; 5 bps slippage/side | 0.813 / 1316 | 0.815 / 916 | 0.905 / 843 |
| Public Upstox fees; 10 bps slippage/side | 0.669 / 1316 | 0.667 / 916 | 0.744 / 843 |
| 150% public fees; 15 bps slippage/side | 0.530 / 1316 | 0.528 / 916 | 0.581 / 843 |

### Calendar-period attribution

| Scenario / direction | 2024 partial | 2025 | 2026 partial |
|---|---:|---:|---:|
| zero_cost / both | +8.46% | +1.79% | +0.08% |
| zero_cost / long | +6.17% | -0.03% | +0.78% |
| zero_cost / short | +3.50% | +12.16% | +0.99% |
| public_fees_slip_2 / both | +6.02% | -9.00% | -8.28% |
| public_fees_slip_2 / long | +4.54% | -7.45% | -4.89% |
| public_fees_slip_2 / short | +2.28% | +4.15% | -5.15% |
| public_fees_slip_5 / both | +5.03% | -15.23% | -12.67% |
| public_fees_slip_5 / long | +3.79% | -11.94% | -8.10% |
| public_fees_slip_5 / short | +1.77% | -0.61% | -8.17% |

### Uncertainty diagnostics

| Public fees + 2 bps/side | Mean daily return | 95% block interval |
|---|---:|---:|
| both | -0.0239% | -0.0577% to +0.0115% |
| long | -0.0162% | -0.0465% to +0.0147% |
| short | +0.0026% | -0.0251% to +0.0303% |

Moving blocks: five consecutive sessions, 2,000 resamples, fixed seed. These intervals describe arithmetic daily-return uncertainty in an inspected sample. They do not resolve survivorship, exclusions, model selection or executable-fill bias.

### Cost model and interpretation

[Upstox public fee schedule](https://upstox.com/brokerage-charges/) checked 9 October 2026. Model assumes basic brokerage min(Rs 20, 0.1% notional) per order throughout this history; actual historical account plans are unverified. Cash intraday STT applies to sells, stamp duty to buys; exchange rates change on 1 March 2026. IPFT and SEBI levies are included; GST on applicable fees is modeled conservatively. Contract-note rounding, promotions, forced square-off fees and account-specific charges are excluded.

Exact nonlinear fees affect the simulated quantity, reserved capital and stop-risk budget, as well as final P&L. Slippage affects fills and protective levels; reducing it is a sensitivity experiment, not an assertion that such fills are attainable. The stress case multiplies charges by 1.5 and raises slippage from 10 to 15 bps/side.

### Limits and next research

This is the existing ORB setup, not a test of VWAP pullbacks or failed breakouts. Current constituents, explicit corporate-action exclusions, session-end drawdown and unverified short/circuit/participation constraints are inherited. All historical periods have already been inspected. Before claiming improvement, use a distinct untouched period and observed paper fills.

If profits disappear with public fees even at zero slippage, prioritize signal/selection changes. If they survive fees but disappear with small slippage, execution quality and expected movement are binding. A less negative result remains a loss, and a positive zero-cost result does not establish a tradeable edge.

Next controlled experiment: broaden liquid-stock selection without changing the entry setup, then test VWAP pullback/rejection as a separate strategy. Keep all cost assumptions and candidate thresholds declared before outcomes.

### Reproduction

`.venv/Scripts/python.exe scripts/research_intraday_costs.py 836c4463d21b` followed by `.venv/Scripts/python.exe scripts/report_intraday_costs.py`.

Raw run ledgers, equity curves and summary are retained in `artifacts/intraday_cost_research/`; these reference the original frozen daily/minute hashes rather than duplicating inputs.


## Sector-filter implementation

Source added in the shared checkout during this consolidation: core/research/sector.py, Swing engine/paper integration and UI/API controls. This is a source snapshot, not confirmation of deployment or profitable comparison results.

- Modes: off (default), trend, trend_rs. Only long Swing next_open research supports enforcement; bearish and intraday Swing reject it.
- Fetch explicitly downloads 21 official sector constituent CSVs: Bank, Financial Services, IT, Auto, Pharma, Healthcare, FMCG, Metal, Realty, Oil & Gas, Consumer Durables, Capital Goods, Cement, Chemicals, Commercial & Transport Services, Construction, Consumer Services, Media, Power, REITs & Realty, Telecommunications. `core/research/sector.py::INDICES` defines the exact official constituent filenames; each downloaded source retains URL, SHA256, rows and capture time. Exact ISIN membership is preferred. Bank takes precedence over Financial Services, Pharma over Healthcare and Realty over REITs & Realty only for verified membership overlaps. Otherwise an explicit broad benchmark can resolve Financial Services -> financial, Healthcare -> healthcare, Capital Goods -> capital_goods, Chemicals -> chemicals, Construction -> construction, Consumer Services -> consumer_services, Services -> commercial_transport, Power -> power, Telecommunication -> telecom, Media Entertainment & Publication -> media. The issuer's official label must also occur in that benchmark's downloaded constituents; do not infer a bank or pharmaceutical company from a broad label. Remaining uniquely matching labels can use a benchmark proxy, except Cement and REITs & Realty require exact membership because their broader labels include other businesses. Ambiguity remains unmapped. Download/CSV failure retains the entire previous mapping; no partial classification is saved.
- Daily sector indices and Nifty 500 benchmark use exact Upstox NSE_INDEX identity; annual fetch chunks isolate defective years. Previous valid data remains on failures, but is not represented as fresh.
- Signals use the completed stock signal date. trend requires close strictly above its 50-session mean and that mean strictly above the mean 20 observed sessions earlier; minimum 70 observations. trend_rs additionally requires positive sector-minus-benchmark 63-session return, with exact matching session dates. Missing mapping/session/warmup/benchmark blocks enforced entries.
- Current constituent/industry classifications introduce historical mapping bias; pre-launch index backfills are unverified. No historical classification is invented.
- Snapshots freeze mappings, prices, capture times, version, notice and SHA256. Replays reject changed/missing evidence. Research saves run_sector/<id>.json, report references and candidate decision checks.
- Compare sector filters runs off/trend/trend_rs against a long Swing next-open reference with identical frozen stock, financial and sector evidence. Failures are retained; defaults are not automatically changed.
- Swing paper has sector_observe_only=true by default. If configured, decisions are journaled without blocking until enforcement is explicitly selected. Mapping freezes after the first successful context; processed sector-price revisions halt. paper_sector/<job-id>.json and each cycle retain evidence/checks. Existing accounting is preserved.
- APIs: GET /api/sectors audits current mappings/index histories; POST /api/jobs/sectors fetches; POST /api/jobs/sector-comparison takes reference_id. Bootstrap includes sector_fetch and latest 20 sector_comparisons. Tracked actions share the single-job worker.

### Local sector mapping expansion, 9 October 2026

Mapping contract version is `sector-trend-v2`. Mapping rows retain `isin`, `industry`, `index`, `method`, `official_member`, `candidates`, and `status`. `official_member=true` means exact ISIN membership in the selected index's official CSV. `method=broad_sector_benchmark` or `unique_industry_label` can select a proxy without asserting index membership. Mapping status describes classification coverage, independently of available index candles or signal eligibility. Existing frozen research/paper snapshots remain unchanged and retain their captured mappings.

`scripts/refresh_sector_mapping.py` refreshes the local `niftytotalmarket` mapping using public official CSVs without a broker token or fetching prices. It saves a recoverable prior mapping at `sector/mapping_before_expansion.json`, then records newly mapped symbols, unresolved symbols/industries, and missing index-price counts at `sector/mapping_expansion.json`. All 21 sources must validate before the live mapping is atomically replaced. Normal sector fetch uses this same mapping function and separately fetches prices through exact Upstox index identities; failures preserve prior prices and mark the fetch partial.

Local result: 439 of the previously unmapped 457 stocks were resolved, increasing coverage from 293 to 732 of 750. No previously mapped stock became unmapped. The remaining 18 have labels but lack an appropriate supported benchmark: Textiles (ARVIND, GOKEX, ICIL, KPRMILL, KITEX, PDSL, PAGEIND, PGIL, RAYMONDLSL, TRIDENT, VTL, WELSPUNLIV); Utilities (EIEL, IONEXCHANG, REFEX, WABAG); Diversified (GODREJIND); Forest Materials (JKPAPER). Do not substitute an unrelated broad-market/thematic index just to reach 100% coverage.

Prices were requested for 8 October 2025 through 8 October 2026, retaining older valid caches. New usable Upstox histories: Cement and REITs & Realty from 11 May 2026 (105 bars each), Chemicals from 10 November 2025 (227 bars), Media from 8 October 2025 (248 bars), all ending 8 October 2026. These are observed provider history boundaries, not verified launch dates. Capital Goods, Commercial & Transport Services, Construction, Consumer Services, Power and Telecommunications were absent from the retrieved Upstox NSE_INDEX catalog. Consequently 246 mapped stocks still lack their selected benchmark's candles; enforced sector gates block these entries. A mapping alone does not establish full-year historical sector data or sufficient warmup on earlier dates. These counts supersede the earlier 457-unmapped snapshot for the local workspace; they do not assert a production update.

Validation includes broad-financial/healthcare proxy assignment without narrow business inference, exact constituent overlap resolution, rejection of Cement proxies for nonmember Construction Materials companies, retaining mappings on incomplete downloads, missing-index-price gate rejection, and existing frozen replay/paper tests.


### Nonlinear intraday fee research contract

core/research/intraday_costs.py defines upstox_cash_fees(price, quantity, side, day, multiplier=1), an explicit hypothesis for dates from 1 October 2024 onward. It rejects invalid side, nonpositive/nonfinite notional, quantity below one, and negative/nonfinite multiplier. Brokerage is min(20 INR, 0.001 * notional). Exchange charge is 0.0000297 * notional before 1 March 2026 and 0.0000307 after; IPFT is respectively 0.000001 and 0.000000001 * notional. SEBI levy is 0.000001 * notional; sell-only STT is 0.00025; buy-only stamp is 0.00003. GST is 18% of brokerage + exchange + IPFT + SEBI, then the multiplier applies to all fees. Contract-note rounding, actual historic plans and special/DP/forced-square-off costs remain unverified/excluded.

Momentum simulate accepts an optional fee_model callback. Custom fees must be finite/nonnegative and are applied to slipped prices. Largest integer quantity satisfying exact nonlinear stop-risk and allocated-notional limits is found by bounded binary search; the callback must be nondecreasing with quantity. This research path requires breakeven trailing disabled. Default fee behavior is preserved when no callback is supplied. The 21-run suite explicitly uses separate capital/direction simulations, identical frozen data and baseline replay verification; it is not a sign flip or cost add-back.

<a id="intraday-selection-research"></a>

## Intraday stock-selection comparison — declared 9 October 2026

Compare prior-turnover scan sizes 50 and 200 on February 2025, June 2025 and January 2026. Daily inputs and exclusions come from frozen two-year reference `836c4463d21b`. The current strategy already ranks eligible stocks by same-clock opening relative volume; this experiment broadens the pool available to that ranking, rather than introducing a new volume indicator.

Run combined, long-only and short-only standalone portfolios at both 2 and 5 bps adverse slippage per side, with the public Upstox cash-equity fee hypothesis from the cost diagnosis. Preserve all opening-range, ATR-stop, entry/cutoff, capital, position-limit and relative-volume settings. Thirty-six declared simulations; no grid search or default promotion.

Requested windows: 3–28 February 2025; 2–30 June 2025; 2–30 January 2026. Observed sessions depend on the frozen daily source. Each month resets capital to Rs 1,000,000; adding monthly P&L is a diagnostic, not a compounded continuous portfolio.

Preflight found 345, 296 and 4,965 missing five-minute stock-sessions respectively for the 200-stock plans. Missing sessions may be fetched through the existing authenticated historical-data client. Cache inputs are normalized and checked for complete required session boundaries, then the full monthly input set is frozen and hashed. No daily replacements, silent symbol exclusions or invented candles are allowed. Failed downloads/audits remain failures.

These periods have already been inspected. This pilot tests selection sensitivity; it is not independent out-of-sample proof. Historical universe membership, broker short eligibility, circuits, executable volume, slippage and intraday peak drawdown remain unverified. A candidate must survive stronger cost assumptions and a distinct untouched period before promotion.

### Reproduction

`.venv/Scripts/python.exe scripts/research_intraday_selection.py`

Detailed ledgers, curves, input hashes and failures are saved in `artifacts/intraday_selection_research/`. Results are appended below after the declared suite completes.

This selection worker was active at cleanup, with its declaration retained above. Results are not yet represented as a completed suite. JSON checkpoints/ledgers remain the authoritative progress/result evidence. The preloaded worker still depends on the temporary root INTRADAY_SELECTION_RESEARCH.md; preserve it until that process completes. Future script invocations require an explicit --markdown path and no longer read a documentation template.


### Saved-data validation audit, 9 October 2026

A read-only 750-stock audit measured local and production caches through the saved completed
session of 2026-10-08. Its detailed stock inventories, dates, interval gaps, financial fields
and source-validation results are in artifacts/universe-audit/report.md, local.json and
production.json. No provider fetch, repair or deployment was performed for this audit.
Both environments have daily files and valid OHLCV arithmetic/timestamps for all 750 stocks.
EMBDL has 12 internal daily session gaps relative to the observed calendar, while 20 stocks
have shorter leading history without verified listing dates; these are not confirmed missing
pre-IPO candles. Verified exchange-listing metadata is absent for 253 stocks; only eight
stocks have separately verified IPO evidence. Local/production histories contain bars before
saved venue listing dates for eight/nine stocks respectively, requiring provenance review.
All 750 stocks have complete 75 five-minute intervals for each of seven observed sessions
between 2026-09-29 and 2026-10-08: 525 recent candles per stock. All retained five-minute
candles passed arithmetic, duplicate, order, identity and timestamp checks: 4,167,611 local
and 450,000 production candles. Neither environment has a one-minute cache. Completeness
was measured for the rolling ten-calendar-day window; older retained sessions were validated
but not certified as complete across their full calendar histories.
All 567 saved fundamental snapshots passed archived-source hash, identity and recalculated
metric validation; 183 stocks remain missing (118 unsupported financial issuers, 59 latest
quarter validation failures, six with no supported Ind-AS filings). Among the 567 validated
snapshots, missing fields are debt_equity 251, roe_pct 113, roce_pct 109, profit_growth_pct 107,
revenue_growth_pct 61, cash_profit_ratio 51, interest_coverage 25, promoter_pledge_pct 567,
auditor_concern 418 and governance_concern 567. Missing values remain unknown, not zero.
There is still no complete consecutive-quarter fundamental history.
All 750 stocks have current sector labels. Local sector benchmark mapping is a saved nifty500
snapshot: 217 mapped, 283 unmapped/ambiguous, 250 without rows. All 12 local sector/benchmark
index caches reach 2026-10-08; the Auto index rejected its 2018 fetch range for duplicates.
Production has no saved sector mapping or sector-index price caches. A sector label alone
does not establish a usable sector trend gate; current labels do not verify historical labels.
Price-gap review after existing evidence-based history preparation flags 10 local and 25
production stocks with >=35% discontinuities somewhere in retained history. In the latest
year HEGAM, INDIAGLYCO, TMPV and VEDL are flagged in both environments. PRIVISCL is already
quarantined for unresolved price continuity. Flags do not prove wrong prices or a corporate
action; all 750 records declare adjustment status unverified. Daily gap calendars were
saved benchmark sessions locally and majority-observed stock sessions in production, not
independently verified exchange holiday calendars. Never synthesize missing candles or infer
adjustment factors or listing dates from first prices to resolve these findings.


### Remaining-data refresh and one-year fundamental history contract (9 October 2026)


### Remaining-data refresh and one-year fundamental history contract (9 October 2026)

The owner requested the remaining data in both installations and selected one year of
quarterly fundamentals. Backfill the four most recent published financial quarters per
issuer; source comparables and annual filings may be older. Do not label incomplete
publication periods or unsupported filings as complete history. Previously recorded
567-snapshot/183-missing and 500-stock sector coverage counts describe the earlier audit,
not the final state after this refresh.
The parser supports exact official NSE INDAS, BANKING and NBFC_INDAS filing filenames,
with issuer ISIN/symbol, units, basis, dates and SHA256 validation. Company type follows
the filing taxonomy, not a blanket Financial Services exclusion. Primary P&L amounts
are scoped to the first reporting-period table, ending before the next reporting-period
header or segment revenue section. Conflicting values within that primary table still
fail; segment disclosures never replace quarterly results. BANKING revenue is Total
income and group PAT is Net profit (loss) for the period. NBFC revenue is Total Revenue
From Operations and PAT is Total profit (loss) for period. Quarter growth compares the
same quarter, basis and taxonomy after monetary unit normalization. ROE can use supported
annual PAT/average-equity evidence, but banks/NBFCs never receive industrial ROCE,
debt/equity, interest coverage or cash/PAT ratios. NPA, capital adequacy, pledge and
risk fields remain unknown unless independently supported; template zeros are not inferred
as sound risk metrics. Unsupported taxonomies (including unimplemented insurance forms)
remain incomplete instead of being coerced into these formats.
Run `python scripts/pull_fundamentals_history.py --quarters 4` with the installation's
TRADER_DATA_DIR. Optional --symbols limits an operational retry; --workers accepts 1–3
(default 3). Discovery retains intermediate quarters from the official 800-day index,
up to 64 latest-revision period/basis sources; normal current-quarter discovery retains
its existing eight-source behavior. Each period prefers consolidated when published,
selects its year-ago quarter and available preceding March/December annual comparables,
and retrieves at most eight files. Reuse original cached HTML only after its SHA256
matches; otherwise request the official URL again. Validate archived bytes and recompute
metrics before retaining a scored snapshot. Per-stock and per-period failures continue.
New versions go to company/fundamentals/<isin>/history/<id>.json. Only a snapshot at
or after the current financial period can update the latest record; historical collections
cannot replace newer current evidence. Equivalent snapshots are retained without duplicate
versions. Preserve actual source published_at and today's recorded_at: never backdate
collection or make these newly collected snapshots eligible for earlier paper/backtest
choices. Report each target period's added/retained/unavailable status in
company/fundamentals_history_pull.json and refresh 750-stock cached coverage on completion.
The remaining-data operation separately imports sourced listing dates against all 750
ISINs, refreshes sector mappings for the Total Market universe and all 11 sector indices
plus Nifty 500, retries EMBDL's April/May internal daily gaps, and downloads one-minute
candles for the same rolling ten calendar days used by five-minute history. Never delete
older sessions. Validate timezone, OHLCV, duplicates and minute boundaries before writes;
report absent minutes and preserve gaps when providers cannot supply them. An unmapped
sector because of ambiguous/no index classification is not fixed by inventing an index.

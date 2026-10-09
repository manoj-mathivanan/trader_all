# Trader — authoritative architecture and rebuild specification

**Company research addition — 8 October 2026.** The Fundamentals page adds advisory
technical candidate scans, sector-aware experimental quality scores and automatic LLM
web research of company filings and recent news. Research runs through the existing
job worker and preserves cited reviews. Users do not supply sources. The server needs
`OPENAI_API_KEY` and `TRADER_NEWS_MODEL`; production paid actions require authentication.
Backtest/paper entry rules are unchanged. The complete feature contract, storage and
validation are documented in [COMPANY_RESEARCH.md](COMPANY_RESEARCH.md).

**Reconciled with the application and owner decisions on 4 October 2026.**

**Research thread reconciled — 4 October 2026.** The final refreshed custom Blue sky
backtest profit is ₹1,919.02 (+1.91902%) on ₹100,000, April 2025–October 2026.
New provider matching, exact-row repair, trend/RS/breadth/warmup contracts are integrated
below; the research decisions section records all retained/rejected configurations and
comparisons. Other threads’ implementation contracts are preserved.

This document is sufficient to rebuild the current local dashboard and its backend without
chat history, screenshots, README.md, or an existing checkout. It defines appearance, navigation,
forms, defaults, schemas, HTTP interfaces, algorithms, files, recovery behavior and verification.
The future production design at the end is a separately labeled roadmap. It is not a prerequisite
for recreating the current page. The current specification supersedes older architecture drafts.

Rebuilding the application does not regenerate private credentials, downloaded provider data,
saved experiments or a portfolio ledger. Reconnect and fetch real data for a fresh installation;
restore the existing durable data directory when continuing an existing one; a legacy encrypted token also needs its original encryption key.
Never replace missing user history with example records or hardcoded historical metrics.

## Current deployment decisions — 4 October 2026

The owner now authorizes the agent to commit and push to the public repository `manoj-mathivanan/trader_all` and deploy this MVP for remote research/paper use before edge validation. Live execution and the full Postgres/Redis production roadmap remain deferred. These are final current-runtime decisions. The future infrastructure roadmap below is not required for this deployed MVP; its database, queue and live-broker proposals are not current capabilities.

The approved VPS is DigitalOcean `manoj-projects` in Bangalore, Ubuntu 24.04, 1 vCPU/1 GB RAM/25 GB SSD ($6/month before taxes). Domain: `manojmathivanan.com`; application: `https://trader.manojmathivanan.com`. Caddy HTTPS forwards to one loopback Uvicorn process in Docker Compose. Set `TRADER_PUBLIC_ORIGIN` explicitly; hosts and browser write origins remain checked. No website authentication is configured by owner choice, so all existing UI actions are publicly reachable.

New UI token saves use a plaintext private file with restricted filesystem permissions, outside published state through `TRADER_PRIVATE_DIR`. Tokens are never returned to the UI/logs or committed. Legacy encrypted local records remain readable solely for migration compatibility. `main` holds shared code, tests and configuration only. No data branch is published. Production starts fresh, and local/production files remain independent with no database or synchronization. `TRADER_ENV=local` defaults to research only; production explicitly enables paper APIs and automatic scheduling. The server never commits or pushes. Nightly production backups remain on the VPS. Data and credentials remain outside the code checkout and image. The server needs no GitHub write credential. The complete deployment, backup and recovery specification is embedded below; no other document is required for these contracts.

## Reading map

- [Current deployment decisions](#current-deployment-decisions--4-october-2026)
- [Complete deployment and recovery specification](#complete-deployed-mvp-specification-and-recovery-runbook)
- [Owner decisions and implementation status](#owner-decisions-and-implementation-status)
- [Current application rebuild specification](#current-application-rebuild-specification)
- [Data source, universe and ingestion contract](#data-source-universe-and-ingestion-contract)
- [Complete visual specification and DOM shell](#complete-visual-specification-and-dom-shell)
- [Views, actions and dialogs](#views-actions-and-dialogs)
- [Full screen-preset contract](#full-screen-preset-contract)
- [Exact local signal predicates and differences from the reference](#exact-local-signal-predicates-and-differences-from-the-reference)
- [Exact simulation, costs, exits and metrics](#exact-simulation-costs-exits-and-metrics)
- [Persistent paper portfolio and scheduling](#persistent-paper-portfolio-and-scheduling)
- [Strategy plugin and restart contracts](#strategy-plugin-and-restart-contracts)
- [API, security and persistence contract](#api-security-and-persistence-contract)
- [Schema reference and pinned local dependencies](#schema-reference-and-pinned-local-dependencies)
- [Files to recreate when only this document survives](#files-to-recreate-when-only-this-document-survives)
- [Research decisions, reproducible configurations and results from this thread](#research-decisions-reproducible-configurations-and-results-from-this-thread)
- [Historical reference observations and investigation evidence](#historical-reference-observations-and-investigation-evidence)
- [Future production design — not the current runtime](#future-production-design--not-the-current-runtime)

## Owner decisions and implementation status

| Area | Final decision / current status |
|---|---|
| Purpose | Personal rules-based equities research locally and in production; production Swing paper and local/production forward Scalping paper; no SaaS, multi-tenant service, tips or managed money |
| Current market coverage | NSE cash equities matched to current Nifty 50 or Nifty 500 constituents; broad NSE/BSE support is a future target |
| Product order | Dashboard first, real data and backtests next; production paper support is explicitly authorized before edge validation |
| Visual direction | Light cream/green Banana-inspired design, optional persistent dark toggle; original source/assets only |
| Strategy versus screen | One active Swing Patterns strategy with VCP, Blue sky, Multi-year and IPO screens; no separate parity strategy/profile |
| Momentum research | intraday_momentum is active for five-minute opening-range backtests; momentum paper/streaming execution remains pending; scalping supports one-minute pullback research and forward quote paper (see SCALPING_RESEARCH.md); options is a roadmap item |
| Portfolio ownership | Exactly one created portfolio per strategy ID, independent cash/capital/configuration/positions/history; no capital pooling |
| Configurability | Research settings and paper screen/risk/exits/costs/schedule are editable in the UI; schema-defined fields, no deploy for routine tuning |
| Accounting invariants | Paper capital and membership are fixed after creation; capital transfers/reallocation are not implemented; editing other settings never resets the ledger |
| Execution | Swing paper uses simulated EOD next_open fills; Scalping paper uses observed streamed bid/ask for long/short fills; Upstox supplies data only, with no broker orders |
| Persistence | Durable per-strategy JSON ledger, atomic replacement and session checkpoint; startup restores history and retries interrupted scheduled work |
| Runtime | One loopback FastAPI process and in-process research job worker per environment; Swing weekday scheduler starts only in production; Scalping has a separate optional quote process with cross-process locks; no Postgres, Redis or RQ |
| Data honesty | Real provider data only; tests may use isolated synthetic fixtures; no invented candles, prices, trades or performance |
| Research gate | Edge is not validated; current constituents, adjustments, historical RS and listing history remain incomplete; live trading and the larger database/queue roadmap require research validation; current remote research/paper MVP is authorized |
| Deployment | MVP deployed to DigitalOcean with Caddy HTTPS at trader.manojmathivanan.com; live mode remains unavailable |
| Authentication | No website login for the current public MVP by owner choice; optional Basic Auth is implemented but unset; live-broker access is a separate future decision |
| Source control | Owner authorizes agent commits/pushes of shared code/configuration to public manoj-mathivanan/trader_all main; all data and secrets excluded; server never pushes |

Implemented: six production dashboard views (five locally), plaintext private token saves, real constituent matching/ingestion,
coverage and candlestick charts, saved screens, costed backtests and complete sortable reports,
jobs/logs, isolated paper portfolios, configurable paper UI, scheduling and restart recovery.
Production MVP deployment is implemented. Database/queue, Telegram, momentum paper/streaming and options execution,
live broker accounts/orders/stops/reconciliation and unbiased edge validation remain pending.
No account/portfolio or automatic paper schedule is created at installation. Deployment installs the separate nightly data-backup timer.

## Current application rebuild specification

The following sections define the current shared application and its local/production differences. They distinguish API compatibility defaults,
new-form UI seeds, reference-site observations and future goals explicitly. If a known limitation
is described, reproduce the documented current behavior rather than silently claiming a fix.

### Current repository and run commands

The shared file-based MVP is intentionally smaller than the future database/queue architecture below:

| Path | Responsibility |
|---|---|
| `dashboard/api/main.py` | Loopback-bound FastAPI API, allowed public proxy origin, local/production gate, bootstrap/settings/token/jobs/bars/runs/paper routes |
| `dashboard/web/app.js` | Single-page dashboard renderer and forms |
| `dashboard/web/style.css` | Light Banana-inspired dashboard styling |
| `dashboard/web/index.html` and `favicon.svg` | Static document shell and original app icon |
| `dashboard/web/vendor/` | Locally copied KLineChart library and its license |
| `scripts/vendor.mjs`, `package.json`, `package-lock.json` | Frontend dependency installation and vendoring |
| `requirements.txt`, `requirements-lock.txt`, `start.ps1` | Python dependencies and local launch |
| `tests/test_*.py`, `tests/test_screen_presets.cjs` | Backend and screen-selection regression checks |
| `core/research/config.py` | Pydantic settings and backtest schemas |
| `core/research/upstox.py` | Universe refresh, Upstox V3 daily ingestion, boundary merge and validation |
| `core/research/backtest.py` | Daily-bar preparation, simulation, metrics and run snapshots |
| `core/research/jobs.py` | In-process queued/running/success/failed jobs and structured logs |
| `core/research/store.py` | Local JSON/lock-backed persistence under `data/` |
| `core/portfolio/manager.py` | Strategy identity, isolated creation/configuration/status/persistence |
| `core/portfolio/registry.py` | Per-strategy paper schema and runner registration |
| `core/portfolio/paper.py` | Swing config, forward-only cycle, data fingerprints and atomic checkpoints |
| `core/portfolio/scheduler.py` | Production-only weekday schedule, claims and restart recovery |
| `core/risk/position_sizer.py` | Shared risk and cash sizing |
| `core/execution/paper.py` | Shared simulated fills, fees and actual slippage |
| `core/strategies/registry.py` | Active Swing Patterns, Intraday Momentum research and Scalping research entries |
| `strategies/swing_patterns/patterns/registry.py` | Banana screen registry |
| `strategies/swing_patterns/patterns/signals.py` | Pure daily-bar signal predicates |

On Windows, run `start.ps1` from the repository root. The dashboard is loopback-only at
`http://127.0.0.1:8765`. Run `npm.cmd run check` and
`.venv/Scripts/python.exe -m unittest discover -s tests -q` after code changes.

### Data source, universe and ingestion contract

- Upstox is the primary historical EOD source. The user has Upstox API access; never ask for or
  print access tokens in chat, logs, code, or reports.
- The token is entered in each environment's Settings and saved as plaintext in its private file, with restricted filesystem permissions. It is never returned to the browser or logged. Legacy encrypted local records remain readable with the original key. Mutating requests require the existing `X-Trader-Request: local-ui` header in both environments; its name is a protocol marker, not authentication.
- The API default universe is **Nifty 50**; the owner expanded research first to **Nifty 500**,
  then to **Nifty Total Market (750)** on 8 October 2026. The existing paper portfolio retains
  its frozen Nifty 500 membership.
  Both are implemented Settings choices. The full available 500-member provider universe has
  been fetched; broader NSE/BSE coverage and historical membership remain future work.
- Historical setup used a maximum ten-year internal range. The rolling Market data fetch contract below supersedes editable dates. The validated working range is
  research initially used `2019-01-01` onward, then extended stored history to `2018-01-01`.
  Upstox returned actual trading candles through `2026-10-01`; requested end dates and observed
  last sessions are distinct. Do not overwrite other threads’ current Settings merely to
  reproduce a historical settings snapshot.
- Upstox V3 daily requests use the inclusive path format
  `/v3/historical-candle/{instrument_key}/days/1/{to_date}/{from_date}`. Instrument keys are URL
  encoded. Upstox daily history supports old ranges back to 2000; the application still enforces
  a ten-year local setting range.
- **Refresh universe** downloads and matches the current official constituent list and Upstox
  instruments. It does not fetch candles.
- **Fetch missing data** examines every symbol's actual stored first/last bar. It requests only an
  earlier boundary when the configured start precedes local coverage and only a later boundary
  when the configured end follows local coverage. New candles merge by date, replace duplicate
  dates with the provider's newest row, validate OHLCV, and atomically replace the local record.
- If coverage is complete, the provider is not called. Exchange holidays, suspensions and missing
  sessions are not invented. A symbol may begin later because it listed later.
- An earlier validated ingestion snapshot fetched 93,962 bars for 50 Nifty 50 symbols. In that snapshot ADANIENT had 1,923
  bars from `2019-01-01` through `2026-10-01`, with no duplicate dates or suspicious multi-day
  gaps. Current constituents are still survivorship-biased; delisted/merged historical membership
  and corporate-action adjustment require a future data source/validation step.

### Decisions and precedence

- Use the shared dashboard for real-data research/backtests locally or in production; create and run paper portfolios only in production.
- One Swing strategy owns four screen families; VCP is a screen, not another strategy. There is
  no separate Banana parity profile. Intraday Momentum and Scalping have active research tabs; Scalping also supports a separately controlled forward quote paper runner. Momentum streaming paper remains pending.
- Backtest and paper forms have exactly one **Screen** dropdown containing built-ins and saved
  screens. Store `pattern` as a hidden field updated by the selection. Do not add a second
  visible Banana screen selector. Only custom-screen creation has a **Base screen** selector.
- Every dropdown change replaces all thirteen screen-filter values, including custom → built-in
  transitions. It leaves dates, name, capital, entries, exits, risk, fees and acknowledgment alone.
- Production paper simulation and remote MVP hosting are authorized before edge validation; this does not validate the edge. Live execution remains future.
- The public MVP deliberately has no website authentication. Basic Auth remains an optional implementation, not a deployment requirement. Uvicorn remains bound to loopback behind Caddy.
- The owner authorizes the agent to commit and push to the public repository; exclude credentials.
- The reference site's screen thresholds are research inputs. Actual implemented predicates below
  determine the local output; do not imply missing reference filters are enforced.
- Preserve old experiments rather than rewriting their settings or metrics after a bug fix.

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

Hash navigation: `#overview`, `#data`, `#backtests`, `#paper`, `#jobs`, `#settings`; unknown hashes
return to overview. Closing/changing views disposes charts and closes the modal.

| View | Required content and behavior |
|---|---|
| Overview | Universe, loaded-symbol/bar coverage, run count, Research/Paper mode and simulated position count; latest run's return/trade count and full-report button; connection/data/backtest onboarding; methodology strip; three recent jobs |
| Market data | Refresh universe, Fetch missing data, selected universe/requested dates, actual coverage and bias warning; search symbol/company/sector; table of company/symbol, sector, last close/change, bars, first/last history and Chart button |
| Backtests | New backtest; newest-first run cards with name, universe, dates, IST creation time, return, drawdown, trades; open complete report; explanatory research text |
| Paper trading | Strategy portfolio selector; Create/configure portfolio; pause/resume new entries; Run daily cycle; status/universe/start/last session/schedule; equity/cash/realized/unrealized cards; open positions, equity curve, closed trades, fills and full JSON export |
| Jobs & logs | All returned jobs with type/time/status and View logs; pending-job link and manual Refresh; readable timestamped log in a modal |
| Settings | Research-universe form (automatic history windows); private plaintext-token connection form; token saved/replacement status; environment/authentication status; backtest configuration action |

Sidebar saved-screen buttons open New backtest seeded from that screen. Add new screen opens
name, Base screen and all thirteen filters. New backtest groups fields into Experiment; Banana screen
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
not the minimum date. With no history boundaries, disable the date inputs. Do not constrain
Market data settings, since those dates request additional history. Preserve cloned report
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

All four built-ins currently share the following thirteen-field seed; their pattern IDs choose
different predicates. These shared defaults do not mean the four signal rules are identical.

```json
{
  "base_days": 15, "max_depth_pct": 35, "volume_multiple": 1,
  "sma_days": 50, "require_long_trend": false,
  "require_rising_long_trend": false, "min_rs_rating": 0, "min_turnover": 50000000,
  "vcp_window_days": 10, "vcp_volume_multiple": 0.9,
  "blue_sky_lookback_days": 5000,
  "multiyear_base_days": 260, "multiyear_max_depth_pct": 50
}
```

IDs are `builtin:vcp`, `builtin:blue_sky`, `builtin:multiyear`, `builtin:ipo`; they are UI IDs only.
Saved screen stores name, one pattern ID, the thirteen filters, created_at and an ID computed as
`custom_` + first ten hex characters of SHA1(name encoded as UTF-8). Saving the same name replaces
that preset; keep at most 100 newest presets. No delete/edit-specific screen API exists yet.
Selecting a saved screen copies its stored values. For older presets missing the three new
trend/RS filters, merge the built-in disabled defaults (false, false, 0); never leave stale
checkbox states. Set checkbox.checked for booleans, numeric input.value for numeric fields. New form merge order:
built-in/saved filters, then any explicit run seed (for cloning), then UI general defaults as
fallbacks. Always set the visible Screen selection to the chosen seed. There is no screen ID in
the saved run configuration; the resolved pattern, boolean and numeric values are the reproducible snapshot.

New backtest defaults outside filters: name `Breakout experiment`, capital ₹10,00,000, pivot,
1.5% risk, 8% stop, trail_50d, weak-market off, breakeven_r 1, trail_pct 8, five positions,
120 holding sessions, alphabetical ranking, minimum_warmup_sessions 50, market_breadth_pct 40,
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

### Intraday momentum research contract

`core/research/momentum.py` declares `MomentumConfig`, the prior-session liquidity/ATR preselection, same-opening-interval relative-volume ranking, completed five-minute breakout-close signals, next-bar-open long/short simulation, ATR stops/optional R targets, reserved equal capital budgets, and same-day cutoff exits. It is independent of Swing screen/risk settings and paper execution. The dashboard renders its schema in the Momentum view and dispatches `/api/jobs/momentum`; `/api/momentum/coverage` reports required/cached/missing stock-sessions without fetching. `intraday_data.load_ranges` validates and reuses per-ISIN/session caches, downloads missing inputs in <=28-day V3 requests, and fails on missing expected sessions. Runs snapshot `run_data` and `run_intraday`, daily selections, input hashes, provenance and research references; charts read frozen five-minute inputs. Normal daily-history coverage/listing evidence and price-discontinuity checks remain enforced. Full behavior and the initial experiment are documented in `MOMENTUM_RESEARCH.md`.

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
| Research | required_warmup(config), available_window(settings, warmup), prepare(settings, config) → universe/datasets/manifest/exclusions, run(settings, config, log, job_id) → {run_id} |
| Simulation | simulate(datasets, config, state=None, liquidate=True, allow_entries=True) → trades/curve/state/metrics; deepcopy input state before mutation |
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
Financial Services bank/NBFC adapters and other unsupported forms remain missing/unsupported.
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

### API, security and persistence contract

All routes use the same origin and optional Basic Auth (unset in the public MVP). Bind 127.0.0.1:8765 with one process, never reload/multiple workers. Local launch disables proxy headers. Production trusts proxy headers only from 127.0.0.1; Caddy removes X-Forwarded-For so the peer remains loopback. Accept loopback peers and localhost/loopback hosts (testclient/testserver in tests), plus the hostname of explicitly configured TRADER_PUBLIC_ORIGIN. Mutations require `X-Trader-Request: local-ui`; when Origin is present, require exact TRADER_PUBLIC_ORIGIN for the public host, otherwise exact base-origin match. These guards are not a login or authorization system. Security response headers: nosniff, DENY frames,
no-referrer and no-store. Do not expose OpenAPI/docs endpoints. ValueError returns 400 detail. Standard schema errors return 422 locations/messages without echoing inputs; generic plugin-config validation returns a safe 422 detail string. Invalid/missing run, bar and job IDs return 404; unknown strategy IDs and unimplemented paper plugins return 400, and GET of a valid strategy without a portfolio returns JSON null.

| Method and route | Request / response |
|---|---|
| GET `/` and `/static/*` | HTML shell and static assets |
| GET `/api/bootstrap` | settings/settings_schema, backtest_schema, patterns, screens, token_saved, instruments/catalog coverage, universe_updated, jobs (latest 100), runs, strategies, auth_enabled, environment, paper_enabled, remote_enabled, paper_schema/portfolio and generic paper_schemas/paper_portfolios |
| PUT `/api/settings` | DataPreferences (universe only); reject while job active; preserve internal legacy dates; no implicit fetch |
| PUT `/api/connection` | access_token 20–10000 chars after whitespace checks; save plaintext private file; saved status only |
| POST `/api/screens` | name/pattern/thirteen filters; validate and persist resolved preset |
| POST `/api/jobs/universe` | Queue constituent/instrument match job |
| POST `/api/jobs/ingest` | Require saved token; queue full 750-stock rolling daily + five-minute fetch |
| POST `/api/jobs/backtest` | BacktestConfig; validate prepare before queuing; job result run_id |
| GET `/api/backtest/window?warmup=50` | warmup integer50–2500; start/end, warmup_sessions, ready/total symbols, history_start/end |
| GET `/api/bars/{isin}` | Full normalized bar record; ISIN alphanumeric length 12 |
| GET `/api/runs/{run_id}` | Saved complete report; ID 12 lowercase hex |
| GET `/api/jobs/{job_id}` | Job/logs/result; ID 12 lowercase hex |
| POST/PUT `/api/paper/portfolio` | Create/update Swing PaperConfig; full portfolio result |
| PUT `/api/paper/status` | status active/paused |
| POST `/api/jobs/paper` | Queue Swing cycle, manual trigger |
| GET/POST/PUT `/api/strategies/{strategy_id}/paper/portfolio` | Generic per-strategy lookup/create/update |
| PUT `/api/strategies/{strategy_id}/paper/status` | Per-strategy active/paused |
| POST `/api/strategies/{strategy_id}/paper/cycle` | Queue registered plugin cycle; reject unsupported strategy |

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

Regression acceptance: custom→every built-in resets all thirteen filters and checkbox.checked;
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
4. Build the HTML shell, design tokens, six production views/five local views, dialogs/preset merge and polling behavior; gate paper routes/scheduler on TRADER_ENV.
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

### Schema reference and pinned local dependencies

All monetary/numeric input models reject NaN/infinity and unknown fields. Dates must increase;
Internal legacy Settings additionally limits its range to 3653 calendar days; public DataPreferences has no date fields. Backtest/Paper acknowledgment must
be true. Defaults below are **API/schema defaults**; the explicit UI screen seed above overrides
them for new forms. This separation preserves older saved experiments.

#### Settings (internal legacy model; UI/API uses universe-only DataPreferences)

| Field | Type / allowed values / bounds | API default |
|---|---|---|
| `universe` | string: nifty50, nifty500, niftytotalmarket | "nifty50" |
| `start` | date | "2018-10-01" |
| `end` | date | "2026-10-01" |

#### BacktestConfig

| Field | Type / allowed values / bounds | API default |
|---|---|---|
| `name` | string; length ≥ 1; length ≤ 80 | "Breakout experiment" |
| `pattern` | string: breakout, vcp, blue_sky, multiyear, ipo | "breakout" |
| `capital` | number; ≥ 1000; ≤ 10000000000.0 | 1000000 |
| `base_days` | integer; ≥ 5; ≤ 250 | 25 |
| `max_depth_pct` | number; > 0; ≤ 80 | 30 |
| `volume_multiple` | number; ≥ 0.1; ≤ 10 | 1.5 |
| `sma_days` | integer; ≥ 5; ≤ 250 | 50 |
| `require_long_trend` | boolean | false |
| `require_rising_long_trend` | boolean | false |
| `min_rs_rating` | number; ≥ 0; ≤ 100; 0 disables | 0 |
| `candidate_rank` | string: alphabetical, rs_126 | "alphabetical" |
| `min_turnover` | number; ≥ 0; ≤ 1000000000000.0 | 50000000 |
| `vcp_window_days` | integer; ≥ 3; ≤ 60 | 10 |
| `vcp_volume_multiple` | number; > 0; ≤ 1 | 0.8 |
| `blue_sky_lookback_days` | integer; ≥ 50; ≤ 5000 | 5000 |
| `multiyear_base_days` | integer; ≥ 252; ≤ 2500 | 260 |
| `multiyear_max_depth_pct` | number; > 0; ≤ 90 | 50 |
| `entry_mode` | string: pivot, close, next_open | "pivot" |
| `risk_pct` | number; > 0; ≤ 5 | 1.5 |
| `stop_pct` | number; > 0; ≤ 50 | 8 |
| `winner_exit` | string: trail_50d, trail_30w, take_25 | "trail_50d" |
| `skip_weak_markets` | boolean | false |
| `market_breadth_pct` | number; ≥ 0; ≤ 100 | 40 |
| `breakeven_r` | number; ≥ 0.1; ≤ 10 | 1 |
| `trail_pct` | number; > 0; ≤ 50 | 8 |
| `max_positions` | integer; ≥ 1; ≤ 50 | 5 |
| `max_hold_days` | integer; ≥ 1; ≤ 1000 | 120 |
| `slippage_bps` | number; ≥ 0; ≤ 500 | 10 |
| `buy_cost_bps` | number; ≥ 0; ≤ 500 | 10 |
| `sell_cost_bps` | number; ≥ 0; ≤ 500 | 10 |
| `minimum_warmup_sessions` | integer; ≥ 50; ≤ 2500 | 50 |
| `start` | date | Required |
| `end` | date | Required |
| `acknowledge_limitations` | boolean | false |

#### PaperConfig

| Field | Type / allowed values / bounds | API default |
|---|---|---|
| `name` | string; length ≥ 1; length ≤ 80 | "Swing paper portfolio" |
| `pattern` | string: vcp, blue_sky, multiyear, ipo | "vcp" |
| `capital` | number; ≥ 1000; ≤ 10000000000.0 | Required |
| `base_days` | integer; ≥ 5; ≤ 250 | 25 |
| `max_depth_pct` | number; > 0; ≤ 80 | 30 |
| `volume_multiple` | number; ≥ 0.1; ≤ 10 | 1.5 |
| `sma_days` | integer; ≥ 5; ≤ 250 | 50 |
| `require_long_trend` | boolean | false |
| `require_rising_long_trend` | boolean | false |
| `min_rs_rating` | number; ≥ 0; ≤ 100; 0 disables | 0 |
| `candidate_rank` | string: alphabetical, rs_126 | "alphabetical" |
| `min_turnover` | number; ≥ 0; ≤ 1000000000000.0 | 50000000 |
| `vcp_window_days` | integer; ≥ 3; ≤ 60 | 10 |
| `vcp_volume_multiple` | number; > 0; ≤ 1 | 0.8 |
| `blue_sky_lookback_days` | integer; ≥ 50; ≤ 5000 | 5000 |
| `multiyear_base_days` | integer; ≥ 252; ≤ 2500 | 260 |
| `multiyear_max_depth_pct` | number; > 0; ≤ 90 | 50 |
| `entry_mode` | string: next_open | "next_open" |
| `risk_pct` | number; > 0; ≤ 5 | 1.5 |
| `stop_pct` | number; > 0; ≤ 50 | 8 |
| `winner_exit` | string: trail_50d, trail_30w, take_25 | "trail_50d" |
| `skip_weak_markets` | boolean | false |
| `market_breadth_pct` | number; ≥ 0; ≤ 100 | 40 |
| `breakeven_r` | number; ≥ 0.1; ≤ 10 | 1 |
| `trail_pct` | number; > 0; ≤ 50 | 8 |
| `max_positions` | integer; ≥ 1; ≤ 50 | 5 |
| `max_hold_days` | integer; ≥ 1; ≤ 1000 | 120 |
| `slippage_bps` | number; > 0; ≤ 500 | 10 |
| `buy_cost_bps` | number; > 0; ≤ 500 | 10 |
| `sell_cost_bps` | number; > 0; ≤ 500 | 10 |
| `auto_run` | boolean | false |
| `run_hour` | integer; ≥ 16; ≤ 23 | 16 |
| `run_minute` | integer; ≥ 0; ≤ 59 | 15 |
| `acknowledge_limitations` | boolean | false |

ScreenInput contains only name, pattern and the thirteen screen-filter fields; name is required,
pattern defaults to vcp, and numeric defaults/bounds match the BacktestConfig filter rows.
No execution/cost fields belong to a screen. It also forbids extra keys and nonfinite numbers.

Exact requirements-lock.txt snapshot inspected on 4 October 2026:

```text
annotated-doc==0.0.5
annotated-types==0.8.0
anyio==4.15.1
certifi==2026.7.22
cffi==2.1.1
click==8.5.0
cryptography==50.0.2
fastapi==0.142.2
h11==0.16.0
httpcore==1.0.9
httpx==0.28.1
idna==3.20
opentelemetry-api==1.45.0
pycparser==3.0
pydantic==2.13.5
pydantic_core==2.46.5
python-multipart==0.0.32
starlette==1.7.0
typing-inspection==0.4.4
typing_extensions==4.16.0
uvicorn==0.54.0
```

## Files to recreate when only this document survives

Recreate the source modules described above, their package directories and tests; conventional
__init__.py files may be empty. The package registry, schemas, algorithm and API contracts are
specified in this document. The HTML shell loads favicon, style.css, KLineChart and app.js from
/static; use defer for both scripts and UTF-8/viewport/theme-color metadata. The root document
contains the required DOM IDs given above. All application files and this spec are UTF-8.

The following shared/local support files are fully specified here; production support files are embedded in the deployment section. They replace the original
production starter-file suggestions for the current rebuild; do not install unused broker SDKs,
Timescale/Redis, vectorbt or Telegram merely to display this page.

### package.json

```json
{
  "name": "trader-control-panel",
  "private": true,
  "version": "0.1.0",
  "scripts": { "vendor": "node scripts/vendor.mjs", "check": "node --check dashboard/web/app.js", "test": "node tests/test_screen_presets.cjs" },
  "dependencies": { "klinecharts": "9.8.12" }
}
```

### requirements.txt

```text
fastapi>=0.115,<1
uvicorn>=0.34,<1
httpx>=0.28,<1
cryptography>=44,<51
```

For an exact dependency snapshot, create requirements-lock.txt from the pinned list above.
Python 3.13 is the verified runtime, not a requirement to invent a different dependency stack.
With no surviving package-lock.json, run `npm.cmd install` against the exact KLineChart version
in package.json to generate a lockfile. Use `npm.cmd ci` only after that lockfile exists.
Node must support ES modules and node:fs/promises for the vendor script and node:vm for tests.

### scripts/vendor.mjs

```javascript
import { mkdir, copyFile } from 'node:fs/promises';
await mkdir('dashboard/web/vendor', { recursive: true });
await copyFile('node_modules/klinecharts/dist/umd/klinecharts.min.js', 'dashboard/web/vendor/klinecharts.min.js');
await copyFile('node_modules/klinecharts/LICENSE', 'dashboard/web/vendor/KLINECHARTS-LICENSE');
```

### start.ps1

```powershell
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& "$PSScriptRoot/.venv/Scripts/python.exe" -m uvicorn dashboard.api.main:app --host 127.0.0.1 --port 8765 --no-proxy-headers
```

### .gitignore

```gitignore
.env
*.env
__pycache__/
*.pyc
.venv/
venv/
node_modules/
*.db
*.sqlite3
data/raw/
data/cache/
.DS_Store
.idea/
.vscode/
artifacts/
data/
.local-key

!.env.example
*.log
*.pid
```

### dashboard/web/index.html

```html
<!doctype html>
<html lang="en" data-theme="light">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#f7f8f3">
  <title>Trader — Swing control panel</title>
  <link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="/static/style.css">
  <script defer src="/static/vendor/klinecharts.min.js"></script>
  <script defer src="/static/app.js"></script>
</head>
<body>
  <a class="skip" href="#content">Skip to content</a>
  <header class="topbar">
    <a href="#overview" class="brand" aria-label="Trader home"><span class="brand-mark">↗</span><span>trader<span class="brand-dot">.</span><small>A little more systematic.</small></span></a>
    <nav id="top-navigation" aria-label="Workspace navigation"></nav>
    <div class="top-tools"><span class="local-status"><i></i> Local workspace</span><button class="icon-button" id="theme-toggle" aria-label="Switch to dark theme">◐</button><span class="avatar" aria-label="Personal workspace">M</span></div>
  </header>
  <aside class="sidebar">
    <div class="eyebrow">YOUR STRATEGIES</div><div id="strategies"></div>
    <div class="eyebrow saved-eyebrow">SAVED SCREENS</div><div id="saved-screens"></div>
    <button class="button add-screen" data-action="new-screen">＋ Add new screen</button>
    <div class="sidebar-bottom"><div class="risk-icon">◎</div><strong>Protect first.<br>Let the winners run.</strong><p>One set of rules.<br>Every trade, every time.</p><button class="text-button" data-action="method">Explore the method ↗</button></div>
    <div class="sidebar-foot"><i></i> Research workspace <span>v0.1</span></div>
  </aside>
  <main id="content" tabindex="-1">
    <div class="demo-banner"><span><b>RESEARCH & PAPER</b> Real market data. Simulated trades. No live execution.</span><a href="#settings">Connection settings ↗</a></div>
    <div id="view"><div class="empty">Loading your workspace…</div></div>
    <footer><span>Rules-based research. Not investment advice. Backtests are hypothetical.</span><span>Charts by KLineChart · <a href="/static/vendor/KLINECHARTS-LICENSE">Apache 2.0</a></span></footer>
  </main>
  <dialog id="modal"><div id="modal-content"></div></dialog>
  <div id="toast" role="status" aria-live="polite"></div>
</body>
</html>
```

### dashboard/web/favicon.svg

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><rect width="40" height="40" rx="12" fill="#21734e"/><path d="M10 28 28 10M14 10h14v14" fill="none" stroke="#e6ed9b" stroke-width="3"/></svg>
```

### A complete paper-create configuration example

This is documentation for the request shape, not an automatically created account. The owner
chooses their own capital in the UI. POST this shape to /api/strategies/swing_patterns/paper/portfolio
only after actual universe/history ingestion; resolved screen values are included, not a screen ID.

```json
{
  "name": "Swing paper portfolio",
  "pattern": "vcp",
  "capital": 1000000.0,
  "base_days": 15,
  "max_depth_pct": 35,
  "volume_multiple": 1,
  "sma_days": 50,
  "min_turnover": 50000000.0,
  "vcp_window_days": 10,
  "vcp_volume_multiple": 0.9,
  "blue_sky_lookback_days": 5000,
  "multiyear_base_days": 260,
  "multiyear_max_depth_pct": 50.0,
  "entry_mode": "next_open",
  "risk_pct": 1.5,
  "stop_pct": 8.0,
  "winner_exit": "trail_50d",
  "skip_weak_markets": false,
  "breakeven_r": 1.0,
  "trail_pct": 8.0,
  "max_positions": 5,
  "max_hold_days": 120,
  "slippage_bps": 10.0,
  "buy_cost_bps": 10.0,
  "sell_cost_bps": 10.0,
  "auto_run": false,
  "run_hour": 16,
  "run_minute": 15,
  "acknowledge_limitations": true
}
```

### Settings titles for the schema-driven form renderer

Use these API field titles for the common trading inputs. UI-specific overrides are Screen,
Base screen, Strategy, Portfolio name and Allocated capital (₹), as described above.

| Field | JSON-schema title |
|---|---|
| `name` | Run name |
| `pattern` | Banana screen |
| `capital` | Starting capital (₹) |
| `base_days` | Base length (sessions) |
| `max_depth_pct` | Maximum base depth (%) |
| `volume_multiple` | Volume / prior 50-session mean |
| `sma_days` | Trend SMA (sessions) |
| `require_long_trend` | Require price above 200-day SMA |
| `require_rising_long_trend` | Require rising 200-day SMA (20 sessions) |
| `min_rs_rating` | Minimum 126-session RS percentile (0 disables) |
| `candidate_rank` | Simultaneous signal priority |
| `market_breadth_pct` | Minimum market breadth (%) |
| `minimum_warmup_sessions` | Minimum comparison warmup (sessions) |
| `min_turnover` | Minimum average turnover (₹) |
| `vcp_window_days` | VCP contraction window (sessions) |
| `vcp_volume_multiple` | VCP final volume / 50-session mean |
| `blue_sky_lookback_days` | Blue-sky prior high lookback (sessions) |
| `multiyear_base_days` | Multiyear base length (sessions) |
| `multiyear_max_depth_pct` | Multiyear maximum base depth (%) |
| `entry_mode` | Entry price |
| `risk_pct` | Risk per trade (%) |
| `stop_pct` | Initial stop (%) |
| `winner_exit` | Winner exit |
| `skip_weak_markets` | Skip weak markets |
| `breakeven_r` | Breakeven trigger (R) |
| `trail_pct` | Trail below best close (%) |
| `max_positions` | Maximum open positions |
| `max_hold_days` | Maximum holding sessions |
| `slippage_bps` | Slippage per side (bps) |
| `buy_cost_bps` | All-in buy charges (bps) |
| `sell_cost_bps` | All-in sell charges (bps) |
| `start` | Test from |
| `end` | Test through |
| `acknowledge_limitations` | I understand this is an exploratory backtest |

Research provenance note: the following section is maintained by the research/enhancement work.
Its references to "this thread" and statements that no deployment/commit/push was performed
describe that research work, not the separate deployment thread recorded later in this document.

## Research decisions, reproducible configurations and results from this thread

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

## Complete deployed MVP specification and recovery runbook

This section records the final decisions and implementation from the deployment thread on
4 October 2026 (IST). It is the current specification, not the future PostgreSQL/Redis roadmap.
All required deployment files are reproduced below. Private credentials cannot be reconstructed
from a public document; preserve them separately or re-enter them after recovery.

### Environment boundaries and final decisions

| Concern | Local | Production |
|---|---|---|
| Source | Shared repository main | Same shared source main |
| TRADER_ENV | local (default) | production, explicitly set by Compose |
| Market data, screens, backtests, jobs | Independent local files | Independent production files |
| Paper portfolio/API/scheduler | Hidden/blocked; no scheduler recovery/start | Enabled capability; owner creates/configures portfolio |
| Token | Own Settings save/private file | Own Settings save/private file |
| Data root | repository/data by default | Host /srv/trader/data → container /state/data |
| Private root | DATA/private by default | Host /srv/trader/private → container /state/private |
| URL | http://127.0.0.1:8765 | https://trader.manojmathivanan.com |
| Login | Optional Basic Auth, normally unset | No website authentication, explicitly owner-selected |

Production starts fresh. Do not seed it from local candles, screens, settings, runs, paper
ledgers or credentials. Subsequent deployment updates retain production files. No shared database,
database service, local/production synchronization or automatic merging is implemented or wanted
now. Both environments use the same algorithms, schemas and UI source. Local research/backtests
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
export all non-secret JSON into /srv/trader/backup-state. Ignore any private path and .tmp file;
reject other non-JSON input files. Hash exact JSON file bytes with SHA256. manifest.json is
{version: 1, files: {relative_filename: lowercase_64_character_sha256}}; blobs/<sha>.json.gz holds
the original bytes compressed with empty gzip filename and mtime=0. Identical input files share
one blob. New blobs must parse as JSON and pass credential-key/JWT scans. Write blobs/manifest
via temporary files and atomic replace; remove unreferenced blobs from the current staging set.
These scans are safeguards, not a general guarantee that arbitrary JSON contains no sensitive data.

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

### Exact deployment files to recreate

Copy the following blocks to the named relative paths. Keep shell/Python/YAML/Dockerfile line
endings LF and save all source as UTF-8. Deployment paths/UID/origin must match the contracts above.

#### Dockerfile

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY requirements-lock.txt .
RUN pip install --no-cache-dir -r requirements-lock.txt
COPY core core
COPY strategies strategies
COPY dashboard dashboard
RUN useradd --uid 10001 --create-home trader
USER trader
CMD ["python", "-m", "uvicorn", "dashboard.api.main:app", "--host", "127.0.0.1", "--port", "8765", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"]
```

#### compose.yaml

```yaml
services:
  trader:
    build: .
    restart: unless-stopped
    network_mode: host
    environment:
      TRADER_ENV: production
      TRADER_PUBLIC_ORIGIN: https://trader.manojmathivanan.com
      TRADER_DATA_DIR: /state/data
      TRADER_PRIVATE_DIR: /state/private
    volumes:
      - /srv/trader/data:/state/data
      - /srv/trader/private:/state/private
    stop_grace_period: 60s
    logging:
      driver: json-file
      options:
        max-size: 10m
        max-file: '3'
```

#### deploy/Caddyfile

```caddyfile
trader.manojmathivanan.com {
    reverse_proxy 127.0.0.1:8765 {
        header_up -X-Forwarded-For
    }
}
```

#### deploy/bootstrap.sh

```bash
#!/bin/bash
set -euo pipefail
install -d -o 10001 -g 10001 /srv/trader/data /srv/trader/private
chmod 700 /srv/trader/private
install -d /opt/trader /srv/trader/snapshots /srv/trader/backups
if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    printf '/swapfile none swap sw 0 0\n' >>/etc/fstab
fi
systemctl enable --now docker caddy
```

#### deploy/backup.sh

```bash
#!/bin/bash
set -euo pipefail
exec 9>/run/trader-backup.lock
flock -n 9 || exit 0
cd /opt/trader
python3 - <<'PY'
import json
from pathlib import Path
p = Path('/srv/trader/data/jobs.json')
if p.exists() and any(j['status'] in ('queued', 'running') for j in json.loads(p.read_text())):
    raise SystemExit('Backup deferred: a job is active. Run manually after completion.')
PY
docker compose stop trader
trap 'cd /opt/trader; docker compose start trader' EXIT
mkdir -p /srv/trader/backup-state /srv/trader/backups
python3 deploy/data_snapshot.py snapshot /srv/trader/data /srv/trader/backup-state
tar -czf /srv/trader/backups/data-$(date -u +%Y%m%dT%H%M%SZ).tar.gz -C /srv/trader/backup-state .
find /srv/trader/backups -name 'data-*.tar.gz' -mtime +7 -delete
```

#### deploy/data_snapshot.py

```python
"""Content-addressed, compressed snapshots of non-secret Trader JSON state."""
import gzip
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path


def snapshot(source, target):
    blobs = target / 'blobs'
    blobs.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for path in sorted(source.rglob('*')):
        if not path.is_file() or 'private' in path.relative_to(source).parts or path.suffix == '.tmp':
            continue
        if path.suffix != '.json':
            raise ValueError(f'Unexpected file: {path}')
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        blob = blobs / (digest + '.json.gz')
        if not blob.exists():
            raw = path.read_text(encoding='utf-8')
            json.loads(raw)
            if re.search(r'"(?:access_token|encrypted_token|api_key|api_secret|password|private_key)"\s*:', raw, re.I) or re.search(r'eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', raw):
                raise ValueError(f'Credential found: {path}')
            del raw
            pending = blob.with_suffix('.tmp')
            with path.open('rb') as src, pending.open('wb') as dst:
                with gzip.GzipFile(filename='', mode='wb', fileobj=dst, mtime=0) as compressed:
                    shutil.copyfileobj(src, compressed)
            pending.replace(blob)
        manifest[path.relative_to(source).as_posix()] = digest
    target.mkdir(parents=True, exist_ok=True)
    pending = target / 'manifest.tmp'
    pending.write_text(json.dumps({'version': 1, 'files': manifest}, indent=2) + '\n', encoding='utf-8')
    pending.replace(target / 'manifest.json')
    used = set(manifest.values())
    for blob in blobs.glob('*.json.gz'):
        if blob.name.removesuffix('.json.gz') not in used:
            blob.unlink()
    print(f'Snapshot: {len(manifest)} files, {len(used)} unique blobs.')


def restore(source, target):
    manifest = json.loads((source / 'manifest.json').read_text())
    if manifest['version'] != 1:
        raise ValueError('Unsupported snapshot version')
    if target.exists() and any(target.iterdir()):
        raise ValueError('Restore destination must be empty')
    target.mkdir(parents=True, exist_ok=True)
    for name, digest in manifest['files'].items():
        path = (target / name).resolve()
        if not path.is_relative_to(target.resolve()) or 'private' in Path(name).parts or path.suffix != '.json' or not re.fullmatch('[a-f0-9]{64}', digest):
            raise ValueError('Unsafe snapshot manifest')
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(source / 'blobs' / (digest + '.json.gz'), 'rb') as src, path.open('wb') as dst:
            shutil.copyfileobj(src, dst)
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                raise ValueError(f'Corrupt snapshot: {name}')
    print(f'Restored {len(manifest["files"])} verified files.')


if __name__ == '__main__':
    {'snapshot': snapshot, 'restore': restore}[sys.argv[1]](Path(sys.argv[2]), Path(sys.argv[3]))
```

#### deploy/trader-backup.service

```ini
[Unit]
Description=Back up production Trader state locally
After=docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/trader-backup
TimeoutStartSec=3600
```

#### deploy/trader-backup.timer

```ini
[Unit]
Description=Nightly production Trader backup

[Timer]
OnCalendar=*-*-* 20:00:00 UTC
Persistent=true
RandomizedDelaySec=120

[Install]
WantedBy=timers.target
```

#### .dockerignore

```text
.git
.env
*.env
.local-key
data
artifacts
node_modules
.venv
**/__pycache__
```

#### .gitattributes

```gitattributes
* text=auto
*.sh text eol=lf
*.py text eol=lf
*.yml text eol=lf
*.yaml text eol=lf
Dockerfile text eol=lf
```

#### .env.example

```dotenv
# Optional Basic Auth for the LOCAL RESEARCH app. Set both in the process environment.
# The server fails to start if only one is configured.
DASHBOARD_ADMIN_USER=
DASHBOARD_ADMIN_PASSWORD=
# Enter the Upstox token in Settings, never here. New saves are plaintext private files.
# Python does not load this file automatically. Supply variables explicitly.
TRADER_PUBLIC_ORIGIN=
TRADER_DATA_DIR=
TRADER_PRIVATE_DIR=
TRADER_ENV=local
# Remote deployment uses https://trader.manojmathivanan.com and /srv/trader storage.
```

#### .github/workflows/checks.yml

```yaml
name: Checks
on:
  push:
    branches: [main]
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'
      - uses: actions/setup-node@v4
        with:
          node-version: '22'
      - run: pip install -r requirements-lock.txt
      - run: npm ci && npm run check && npm test
      - run: python -m unittest discover -s tests -q
```

## Future production design — not the current runtime

The numbered sections below preserve the production architecture and intent. Section references
such as §3/§4.2 inside this roadmap refer to the numbered production sections, not the current
shared rebuild. The remote file-based MVP is deployed; that does not complete the proposed Timescale/Redis/live-broker platform. Database and queue migration are deferred by owner decision. Preserve the shared UI and independent environment histories; future migration must be explicit and must never overwrite paper ledgers.

## 1. What this is — future production scope

A personal, multi-strategy automated trading platform for NSE/BSE (Indian equities), starting with
rules-based swing trading and expanding over time to intraday momentum, scalping, and options
strategies — all run by one person (the owner), from one codebase, on one cheap VPS.

The owner's workflow for every strategy, present or future, is the same: pick a pattern/strategy →
backtest it → paper trade it for some weeks → go live with real capital — independently per
strategy.

This is one project within the owner's personal portfolio website (where each project gets its own
subdomain and repository). The purchased parent domain is manojmathivanan.com and Trader uses trader.manojmathivanan.com. The root domain and other projects are reserved, not implemented by this MVP. Current Trader DNS/hosting are specified above.

### Explicit non-goals
- Not a SaaS product, not multi-tenant, not for managing other people's money.
- Not high-frequency / sub-millisecond trading — "scalping" here still means seconds-to-minutes
  holding periods, not co-located HFT.
- Not trying to minimize infrastructure cost at the expense of correctness (e.g. we still use a
  real relational database, not spreadsheets) — but we do consistently pick the cheapest tool that
  is still correct, because this runs on a single inexpensive VPS for one user.

---

## 2. Design reference: bananapatterns.com

The owner's inspiration for the *methodology and presentation* (not the code) is
[bananapatterns.com](https://bananapatterns.com/) — a rules-based NSE/BSE stock screener. Its
relevant characteristics, which this platform's UI and reporting should carry over:

- **Methodology, not tips.** Every pattern is a published, fixed rule applied uniformly across the
  whole universe — no hand-picking, no results selected after the fact.
- **Risk-first framing.** Risk per trade is decided before entry (e.g. ~1.5% of capital), with a
  hard stop (e.g. ~8%), a move to breakeven once a trade is working, then a trailing stop. The
  site states plainly that it wins roughly 1 in 3 trades, and that the edge is the asymmetry
  between large winners and small, capped losses — not prediction accuracy.
- **Full transparency in backtests.** Losing trades are shown beside winners; nothing is cherry
  picked. Backtests are explicitly labeled hypothetical, not a live track record.
- **UI characteristics to emulate:**
  - Light cream theme with green accents by default (dark toggle may remain available), minimal,
    clean typography and no clutter.
  - Candlestick/OHLC charts — the reference site uses
    [KLineChart](https://github.com/klinecharts/KLineChart) (Apache 2.0 licensed, free to reuse).
  - A "today's scan" / live view surfacing current signals (their "breakout record" — every
    breakout in the last few trading days).
  - A per-symbol search that pulls up a chart annotated with how that stock relates to the pattern.
  - A plain-language "how this works" explanation attached to each screen/pattern.
  - A step-by-step depiction of the trade lifecycle (buy the breakout → set a stop → move to
    breakeven → trail the stop → exit when the trend breaks).
  - A disclaimer footer (not investment advice, not SEBI-registered, backtests are hypothetical) —
    relevant here too since this is personal software making real trading decisions, not a
    regulated advisory product.

For this platform: the same visual language (light cream/green default, clean charts, transparent backtest
reporting, explicit risk framing) should be applied **per strategy tab** (see §4.7) rather than per
"screen" as on the reference site, since this platform has one portfolio/account per strategy
rather than one unified screener.

---

## 3. Functional requirements

These are the decisions that constrain every module below. Treat them as acceptance criteria.

1. **Multi-strategy, start with one.** Phase 1 ships swing trading only using the Banana-aligned
   VCP, Blue sky, Multi-year and IPO-base screens on NSE equities. Intraday momentum, scalping, and options are
   planned future phases, not built now — but the architecture must not need a rewrite to add them.
2. **One Portfolio per strategy (1:1).** Each strategy has exactly one Portfolio: its own capital
   allocation, its own paper/live ledger, tracked completely independently of every other strategy.
3. **Paper → live is a mode transition, not a fork.** When a strategy's portfolio is ready to go
   live, its `mode` flips from `paper` to `live` on the *same* portfolio record — it does not spawn
   a second, parallel portfolio. The paper-trading history should remain visible after the switch
   (for comparing pre/post-live behavior), distinguished by mode and timestamp.
4. **Execution adapter (broker) differs per portfolio.** Different strategies may trade through
   different brokers (e.g. swing via Zerodha, intraday via Upstox). The broker adapter is resolved
   per portfolio, not configured globally.
5. **Position sizing is configurable per portfolio, and the sizing *algorithm* itself is pluggable**
   — not just its parameters. Equity strategies (swing/intraday/scalping) use a percent-of-capital
   risk sizer; options strategies will need a Greeks/premium-at-risk based sizer later. A portfolio
   references which sizer it uses plus that sizer's own config.
6. **Database and data ingestion are shared infrastructure**, used by every strategy — one
   database, one ingestion subsystem — but internally split by data granularity (daily bars,
   intraday bars, ticks, options-chain snapshots) because volume and shape differ enormously
   between them.
7. **Dashboard/UI is one shared application, navigated as one tab per strategy** — not a single
   generic/combined page. Each tab is self-contained and shows only that strategy's own portfolio
   (paper or live), own data pipeline status, own configuration, own backtests/jobs/logs. A future
   "combined" tab that cross-references signals from multiple strategies is anticipated but
   explicitly out of scope for now — it will be purpose-built later, not auto-generated.
8. **Everything operationally tunable must be configurable from the UI, without a deploy:** which
   data source is active, which symbols/universe are scanned, each pattern's thresholds, each
   portfolio's capital/mode/broker account/sizer choice and that sizer's parameters, and which jobs
   run automatically. Backend code changes are reserved for **bug fixes** and for **adding new
   types** (a new strategy, a new sizer algorithm, a new broker adapter, a new data source) — not
   for routine tuning.
9. **New strategies get their own tab automatically.** Each pluggable strategy (and sizer, broker
   adapter, data source) declares its own small config schema (field names/types/defaults)
   alongside its code. The dashboard has one reusable "strategy tab" template that renders a
   settings form generically from whatever schema a plugin declares, plus standard
   data/jobs/portfolio sections. Adding a new strategy should require backend work only — no
   hand-built frontend screen per strategy.
10. **Every triggered action is a trackable Job.** Whether triggered by a nightly cron schedule or
    manually from the UI (e.g. "re-fetch today's data", "run a backtest"), the action is recorded
    with a status (queued/running/success/failed) and structured logs, retrievable from the UI.
    This is the mechanism for "show me what went wrong" when a trigger fails.
11. **Broker credentials are managed through the UI and encrypted at rest.** Once saved, a secret
    is never redisplayed in plaintext.
12. **Backtests must avoid survivorship bias** — the historical instrument universe must include
    delisted/merged symbols, not just symbols currently listed.
13. **One shared risk/sizing *implementation* (code) across backtest, paper, and live, for a given
    portfolio** — the same `position_sizer.py`/`stop_manager.py` code path, not three separate
    implementations, so tested behavior and real behavior cannot silently diverge. **This is about
    code, not config or capital:** each portfolio still has its own independent `sizer_config`
    (its own risk %, stop %, trailing rule) — risk parameters are never pooled or shared *across*
    strategies. "Shared" means swing's backtest/paper/live all run swing's numbers through the same
    formula; it does not mean swing and intraday share a risk budget.
14. **Runs on a single inexpensive VPS.** Every infrastructure choice below is picked to be the
    cheapest option that is still correct for a solo operator — not the most scalable option in the
    abstract.
15. **Live stops are exchange-side resting orders, not software-polled.** A stop-loss for a live
    position must be a real resting order placed on the exchange via the broker (e.g. an SL-M
    order), kept at the level `stop_manager.py` computes and modified as a trade trails. A VPS
    crash or network blip must not mean the stop-loss stops existing — if the process is down, the
    exchange still holds the protective order. Paper mode may keep simulating this in software
    since there is no real exchange order to place.
16. **Backtest and paper execution must both model realistic trading costs** — brokerage, STT,
    exchange charges, and an explicit slippage assumption — using the same cost model in both
    places. Without this, Phase 6's "does paper match backtest" check could look clean while both
    numbers are optimistic in the same direction.
17. **Every runner must reconcile against the broker's actual state before resuming trading
    after a restart.** If `batch_runner`, `streaming_runner`, or the job worker restarts while a
    live position is open, it must pull `BrokerAdapter.get_positions()`/order status and compare
    against local DB state *before* placing or modifying any order, halting and alerting on a
    mismatch rather than silently continuing on possibly-stale local state.

---

## 4. Architecture

### 4.1 Shape

A shared core kernel, plus thin per-strategy plugins, plus a first-class Portfolio concept that
isolates capital/account/sizing per strategy, plus a Jobs framework that makes every action
(scheduled or manual) trackable, plus a dashboard with one tab per strategy built from a reusable
template.

```
                 ┌─────────────────────────────────────────────────────┐
                 │                     Dashboard (UI)                   │
                 │  one tab per strategy, rendered from a shared        │
                 │  template + each plugin's declared config schema     │
                 └───────────────────────┬───────────────────────────────┘
                                          │ (triggers / reads)
                 ┌────────────────────────▼───────────────────────────┐
                 │                    Jobs framework                    │
                 │   every trigger (cron or manual) = a tracked Job      │
                 │   with status + structured logs                      │
                 └───────────────────────┬───────────────────────────────┘
                                          │
     ┌──────────────┬──────────────┬─────▼──────┬──────────────┬───────────────┐
     │  Ingestion    │   Strategy   │  Backtest  │  Portfolio    │  Execution     │
     │ (market data) │   plugins    │   engine   │ (capital/acct)│ (broker calls) │
     └──────┬────────┴──────┬───────┴─────┬──────┴──────┬───────┴───────┬────────┘
            │               │             │             │               │
            └───────────────┴─────────────┴─────────────┴───────────────┘
                                          │
                                 ┌────────▼─────────┐
                                 │     Database       │
                                 │ Postgres+Timescale  │
                                 └─────────────────────┘
```

### 4.2 Module map

**Shared core (one instance, used by every strategy):**

| Module | Responsibility |
|---|---|
| `core/instruments/` | `Instrument` base + `Equity` / `Future` / `Option` subtypes; symbol/lot-size/expiry/strike registry, including delisted symbols (survivorship-bias avoidance). |
| `core/market_data/` | `MarketDataProvider` interface; `historical/` (EOD + intraday historical pulls), `realtime/` (broker websocket streaming, phase 2+), `options_chain.py` (phase 3+). One interface regardless of data source. |
| `core/db/` | SQLAlchemy models + Alembic migrations. One database, tables split by granularity (see §4.5). |
| `core/events/` | Redis pub/sub wrapper — the shared nervous system once live ticks need to reach multiple consumers at once (strategy, execution, dashboard). Dormant/unused until phase 2 (intraday). |
| `core/risk/` | `position_sizer.py` (the pluggable-per-portfolio sizer interface + a `PercentRiskSizer` implementation for phase 1), `stop_manager.py` (computes stop-loss / breakeven / trailing levels — shared code across backtest/paper/live, but each portfolio's own `sizer_config` parameters; for live portfolios this feeds `order_manager.py`, which is responsible for actually placing/modifying the real exchange-side stop order — see requirement 15, §3), `account_risk.py` (a lighter check: only relevant when two *live* portfolios happen to share one real broker account, verifying their combined margin use doesn't exceed that account's capacity). |
| `core/execution/` | `broker_adapter.py` (interface: place/modify/cancel order, get status, get positions), `broker_account.py` (maps a `broker_account_id` to a concrete adapter instance + credentials), `adapters/` (`paper.py`, `kite.py`, `upstox.py`, ...), `order_manager.py` (order state machine: PENDING → SENT → FILLED/REJECTED/CANCELLED; for live positions, keeps a real resting stop-loss order on the exchange and modifies it as `stop_manager.py` trails it — requirement 15; reconciles local state against `BrokerAdapter.get_positions()` both periodically *and* mandatorily on every process start before resuming any trading action — requirement 17), `position_manager.py` (per-portfolio positions/P&L ledger, costs included — see `backtest/metrics.py`). |
| `core/backtest/` | `engine.py` (orchestrates a run), `simulators/` (`daily_bar.py` for phase 1, `intraday_bar.py` / `tick.py` / `options_chain.py` for later phases — all behind one `MarketSimulator` interface), `metrics.py` (win rate, R-multiples, drawdown, equity curve, **and modeled trading costs — brokerage, STT, exchange charges, slippage, requirement 16** — one shared implementation, same cost model used by the paper adapter's simulated fills, so every strategy is scored identically and paper vs. backtest comparisons aren't both optimistic in the same direction). |
| `core/portfolio/` | `models.py` (the `Portfolio` entity — see §4.3), `manager.py` (CRUD + the read paths the dashboard needs), `executor.py` (fans a strategy's signals out to its one bound portfolio: size the signal via that portfolio's sizer, apply stops, call its broker adapter — see §4.4). |
| `core/jobs/` | `models.py` (`Job` entity: type, strategy, status, timestamps, triggered-by), `queue.py` (thin wrapper over RQ, using the same Redis instance as the event bus), `logger.py` (structured logging helper every ingestion/backtest/scan module writes through, so logs land in a queryable `job_logs` table), `worker.py` (the RQ worker process that actually executes queued jobs — its own systemd service). |

**Strategy plugins (the only non-shared part — one package per strategy type):**

| Module | Responsibility |
|---|---|
| `strategies/swing_patterns/` | Migrate the current VCP, Blue sky, Multi-year and IPO predicates into production `Pattern` plugins with a common interface; retain explicit legacy backtest compatibility. Add historical relative-strength filters only after sourcing and validating that data. `scanner.py` performs the nightly universe scan; `strategy.py` implements `core.strategy.base.Strategy` and declares its UI config schema. |
| `strategies/intraday_momentum/` | Phase 2. Same shape as swing_patterns; `trigger_mode=STREAMING`, `granularity=INTRADAY_1M`. |
| `strategies/scalping/` | Phase 2/3. Same shape; reacts to ticks (`on_tick`) rather than bars. |
| `strategies/options/` | Phase 3. Same shape; adds `greeks.py` (Delta/Gamma/Theta/Vega) and uses a Greeks-aware sizer instead of `PercentRiskSizer`. |

**Orchestration:**

| Module | Responsibility |
|---|---|
| `runners/batch_runner.py` | Cron/systemd-timer triggered. For `BATCH`-mode strategies (swing today): pull latest data → `strategy.on_bar()` → `core/portfolio/executor.py` → notify. Each invocation is wrapped as a Job. |
| `runners/streaming_runner.py` | Phase 2+. Long-running process with a market-hours lifecycle, subscribes to the event bus, calls `on_tick()`/`on_bar()`, routes through the same portfolio executor. Runs as its own systemd service so a crash doesn't affect batch jobs or the dashboard. |

**Dashboard:**

| Module | Responsibility |
|---|---|
| `dashboard/api/` | FastAPI app. Basic auth from day one (this app can trigger real actions and, eventually, will hold live broker credentials — it is not "read-only until public"). **Owner decision: Basic Auth is accepted through Phase 7; 2FA and rate-limiting are optional future improvements, not prerequisites added by this document.** Routers: one generic "strategy tab" router parameterized by strategy name (config, data/pipeline status, jobs/backtests/logs, portfolio/positions — rendered from that strategy's declared schema and its one Portfolio), plus `jobs.py` (trigger/list/logs), plus `broker_accounts.py` (CRUD, writes go through encryption, reads never return the raw secret). |
| `dashboard/web/` | Frontend. One reusable "Strategy Tab" component instantiated per registered strategy (reading the backend's strategy registry) — not a bespoke screen per strategy. A distinct, separately-built "combined" view is anticipated for later (§3, requirement 7) but not built now. |

**Other:**

| Module | Responsibility |
|---|---|
| `notifications/telegram.py` | Scan-complete / signal / order / error alerts. Shared across every strategy. |
| `ingestion/` | `eod_equity.py` (phase 1), `intraday_bars.py` / `options_chain_snapshot.py` (later phases). Each ingestion run executes as a Job. |

### 4.3 The Portfolio model

```python
class PortfolioMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"

class Portfolio:
    id: str
    name: str                     # e.g. "swing", "intraday_momentum"
    strategy_name: str             # 1:1 with a strategy
    mode: PortfolioMode             # paper -> live is a transition on this same row
    mode_changed_at: datetime | None  # when it last flipped, so paper history stays distinguishable
    capital_allocated: float
    broker_account_id: str | None   # which real broker/credentials this portfolio trades through; null while paper
    sizer_type: str                 # e.g. "percent_risk", later "greeks_aware"
    sizer_config: dict              # e.g. {"risk_pct": 1.5, "stop_pct": 8, "trail_rule": "..."}
    status: str                     # "active" | "paused" | "closed"
```

A strategy's `on_bar()`/`on_tick()` produces `Signal` objects with no capital or account attached.
`core/portfolio/executor.py` is what turns a signal into a sized, risk-checked, routed order for
that strategy's one portfolio — this is the seam between "what to trade" (strategy) and "with what
money, through what account" (portfolio).

### 4.4 Execution: shared interface, swappable implementation

`BrokerAdapter` (interface) and `order_manager.py` / `position_manager.py` (broker-agnostic logic)
are shared. The *concrete* adapter — which real broker, which credentials — is selected per
portfolio via `broker_account_id`. A `broker_accounts` table holds, per account, which broker it is
and a reference to its (encrypted) credentials; a portfolio's `broker_account_id` points at one.
Paper-mode portfolios skip this and always use the `PaperBrokerAdapter`.

### 4.5 Config vs. code boundary

This is the principle behind requirement 8 (§3) — stated explicitly because it should guide every
future addition to this codebase:

- **Code** (repo, touched only for bug fixes or to add a new *type*): pattern-matching logic, sizer
  formulas, broker API call mechanics, backtest simulation mechanics.
- **Config** (database, edited via the UI, takes effect without a deploy): which data source is
  active, the scan universe, each pattern's thresholds, each portfolio's capital/mode/broker/sizer
  choice and that sizer's parameters, which jobs auto-run.

The mechanism that makes "new strategy = backend only, UI just works" true: every pluggable thing
(a `Pattern`, a `Strategy`, a sizer, a broker adapter, a data source) declares its own config schema
next to its code (field names, types, defaults — e.g. a small Pydantic model). The dashboard's
strategy-tab template renders a settings form generically from whatever schema a plugin declares.
Nobody hand-builds a form per strategy.

### 4.6 Jobs framework

Every action — the nightly cron batch run *and* a manual "run backtest now" click in the UI — goes
through the same `Job` wrapper: a row is created (`queued`), handed to an RQ worker (over the same
Redis used for the event bus — no new infrastructure piece), execution logs are written through
`core/jobs/logger.py` into a `job_logs` table keyed by the job's id, and the row is updated to
`success`/`failed` on completion. The dashboard's jobs view lists recent runs (filterable by
strategy/type/status) and lets you open any run's logs — this is the answer to "let me see what
went wrong."

### 4.7 Dashboard structure

Navigation is one tab per registered strategy (read from the backend's strategy registry — adding
a strategy makes its tab appear with no frontend changes). Each tab, built from one shared
template, shows:

1. **Config** — this strategy's tunable fields, rendered from its declared schema (universe
   selection where applicable, pattern thresholds, portfolio capital/mode/broker/sizer).
2. **Data/pipeline status** — last ingestion run, success/failure, record counts.
3. **Jobs/backtests/logs** — trigger a backtest or a manual data refresh, see job history and logs.
4. **Portfolio** — this strategy's one portfolio: positions, P&L, equity curve, trade log (paper or
   live, whichever mode it's currently in).

A separate "combined" tab — cross-referencing signals across multiple strategies — is a known
future requirement but is explicitly **not** part of this build; it will need custom logic when
it's actually built, unlike the per-strategy tabs which share a template.

Visual style should follow §2 (light cream/green default, clean OHLC charts via KLineChart, transparent backtest
reporting with both wins and losses shown, explicit risk-first framing, a disclaimer note since
this platform makes real trading decisions).

### 4.8 Database schema (tables)

| Table | Purpose |
|---|---|
| `instruments` | Symbol master: equities/futures/options, lot sizes, tick sizes, listing/delisting dates. |
| `daily_bars` | EOD OHLCV — phase 1. Timescale hypertable, chunked by month. |
| `intraday_bars` | Minute bars — phase 2. Hypertable, chunked by day. |
| `ticks` | Tick data — phase 2/3. Hypertable, chunked by day, compressed after ~7 days, pruned after 30-90 days (keep aggregated bars long-term instead). |
| `options_chain_snapshots` | Strike/expiry/OI/IV/Greeks snapshots — phase 3. |
| `broker_accounts` | id, broker name, alias, reference to encrypted credentials. |
| `portfolios` | The Portfolio model from §4.3. |
| `signals` | Every signal a strategy emitted (any mode), for audit/analysis. |
| `orders` | Order state-machine rows, tagged by `portfolio_id`. |
| `positions` | Open/closed positions, tagged by `portfolio_id` and mode. |
| `backtest_runs` / `backtest_trades` | One row per backtest execution / per simulated trade. |
| `jobs` | Every triggered action (cron or manual): type, strategy, status, timestamps. |
| `job_logs` | Structured log lines keyed by `job_id`. |

### 4.9 Repository layout

```
trader_all/
├── README.md                    # this document
├── requirements.txt             # see §9
├── .env.example                 # see §9 — infra-level config only, NOT broker secrets
├── .gitignore                   # see §9
├── core/
│   ├── instruments/
│   ├── market_data/
│   │   ├── historical/
│   │   └── realtime/
│   ├── db/
│   │   └── migrations/
│   ├── events/
│   ├── risk/
│   ├── execution/
│   │   └── adapters/
│   ├── backtest/
│   │   └── simulators/
│   ├── portfolio/
│   └── jobs/
├── strategies/
│   ├── swing_patterns/
│   │   └── patterns/
│   ├── intraday_momentum/
│   ├── scalping/
│   └── options/
├── runners/
├── ingestion/
├── dashboard/
│   ├── api/
│   │   └── routers/
│   └── web/
├── notifications/
├── infra/
│   ├── docker-compose.yml
│   ├── Caddyfile
│   └── systemd/
└── tests/
```

---

## 5. Deployment architecture

- **Repo:** public `manoj-mathivanan/trader_all`, shared code/configuration on main. Agent commits/pushes are authorized by the owner; server-side commits/pushes and data publication are not. The services below describe a future platform, not the current one-container deployment.
- **Host:** a single inexpensive VPS (Hetzner/DigitalOcean class, ~$5-20/month).
- **Services (Docker Compose):**
  - `db` — `timescale/timescaledb` image (Postgres + the Timescale extension; one engine, no
    separate time-series database).
  - `redis` — used both as the event bus (pub/sub) and the job queue (RQ).
  - `dashboard` — the FastAPI app (`uvicorn dashboard.api.main:app`).
  - `worker` — the RQ worker process consuming queued jobs.
  - (phase 2+) a `streaming` service for `runners/streaming_runner.py`.
- **Reverse proxy:** Caddy, auto-HTTPS, routes `trader.<domain>` → the dashboard container.
- **Scheduling:** a systemd timer triggers `runners/batch_runner.py` shortly after NSE close
  (15:30 IST) on weekdays; the streaming runner (phase 2+) runs continuously during market hours as
  its own systemd service, independent of the dashboard/batch services so a crash there doesn't
  affect anything else.
- **CI/CD:** manual deploys (SSH + `docker compose up -d` / `git pull` on the VPS) through Phase 6
  (paper trading). Revisit before Phase 7 — once a portfolio is about to go live with a real broker
  and real capital, deploys should become a deliberate, reviewed step (e.g. GitHub Actions running
  tests before a manual-approval deploy), not auto-push-to-prod.
- **Secrets:**
  - Infra-level connection strings (`DATABASE_URL`, `REDIS_URL`) and a server-side
    `SECRET_ENCRYPTION_KEY` live in `.env` (never committed — see `.gitignore`).
  - Broker API credentials are entered through the dashboard UI, encrypted at rest using that
    server-side key, and never redisplayed in plaintext once saved.
- **Site-level context (not part of this repo's build):** this project is reachable at its own
  subdomain (`trader.<domain>`) as one project among several on the owner's personal portfolio
  site; DNS/subdomain wiring is a separate, non-blocking task.

---

## 6. Plan of action (build phases)

**Phase 0 — Edge validation gate for production progression**
The original ordering required this spike before building any dashboard. The owner superseded that
ordering: the local dashboard and real-data research increment were built first so rules can be
inspected and tuned interactively. Production paper simulation and the file-based remote MVP are also authorized. The gate still
applies before live trading or production infrastructure. Use a plain Python/pandas script or the local engine with a fixed data snapshot and
walk-forward split.
- Validate the four implemented screens (VCP, Blue sky, Multi-year, IPO base) against the
  explicit predicates and configurable defaults in the current specification. Add missing
  historical RS/universe/adjustment inputs before claiming reference parity. Legacy breakout
  remains compatibility behavior for saved experiments, not a fifth visible built-in screen.
- **Walk-forward, not fit-and-test-on-the-same-data:** tune parameters on an earlier slice, validate
  on a held-out later slice. The local working range is ten years or less; an eight-year walk-forward
  remains the production research target.
- Include trading-cost modeling (brokerage, STT, slippage — requirement 16) from the start, so the
  edge estimate isn't inflated.
- **Gate:** only proceed to live trading and production infrastructure if the out-of-sample
  result shows a credible edge (positive
  expectancy, a believable win-rate/R-multiple asymmetry — not just a curve-fit on the full
  window). If it fails the gate, revise and retest the rules using the local research
  engine before progressing to production infrastructure or live execution.
- The local dashboard/backtest increment is already implemented. Keep this gate as a research
  decision, not as a reason to remove the working control panel.

**Phase 1 — Foundation**
Scaffold the repo layout (§4.9). Stand up the VPS skeleton: Docker Compose with `db` (Timescale),
`redis`, `caddy`, `worker` — running but mostly empty. Define the core data models: `Instrument`,
`Portfolio`, `broker_accounts`, `Job`/`job_logs`, and the `daily_bars` table (other granularity
tables scaffolded but unused).

**Phase 2 — Dashboard shell + Jobs framework**
Build the FastAPI app with basic auth, the generic strategy-tab template, and the Jobs
router (trigger/list/logs) with the RQ worker wired up — prove the whole chain end-to-end with a
test-only diagnostic job (trigger → queued → run → logged → visible). Migrate the existing real
job handlers afterward; diagnostic fixtures must never appear as market data or portfolio results.

**Phase 3 — Data pipeline (swing scope)**
Use the owner's existing Upstox account as the primary historical EOD data source (no new vendor
signup needed to start) and build EOD ingestion as a Job type — start with Nifty 50 to validate the
pipeline, then expand to the full liquid NSE/BSE universe. Populate the instrument registry,
including delisted symbols. **Known risk to check early:** broker historical APIs (Upstox
included) typically only cover currently-listed instruments, not delisted/merged ones — and the
backtest window is long enough that survivorship bias (requirement 12,
§3) is a real concern. Before relying on Upstox alone for the full 8-year backtest, verify it
actually returns data for delisted/merged NSE/BSE symbols over that window; if it doesn't, a
supplementary source for delisted-symbol history (e.g. a paid vendor, just for that gap) will be
needed — don't silently backtest survivorship-biased.

**Phase 4 — Swing strategy + backtesting**
Refine the Banana-aligned screen rules in `Pattern` plugins —
starting from whatever parameters pass the Phase 0 gate, using the proper backtest engine.
Build the daily-bar backtest simulator and the shared metrics module (including cost modeling,
requirement 16), backtesting against the available validated history using the same walk-forward discipline
as Phase 0 (tune on an earlier slice, validate on a held-out later slice — not fit-and-tested on the
same window). Make backtests triggerable from the UI with parameters (date range, pattern
selection); show results and logs in the swing tab. The working Banana screen thresholds and
execution defaults are specified in the authoritative implementation contract above; they remain
UI-editable hypotheses until RS and historical-universe parity is validated.

**Phase 5 — Portfolio, risk, and paper execution**
Implement the swing Portfolio with `PercentRiskSizer` *defaults* of **risk_pct = 1.5, stop_pct = 8,
winner exit = 50-day trail** (with 30-week trail and +25% alternatives) — these are pre-filled
values on the portfolio's config form, not hardcoded constants; the owner can change risk_pct,
stop_pct and the winner-exit rule from the UI at any time (requirement 8). `capital_allocated` is likewise a plain configurable field on the
Portfolio, set by the owner when the portfolio is created in the dashboard — no spec-level default
is needed for it. Build the `PaperBrokerAdapter`, order manager,
and position manager — the paper adapter's simulated fills must deduct the same modeled brokerage/
STT/slippage costs as the backtest engine (requirement 16), so paper P&L is never flattering
relative to what live would actually cost. Wire `batch_runner.py` so the nightly cycle (itself a
Job) runs: ingest → scan → signal → size via the portfolio's sizer → paper order (net of costs) →
notify. Swing tab now shows live paper positions and an equity curve.

**Phase 6 — Paper trading run**
Let it run nightly for several weeks. Monitor via the dashboard and Telegram alerts. The key
check: does paper performance track what the backtest predicted? Drift between the two usually
means a bug in the shared risk/execution path (since backtest and paper should use identical logic
— requirement 13, §3).

**Phase 7 — Go live (swing only)**
No broker is pre-selected for live trading — the owner wants to paper trade first and decide the
live broker later, which is exactly what the `BrokerAdapter` interface (§4.4) is for: whichever
broker is chosen, it's a new adapter implementation behind the existing interface, not a redesign.
When ready: implement that real `BrokerAdapter`, create the `broker_account`, enter its credentials
via the UI (encrypted at rest), and flip the swing portfolio's `mode` to live with a small starting
capital. Everything upstream (strategy, risk, portfolio executor) is unchanged — only the adapter
and real money are new. Revisit CI/CD (§5) before this phase.

**Phase 8 and beyond — Expand to the next strategy types**
Repeat phases 3-7 for `intraday_momentum` (this is where `StreamingRunner` and the Redis event bus
get used for the first time), then `scalping`, then `options` (introduces the Greeks-aware sizer,
options-chain ingestion, and multi-leg order support). Each gets its own Portfolio, its own tab, and
optionally its own broker account.

**In parallel, non-blocking:** register/confirm the domain and wire up the `trader.<domain>`
subdomain pointing at the dashboard — can happen any time before the dashboard needs to be
reachable from outside the VPS.

---

## 7. Open questions

Resolved since the first draft of this document:

- **Broker for live trading** — deliberately not chosen yet. Paper trade first; the
  `BrokerAdapter` interface (§4.4) means any broker can be plugged in later without changing
  anything upstream. No action needed now beyond keeping that interface broker-agnostic.
- **Historical EOD data source** — use the owner's existing Upstox account as the primary source
  (see Phase 3 caveat about delisted-symbol coverage below — this is downgraded from "open" to "a
  risk to verify early," not a blocking unknown).
- **Domain** — purchased: manojmathivanan.com, Cloudflare registrar/DNS. Trader HTTPS and DNS are configured at trader.manojmathivanan.com; root/other projects remain future work.
- **Sizer defaults** — confirmed: `risk_pct = 1.5`, `stop_pct = 8`, trail-to-breakeven-then-trail
  (bananapatterns-style), per owner confirmation.
- **Backtest history** — the local working range is `2019-01-01` through `2026-10-05` subject to
  provider availability; Banana comparison uses `2020-01-01` through `2025-12-31`. An eight-year
  walk-forward remains the production research target, not a hardcoded UI range.
- **CI/CD** — confirmed: manual deploys until a portfolio is about to go live with a real broker
  (§5); revisit then.

Also resolved, from a design review pass:

- **Edge validation before building infrastructure** — confirmed: a Phase 0 spike (§6) gates entry
  into production Phase 1. Timescale/Redis/event bus remain gated; the local dashboard and
  production paper simulator and file-based remote MVP are authorized and implemented; local mode is research-only.
- **Options phase ordering** — confirmed: options stay deferred to Phase 8. They need tooling
  (Greeks-aware sizer, chain data) the platform doesn't have yet, and carry materially higher risk
  than equity swing — proving out the operational discipline (reconciliation, exchange-side stops,
  monitoring) on the lower-risk strategy first takes priority over options' larger trading volume.
- **Live stops, cost modeling, restart reconciliation** — all resolved as hard requirements (15,
  16, 17 in §3), not left open. See those requirements and the updated module descriptions in §4.2.

Also resolved, in a later round:

- **Pattern parameter defaults** — resolved for the current increment: start from the Banana screen
  values in the authoritative implementation contract above. All are exposed as UI-editable fields
  on the Swing backtest schema; exact reference parity still depends on RS and historical-universe data.
- **Starting capital** — resolved: it's simply the `capital_allocated` field on the Portfolio,
  set by the owner when creating the portfolio in the dashboard. No spec-level default needed.
- **Dashboard authentication strength** — current public MVP has no login by owner choice.
  Basic Auth remains implemented but unset. Earlier acceptance of Basic Auth for a future
  Phase 7 is a roadmap proposal and does not authorize live execution in this public MVP.
  Revisit access controls explicitly before enabling any live broker account/order path;
  stronger authentication or SSH/VPN/IP restrictions are future options, not current requirements.

Still open — resolve before the relevant phase:

1. **Upstox delisted-symbol coverage** (see Phase 3). Needs to be verified empirically early in
   Phase 3 (and during the local research gate, if the run uses the full validated history) — if
   Upstox's historical API doesn't return data for delisted/merged NSE/BSE symbols, the backtest
   will need a supplementary source for that gap specifically, to avoid survivorship bias
   (requirement 12, §3).
2. **SEBI compliance for the chosen live broker.** Not resolvable until a broker is actually
   chosen (Phase 7) — SEBI's framework around algorithmic/API trading access typically expects the
   broker itself to enforce controls (e.g. 2FA) on API access; confirm the chosen broker's specific
   requirements before going live, not after.

---

## 8. Guardrails for whoever builds this

- **Never commit secrets.** `.env`, broker credentials, DB dumps must never be committed — see
  the current `.gitignore` specification above. Future broker credentials belong in encrypted `broker_accounts` storage, not in
  code or `.env`.
- **Source publication is authorized:** the agent may commit/push shared code/configuration on the owner's behalf. Never publish local/production state or credentials; the production server must never write to GitHub.
- **Keep paper and live code paths identical** except for which `BrokerAdapter` instance a
  portfolio resolves to. Any divergence between them defeats the purpose of paper trading.
- **Avoid survivorship bias** in backtest data — include delisted/merged instruments in the
  historical universe.
- **Prefer the cheapest correct option**, consistent with "runs on one VPS for one user":
  Timescale as a Postgres *extension* (not a separate time-series DB), RQ over the existing Redis
  (not a new broker like Celery/RabbitMQ), systemd timers (not Airflow/Prefect).
- **Every new pluggable piece declares a config schema** (pattern, strategy, sizer, broker adapter,
  data source) so the dashboard's generic strategy-tab template can render its settings without new
  frontend code — this is what keeps "add a new strategy" a backend-only change.
- **One Portfolio per strategy**, capital/account/sizer isolated — do not introduce cross-strategy
  capital pooling or netting beyond the lightweight `account_risk.py` check (§4.2), which only
  applies when two live portfolios explicitly share one broker account.
- **Do not advance to live trading or the deferred database/queue platform before the Phase 0 gate passes.** The current public file-based research/paper MVP is an explicit owner-approved exception. Production paper permission does not certify the edge; local mode remains research-only.
- **Live stops are exchange-side orders, not a polled loop** (requirement 15) — this is a safety
  property, not an optimization; don't simplify it away under time pressure.
- **Reconcile against the broker before resuming after any restart** (requirement 17) — never
  assume local DB state is still accurate after a process restart with a live position open.
- **Cost-model everything** (requirement 16) — a backtest or paper result that doesn't deduct
  brokerage/STT/slippage is not comparable to real trading and should not be trusted as a go/no-go
  signal on its own.

---

## Future infrastructure configuration names

Production-only packages anticipated by the module map: sqlalchemy>=2, alembic, psycopg[binary],
redis, rq, python-dotenv, a scheduling/runtime library if needed, pandas/numpy and a selected
backtest engine if needed, python-telegram-bot; add a selected live broker SDK only after broker
choice. These are planned capabilities, not a second current requirements.txt. No live broker
is selected. Production .env loading and secret handling must be implemented explicitly.

| Variable | Future purpose |
|---|---|
| DATABASE_URL | Postgres/Timescale connection |
| REDIS_URL | Queue and future event-bus connection |
| SECRET_ENCRYPTION_KEY | Server-managed key for encrypted broker credentials |
| DASHBOARD_ADMIN_USER / DASHBOARD_ADMIN_PASSWORD | Accepted Basic Auth credentials; both required together |
| TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID | Optional notification destination once Telegram is implemented |

Broker API credentials belong in encrypted broker_accounts storage entered through the UI,
never this document, source, reports or a committed .env. Future production deployment needs
durable Postgres/Redis volumes, secure key retention, portfolio/job/config/input-history migration,
restart supervision and a recovery rehearsal. Retain the local .gitignore's broad data/key ignores.

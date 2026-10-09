# Trader — research and paper workspace

Company research now includes a **Fundamentals** page with technical candidate scans,
experimental quality scores, and an optional LLM that finds filings and recent news on
the web automatically. Select **Research stock**; no source uploads are required.
Saved reviews preserve citations, risks, contradictions and unknowns. Server API
configuration is required for live research. See [COMPANY_RESEARCH.md](COMPANY_RESEARCH.md).

Trader is a browser-based workspace for researching Indian equity swing strategies and maintaining a simulated portfolio. The same shared application runs locally for research and on a Linux server for research plus persistent paper trading. Desktop and mobile browsers access the same dashboard. It does not place live broker orders.

**Website:** [trader.manojmathivanan.com](https://trader.manojmathivanan.com)
**Repository:** [manoj-mathivanan/trader_all](https://github.com/manoj-mathivanan/trader_all)
**Complete implementation and rebuild specification:** [architecture.md](architecture.md)
**Short deployment reference:** [deploy/README.md](deploy/README.md)

This guide covers the published MVP. Enhancements being developed in other threads become production features only after their code is merged and deployed. The future database/queue sections in architecture.md are a roadmap; current storage is independent JSON files in each environment.

## Features at a glance

| Area | Features |
|---|---|
| Overview | Universe, downloaded coverage, run counts, latest report and recent jobs. |
| Market data | Official Nifty 50 / Nifty 500 membership, ISIN matching, incremental daily-history downloads, company search, candlestick and volume charts. |
| Screens | VCP, Blue sky, Multi-year breakouts and IPO base; configurable filters and named saved screens. |
| Bearish screens | Completed-session downside watchlists: VCP breakdown, 52-week low, Multi-year breakdown and IPO base breakdown. |
| Backtests | Dates, capital, signal priority, entry mode, risk sizing, position limits, stops, breakeven, winner exits, holding limits and explicit costs. |
| Reports | Equity curve, return, drawdown, win rate, expectancy R, profit factor, fees, slippage, warnings, exclusions and sortable trade ledger. |
| Comparisons | Adjust & rerun creates a separate experiment; JSON exports preserve reports. |
| Production paper | Persistent strategy portfolio, daily cycles, optional weekday scheduling, pause/resume entries, positions, fills, accounting and exports. |
| Jobs & logs | Timestamped progress and errors for downloads, backtests and paper cycles. |
| Settings | Research universe selection and automatic history windows and installation-specific token replacement. |

## Guide contents

- [Run on Windows](#run-on-windows)
- [First real-data run](#first-real-data-run)
- [Research boundaries](#research-boundaries)
- [Paper trading in production](#paper-trading-in-production)
- [Independent file storage and security](#independent-file-storage-and-security)
- [Verify](#verify)
- [Local prerequisites and Linux/macOS setup](#local-prerequisites-and-linuxmacos-setup)
- [Dashboard workflow and interpreting results](#dashboard-workflow-and-interpreting-results)
- [Deployment architecture](#deployment-architecture)
- [Deploy to a fresh Ubuntu server](#deploy-to-a-fresh-ubuntu-server)
- [Server operation and code updates](#server-operation-and-code-updates)
- [Backups and restore](#backups-and-restore)
- [Configuration reference](#configuration-reference)
- [Troubleshooting](#troubleshooting)
- [Repository structure and GitHub policy](#repository-structure-and-github-policy)


A light cream-and-green control panel inspired by Banana Patterns. This first increment uses real Upstox daily data, not demo prices. It includes a configurable Nifty 50 / Nifty 500 universe, historical coverage, KLineChart candlesticks, persistent job logs and a parameterized daily breakout backtest. The backend registry already exposes Swing patterns as active and Intraday momentum and Scalping as active research plugins; the shared navigation reads this registry, while planned tabs remain visibly disabled until their data and execution modules are implemented.

## Run on Windows

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-lock.txt
npm.cmd ci
npm.cmd run vendor
.venv/Scripts/python.exe -m uvicorn dashboard.api.main:app --host 127.0.0.1 --port 8765 --no-proxy-headers
```

Open http://127.0.0.1:8765. Local mode supports research and backtests; paper trading and its automatic scheduler run only in production. Keep the terminal running. Use one server process, without `--reload` or multiple workers: the research worker runs in that process.

## First real-data run

1. Settings → save an Upstox **access token** (not API key/secret). New saves are plaintext in the private `upstox.json` file, protected by filesystem permissions and excluded from Git. Existing encrypted records remain readable for migration. A saved token is not necessarily valid; ingestion checks it. Replace expired tokens through the same form.
2. Select Nifty 50 and the history interval. Nifty 500 can be selected later. Saving settings does not fetch anything automatically.
3. Market data → Refresh universe. The app downloads the current official NSE constituents and matches ISINs against Upstox's instrument master. Network/provider failures are recorded as failed jobs, never replaced with fake data.
4. Fetch missing data. The first run downloads the configured range. Later runs reuse complete local coverage and fetch only missing earlier/later boundary ranges, then merge and deduplicate candles. Existing valid data is retained if a provider request fails. Internal missing sessions are not inferred because exchange holidays and suspensions are valid gaps; provider coverage is validated when a range is fetched.
5. Backtests → New backtest. Supply research capital and your all-in buy/sell cost assumptions. Adjust entry, stop, breakeven and trailing rules. The results preserve an input snapshot, configuration, costs, equity curve and complete trade ledger. Use Adjust & rerun to create a comparable new experiment, or export the JSON report.

## Scalping research

Open **Scalping → Scalping backtest** for completed one-minute pullback experiments.
Five-minute EMAs establish trend; one-minute candles and an EMA touch identify the
pullback and next-minute-open entry. Optional VWAP confirmation, fixed pullback stops,
R targets, holding limits, cooldowns, daily loss pauses, cash limits and explicit costs
are configurable. **Compare confirmations** retains candle-only, EMA and EMA + VWAP
trials on identical frozen inputs. Minute coverage estimates include indicator warmup.
**Forward scalping paper** runs separately using fresh Upstox bid/ask quotes and
completed REST candles. Create a portfolio with explicit capital, then start its
quote runner. Pause entries, request liquidation and stop, or export the durable
fill ledger from the same page. Restart discards old signals and recovers saved
exposure. Automatic startup is optional and off initially. Live orders remain unavailable.
See [SCALPING_RESEARCH.md](SCALPING_RESEARCH.md) for exact rules and timing assumptions.

## Intraday momentum research

Momentum now supports a historical fundamentals gate before either position side. New dashboard forms enable it; **Test fundamentals filter** compares matched gate-on/off runs with frozen filing evidence. See [MOMENTUM_FUNDAMENTALS_RESEARCH.md](MOMENTUM_FUNDAMENTALS_RESEARCH.md) for rules, archive limitations and results.

**Test EMA / MACD** runs seven declared trials using genuine completed 10-minute/hourly indicators derived from cached five-minute data. The optional filters and indicator timeframe are separate controls from breakout confirmation. See [MOMENTUM_INDICATOR_RESEARCH.md](MOMENTUM_INDICATOR_RESEARCH.md) for exact rules, warmup, sources, validation criteria and audit failures.

Open **Momentum** in the strategy sidebar to backtest opening-range momentum. The form exposes opening range (5/15/30 minutes), same-clock relative-volume history/threshold, prior daily turnover and ATR filters, scan size, long/short direction, ATR stop, optional R target, risk/capital, entry deadline, mandatory same-day exit, fees and slippage. **Check minute coverage** estimates required stock-sessions before ingestion; **Fetch missing & backtest** reuses the shared five-minute cache and batches missing Upstox history. Reports preserve daily/minute inputs, input hashes, source provenance, daily volume selections, equity and trades. Trade charts show the frozen five-minute entry/exit candles and stop levels. Adjust & rerun keeps momentum settings.

This India adaptation uses completed breakout closes followed by next-bar-open market fills, rather than the source paper's stop entries. Equal capital budgets are reserved per selected stock; there is no leverage, same-day capital recycling or overnight holding. Momentum is research-only; no momentum paper portfolio or streaming/live execution is enabled. Read [MOMENTUM_RESEARCH.md](MOMENTUM_RESEARCH.md) for research comparisons, assumptions and the first real-data experiment.

The Momentum dashboard also shows modeled cost drag, long/short P&L, missed-breakout/VWAP diagnostics and earlier/later session results. Optional VWAP confirmation, ATR breakout buffers and next-bar breakeven stops are editable. **Compare refinements** saves all six declared trials on identical frozen candles and matched costs; **Adjust & rerun** preserves the reference inputs. Missing frozen history or changed hashes halt replay. The initial comparison reduced the sample loss to −0.56% with the 0.1 ATR buffer, but every trial remained negative; defaults are unchanged.

## Research boundaries

New data-validity safeguards and the first local audit are documented in
[DATA_VALIDITY.md](DATA_VALIDITY.md). Market data → **Audit price history** lists
large discontinuities. New backtests and paper sessions halt on suspect gaps;
IPO entries require verified listing dates, and the enabled breadth gate requires
sufficient history coverage. Existing reports and ledgers are preserved.

- Swing backtests follow the Banana Patterns screen set: **VCP**, **Blue sky**, **Multi-year breakouts**, and **IPO base**. The same workflow exposes pivot/close entry, 3/5/8/10 position caps, 7/8/10% stops, 50-day or 30-week trailing exits (or +25%), risk per trade, and a 40%-above-200-day weak-market gate. Costs remain explicit assumptions; defaults are zero for reference-site comparison. Historical membership, RS ranking and broad liquid-universe coverage still need validation before claiming numeric parity.
- Next-open entries use completed previous-session signals (including paper). Backtests also retain Banana pivot/close entry assumptions: pivot fills require the entry-session high to reach the trigger; close fills use the signal close. Daily bars cannot order an entry-session low around a pivot fill, so pivot/close stops start next session. Stops gap at the open where applicable. Closing-price trailing updates activate next session. Slippage and percentage costs apply to both sides. Trade R uses initial price-stop risk; sizing also allows for modeled costs.
- One cash pool per run; no leverage. Simultaneous signals use the configured alphabetical or relative-strength priority. Open-time exits may fund entries; intraday stop proceeds cannot fund earlier open-time buys.
- Warmup-deficient symbols are explicitly excluded. Current constituent selection is survivorship-biased. Corporate actions, historical membership, delisted history, calendar gaps and trading suspensions still need validation. No circuit-limit, participation-cap or non-fill model exists yet. Final positions liquidate at their last available close inside the chosen range.
- Costs are user-supplied aggregate assumptions, not a verified historical brokerage/tax schedule. There is no automatic walk-forward optimizer. Use separate training and untouched validation dates deliberately.
- Results are exploratory and cannot pass the architecture's edge-validation gate yet. Production paper execution is available at the owner's request; live execution remains unavailable.

## Paper trading in production

1. Load real daily history for the selected universe, then open **Paper trading → Create portfolio**. Enter allocated capital, choose a screen or saved preset, and configure risk, exits and modeled costs. The initial defaults are 1.5% risk, an 8% stop and a 50-day winner trail. Capital is required; no portfolio is created automatically.
2. Trading starts with sessions **after the creation date in IST**. Earlier bars are indicator context, never retrospectively recorded as paper trades. Paper uses completed previous-session signals and **next-session open** fills. Choose the same `next_open` entry in a backtest when comparing execution. Existing pivot/close comparison experiments remain supported.
3. **Run daily cycle** fetches Upstox data through the latest completed day (today only after 16:00 IST), scans and processes new observed sessions, applies stops and costs, and records a tracked job. Provider delays can leave the common completed boundary behind today; no prices or exchange holidays are invented. Retry failures from this action after fixing the data/token issue.
4. Optionally enable automatic weekday cycles and set the IST time in **Configure portfolio** (default 16:15). Keep one production dashboard process running. Scheduling makes one attempt per weekday; it does not require Codex to stay open. A failed attempt needs a manual retry. After downtime, the next cycle processes missed completed sessions in order as an EOD replay, not proof of real-time order placement.
5. Inspect cash, marked equity, open positions/stops, realized and unrealized P&L, fees, slippage, equity curve, closed trades and every simulated fill. Export the full portfolio JSON for review; it includes configuration history and cycle snapshots. Fill rows link to job logs, including older jobs beyond the recent list.
6. **Pause new entries** blocks buys while daily cycles keep managing open-position exits. New risk and exit settings apply to new positions. Existing positions keep their recorded exit rules; exit transaction costs use the current configured assumptions. Capital and the captured universe membership are fixed for this portfolio so later research settings cannot remove held instruments or rewrite accounting.

Portfolio storage and APIs are scoped by strategy ID. Each strategy has exactly one portfolio at `data/portfolios/<strategy_id>.json`, with its own allocated capital, configuration, positions, cash, trades, equity and checkpoint. Swing uses production daily cycles; Scalping uses a separate market-hours quote runner available from the Scalping page locally and in production. Momentum paper remains pending. The registry distinguishes batch and streaming triggers so the daily scheduler never submits scalping EOD cycles. No strategy can create a second portfolio or reset its existing one through the create action.

Server startup reads the existing files rather than initializing a new account. Interrupted jobs are marked failed, and interrupted automatic schedule claims are released so the scheduler can resume after restart. Already committed sessions are skipped; uncommitted sessions are replayed from the last durable checkpoint. Regular provider failures still need manual retry. Writes flush to disk before atomic replacement, so interruption during a write preserves the previous complete ledger. Keep the same `data/` directory (or `TRADER_DATA_DIR`) across restarts; the production container retains it on durable storage. Changing UI configuration preserves the ledger and creation date.

The daily engine, percent-risk sizer and fill-cost adapter are shared by backtests and paper. All-in buy/sell rates must be positive and cover the owner's brokerage, STT, exchange charges and other charges; slippage must also be positive. These are configurable estimates, not an automatically verified broker/tax schedule. Cash, orders, positions, trades and the session checkpoint commit atomically to `data/portfolios/swing_patterns.json`. Retry/restart does not duplicate committed fills. Changed candles in previously processed history halt the cycle for investigation.

Paper remains EOD simulation with current-constituent/adjustment limitations and no circuit or participation model. It does not establish an investment edge. PostgreSQL/RQ, Telegram notification configuration and live broker integration remain future work. The current remote MVP uses isolated production files and its own scheduler.

## Independent file storage and security

This research increment uses atomic JSON files under ignored `data/` for candles, jobs, runs and frozen run inputs. It is not the production Postgres/Timescale/RQ platform. Jobs interrupted by server restart are marked failed and can be retried. Only one job runs at a time.

The HTTP app binds to loopback, checks allowed Host headers and browser write origins, and supports Caddy HTTPS when `TRADER_PUBLIC_ORIGIN` is set. Optional Basic Auth uses `DASHBOARD_ADMIN_USER` and `DASHBOARD_ADMIN_PASSWORD` (both required together). `.env.example` documents variables; Python does not automatically load it. The current deployment has no website login by owner choice.

New token saves are plaintext private files protected by filesystem permissions and excluded from Git/backups. Legacy encrypted local records require their original separate key, or reconnect after losing it. Production starts fresh with its own token, data and portfolios; local history is preserved independently.

## Verify

```powershell
npm.cmd run check
.venv/Scripts/python.exe -m unittest discover -s tests -v
npm.cmd test
```

Tests use isolated synthetic unit fixtures and temporary directories only. No synthetic price data is shipped to the dashboard.

Reference APIs: [Upstox historical candles V3](https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/), [instrument master](https://upstox.com/developer/api-documentation/instruments/), [NSE Nifty 50 constituents](https://www.nseindia.com/static/products-services/indices-nifty50-index). KLineChart is vendored from npm with its Apache 2.0 license. No reference-site source code or assets are copied.

## Local prerequisites and Linux/macOS setup

Use **Python 3.13** and **Node.js 22**, matching Docker/CI, plus Git and npm. Install Python dependencies from `requirements-lock.txt` and frontend dependencies from `package-lock.json`. An Upstox access token and network access to NSE/Upstox are required for market-data downloads. Previously saved reports remain local files.

The frontend is plain HTML/CSS/JavaScript served by FastAPI. There is no React build, separate frontend development server, database or Redis service. Node is needed for dependency installation, vendor generation and JavaScript checks; it is not a runtime application server.

Linux/macOS, after installing Python 3.13 and Node 22:

```sh
git clone https://github.com/manoj-mathivanan/trader_all.git
cd trader_all
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
npm ci
npm run vendor
TRADER_ENV=local .venv/bin/python -m uvicorn dashboard.api.main:app --host 127.0.0.1 --port 8765 --no-proxy-headers
```

For the Windows instructions above, clone the same repository and change into `trader_all` first. `TRADER_ENV` defaults to `local`; leave it unset or set `$env:TRADER_ENV = 'local'`. Once installed, `./start.ps1` runs the local app using `.venv`. If script execution is restricted, run the explicit Python command instead. Keep the terminal running and press Ctrl+C to stop.

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). Run exactly one process without `--reload` or multiple workers. Jobs run inside that process, and file storage is designed for one application owner. Do not start another instance pointing at the same data directory.

The chart bundle `dashboard/web/vendor/klinecharts.min.js` is tracked in Git. `npm run vendor` regenerates it from pinned KLineChart 9.8.12. The Dockerfile does not run npm, so regenerate missing vendor assets before building an image.

## Dashboard workflow and interpreting results

### Configure data before research

Choose the research universe in Settings. Market data → Fetch always downloads daily candles for the last calendar year and five-minute candles for the last 10 calendar days, ending on Upstox's latest completed Nifty 50 trading day. It covers all 750 Nifty Total Market stocks, regardless of research-universe selection. Older daily and five-minute history stays available. Quarterly fundamentals for the same stocks are checked after candles, with validated snapshots and older versions retained. The Fundamentals page reports scored snapshot history separately from comparative source filings. Failures are reported per stock and interval while remaining downloads continue; partial jobs retain successful data and can be retried. Saving Settings does not download anything.

The UI requests an **access token**, not an API key/client secret. The token expires daily in the current workflow: replace it in Settings and retry failed provider jobs. No code edit or server rebuild is necessary. “Saved” confirms storage, not validity; provider requests establish validity.

Requested coverage and observed candles are different: a recently listed company can be considered for the whole requested interval but only have candles after its listing. The app does not fabricate prices or infer every internal calendar gap as a missing session. Holidays and suspensions can produce valid gaps.

### Create an experiment

1. Open Backtests → New backtest, or choose a built-in/saved screen in the sidebar.
2. Wait for the downloaded-history check. The popup appears immediately with a loading message; a cold scan takes longer than cached checks.
3. Enter a descriptive name, dates and capital. Review each enabled filter rather than relying only on the screen name.
4. Choose entry mode, risk, maximum positions, initial stop, breakeven threshold, winner exit and holding limit.
5. Set realistic charges and slippage for a costed experiment, or deliberately use zero costs for a reference comparison.
6. Acknowledge the limitations, submit, follow Jobs & logs, then open the completed report.

The base-and-pivot experiment was retired after failing its matched comparison.
Its results and archived replay instructions remain in
[BASE_PIVOT_RESEARCH.md](BASE_PIVOT_RESEARCH.md). Existing Blue sky paper rules remain unchanged.

| Configuration | Interpretation |
|---|---|
| Pivot entry | Simulated trigger-price fill when the session high reaches the pivot. Daily OHLC cannot resolve the ordering of that entry and the session low. |
| Close entry | Simulated entry at the signal close. |
| Next-open entry | Completed previous-session signal followed by next-session open; choose this for comparison with paper execution. |
| Risk per trade | Initial-stop-based position sizing, constrained by cash and position limits. |
| Breakeven R | Threshold expressed as a multiple of initial price-stop risk. |
| Winner exit | Configured moving-average trail or +25% target. Other saved protection/holding rules also matter. |
| Charges and slippage | User-supplied execution assumptions; 1 basis point equals 0.01%. |
| Signal priority | Alphabetical or configured relative-strength order when candidates compete for capacity. |

The safe-window suggestion accounts for downloaded history and warmup. Adjust & rerun preserves the historical experiment's explicit dates instead of silently changing them. A requested end beyond coverage needs a date correction or an extended history setting followed by a fetch.

The Run button has a nearby explanation when disabled: an active job, missing symbols, insufficient history or a pending submission. Errors are visible on mobile too. Only one job runs at a time.

### Scan bearish setups

Long backtests, including Blue sky, also support **Intraday** in the holding-period selector. Use **Next session open**: the prior completed daily setup qualifies the stock, entry buys at 09:15 IST, and the position sells by the configured cutoff (15:00 IST by default). These runs use frozen five-minute candles, a 1x capital cap, stop-first handling for ambiguous candles, and session-end drawdown. Swing remains the default for long backtests. Changing the holding period does not automatically tune the daily strategy's stop or target.

Choose a screen under **Bearish screens** in the sidebar, adjust its filters, then select **Scan bearish setups**. VCP breakdown looks for shrinking price ranges and volume followed by a close below support; 52-week low tests a close below the prior 252-session low; Multi-year breakdown tests a year-plus base floor; IPO base breakdown requires verified IPO metadata and a break below a young listing's base.

Defaults require price below a falling 200-session SMA, a 126-session relative-strength percentile no greater than 30, and weak market breadth (no more than 40% above their 200-session SMA, with at least 80% universe history coverage). Volume and liquidity filters remain editable. All values are research assumptions, not validated profitability claims.

Scans use the newest downloaded completed session before today in IST, report that date, and exclude symbols with stale or insufficient history. Existing listing and corporate-action handling applies. Results show broken support, close, volume ratio, relative strength and links to charts.

Select **Backtest this screen** to run historical short research. New dialogs default to **Intraday**: qualify on the previous completed daily session, sell at the next regular-session 09:15 open, and buy back by **15:00 IST** (editable in five-minute steps). Historical Upstox five-minute candles are cached separately and frozen with each report. The cutoff cover uses its bar open; no future candle high, low or close affects that fill. Stops and targets execute intraday; ambiguous stop/target candles assume stop first. Missing regular-session or cutoff candles halt the run rather than substituting daily prices. Positions never carry overnight. Fees apply to their actual buy/sell side; capital remains constrained to 1x entry notional. Drawdown is measured at session end. Broker-specific eligibility, actual fills, margins and auto-square-off charges remain unverified. Paper trading remains long-only.

Older **Swing** research reports remain available with their original holding rules. Swing mode assumes overnight borrowing and can model annual borrow costs; it is not suitable for a broker without stock borrowing. Use a saved `comparison_run_id` to reuse audited frozen daily inputs when comparing strategies. The reference snapshot is audited again; current provider data never replaces it silently.

### Review and compare

Review drawdown, costs, skipped entries, exclusions and individual trades alongside return. Sort the trade ledger; use Adjust & rerun to change one assumption at a time while preserving the original run. Export JSON for independent review or backup. Use separate training and untouched validation dates; there is no automatic walk-forward optimizer.

Backtests save a report/configuration and a full frozen input snapshot. Updating current market data does not rewrite old experiments. These snapshots improve reproducibility but can consume gigabytes across many large experiments. Source repository size and application data size are separate concerns.

## Deployment architecture

```mermaid
flowchart TD
    Browser[Desktop or mobile browser] -->|HTTPS| Caddy[Caddy on VPS: ports 80 and 443]
    DNS[Cloudflare DNS-only record] -. resolves hostname .-> Caddy
    Caddy -->|loopback HTTP port 8765| App[Docker: one FastAPI / Uvicorn process]
    App --> Worker[In-process serial job worker]
    App --> Scheduler[Production paper scheduler]
    App --> Data[Durable JSON: /srv/trader/data]
    App --> Private[Private token: /srv/trader/private]
    Worker --> Providers[Upstox and NSE]
    GitHub[GitHub main: shared source] -->|manual pull and rebuild| App
    Timer[systemd backup timer] --> Backup[Stop, snapshot, archive, restart]
    Data --> Backup
    Backup --> Archives[/srv/trader/backups]
```

| Component | Current deployment inventory |
|---|---|
| Website | `https://trader.manojmathivanan.com` |
| Domain organization | `trader` is this project; the root domain and other subdomains are reserved for other projects. |
| DNS | Cloudflare DNS-only A record `trader` → `143.244.142.226`. |
| VPS | DigitalOcean `manoj-projects`, Bangalore / BLR1, Ubuntu 24.04. |
| Starting capacity | 1 vCPU, 1 GB RAM, 25 GB disk, 2 GB swap; $6/month at provisioning, before taxes/domain fees. |
| HTTPS | Caddy certificate issuance/renewal and reverse proxy. |
| Application | Python 3.13 container, non-root UID 10001, one process, restart policy `unless-stopped`. |
| Application bind | `127.0.0.1:8765`; Compose uses Linux host networking. |
| State | Host bind mounts outside the source checkout/image. |
| Database/queue | None in the MVP: no PostgreSQL, TimescaleDB, Redis or RQ. |
| Backup | Nightly archives on the same VPS; off-server backups are not configured. |
| Website login | Not enabled by owner choice; optional Basic Auth is implemented. |
| Deployment | Manual Git pull and Docker rebuild; CI checks do not deploy. |

Inventory and provisioning price are dated observations, not capacity or price guarantees. Long history and repeated backtests can exceed the smallest VPS's RAM/disk. Monitor resources before expanding workloads.

The public site currently permits visitors to invoke research and paper actions. HTTPS and host/origin guards do not provide user authorization. Uvicorn is loopback-only behind Caddy; port 8765 is not opened publicly. Production trusts proxy headers only from loopback, and Caddy removes forwarded client IPs.

Local and production share code but have independent data, tokens, backtests and portfolios. There is no shared database or automatic data synchronization. A laptop need not remain running for production scheduling. A code update retains the external state directories.

## Deploy to a fresh Ubuntu server

These commands target a fresh **Ubuntu 24.04** VPS and run as root. Use the update procedure for the existing server. Save your SSH private key and provider account recovery information privately; never add them to the public repository.

### 1. Prepare SSH and DNS

Provision the VPS with your SSH public key and verify access:

```sh
ssh -i /path/to/your-private-key root@YOUR_SERVER_IP
```

Create a DNS-only A record for the project's hostname pointing to the server IP. If using another hostname, change both `deploy/Caddyfile` and `TRADER_PUBLIC_ORIGIN` in `compose.yaml` to the same HTTPS origin. Allow SSH and ports 80/443 in any provider firewall as well as the host firewall.

### 2. Install and clone

```sh
apt-get update
apt-get install -y docker.io docker-compose-v2 caddy rsync python3 git ufw
git clone https://github.com/manoj-mathivanan/trader_all.git /opt/trader
cd /opt/trader
bash deploy/bootstrap.sh
```

The bootstrap creates storage directories, sets UID/GID 10001 ownership, restricts private storage, creates 2 GB swap if `/swapfile` is absent and enables Docker/Caddy. It does not save credentials, ingest data or create portfolios. Host Python runs backup tooling; application Python comes from the Docker image.

The chart vendor bundle is included in the public repository. If it is missing in a reconstructed checkout, install Node 22 and run `npm ci && npm run vendor` before building the image.

### 3. Configure firewall and HTTPS

```sh
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable
cp deploy/Caddyfile /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy
```

Allow SSH before enabling UFW; adapt the rule if you changed the SSH port. Public DNS and inbound HTTP/HTTPS must work for certificate issuance. On a server already hosting other projects, **merge** the Trader site block into the Caddyfile rather than overwriting their sites. Assign each project its own loopback port and storage directories.

### 4. Build and start

```sh
cd /opt/trader
docker compose up -d --build
docker compose ps
docker compose logs --tail 100 trader
curl -fsS http://127.0.0.1:8765/api/bootstrap
curl -fsS https://trader.manojmathivanan.com/api/bootstrap
```

| Host mount | Container path | Purpose |
|---|---|---|
| `/srv/trader/data` | `/state/data` | Settings, universe, candles, jobs, backtests, frozen inputs, paper state and provider corrections. |
| `/srv/trader/private` | `/state/private` | Production-specific access token. |

Bootstrap should show `environment=production`, `paper_enabled=true` and, in the current unauthenticated setup, `auth_enabled=false`. Fresh installations have no saved token, loaded history, runs or paper portfolio.

### 5. Enable backup timer

```sh
cd /opt/trader
install -m 755 deploy/backup.sh /usr/local/sbin/trader-backup
cp deploy/trader-backup.service deploy/trader-backup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now trader-backup.timer
systemctl list-timers trader-backup.timer
```

### 6. Initialize production through the UI

Save the production token, select history/universe, refresh constituents and fetch missing data. Review job logs and coverage before creating a paper portfolio. Enable automatic cycles only if chosen; deployment does not allocate capital or enable portfolio scheduling automatically.

**Known provider correction:** Upstox supplied invalid negative IDEA volume for 2024-08-30. The NSE-verified exact-row recipe is documented in [architecture.md](architecture.md). Production has it installed. Fresh data directories do not receive it from Git: verify and recreate `provider_overrides/INE669E01016.json` in that environment if the provider still returns the same invalid row. Do not disable validation or apply a generic absolute-value repair.

## Server operation and code updates

### Inspect health and resource use

```sh
cd /opt/trader
docker compose ps
docker compose logs --tail 100 trader
systemctl status caddy --no-pager
journalctl -u caddy -n 50 --no-pager
df -h /
free -h
```

Use Jobs & logs for individual application failures; container and Caddy logs for startup/routing failures. `docker compose logs -f trader` follows live output. `docker compose stop trader` and `docker compose start trader` stop/start the existing container.

Restarting interrupts active jobs; startup marks them failed. Investigate and retry deliberately. Paper committed sessions are retained and uncommitted sessions can be replayed. Never run two application processes against the same state.

### Deploy a source update

Wait for active jobs to complete, then make a successful backup before pulling approved code:

```sh
systemctl start trader-backup.service
systemctl status trader-backup.service --no-pager
cd /opt/trader
git pull --ff-only origin main
docker compose up -d --build
docker compose ps
curl -fsS https://trader.manojmathivanan.com/api/bootstrap
```

Verify Settings, market coverage, charts, reports, mobile rendering and paper controls afterward. The bind-mounted data/private directories survive image rebuilds. Do not copy a local dataset over production as part of deployment.

The server pulls the public repository without a GitHub write credential and never commits/pushes runtime state. There is no automatic deployment from GitHub. A documentation-only update can be pulled without restarting the app.

For rollback, select a known good code commit and rebuild while retaining current data, after checking state/config compatibility. A code rollback is not a reason to replace a paper ledger with an older backup.

## Backups and restore

The timer runs at **20:00 UTC / 01:30 IST the following day**, randomized by up to two minutes, with persistent scheduling. This is separate from the portfolio's weekday cycle.

The script defers when a job is queued/running. It briefly stops Trader, exports non-secret JSON and restarts via an EXIT trap. Avoid initiating new jobs during this window: the pre-stop check is not an atomic admission lock. Retry a deferred backup manually after completion.

The exporter uses a filename manifest and SHA256-addressed compressed blobs; identical files share a blob within the snapshot. Each archive contains the complete manifest/blob set. This compresses backups, not live backtest snapshots.

- Archives: `/srv/trader/backups/data-<UTC timestamp>.tar.gz`.
- Staging: `/srv/trader/backup-state`.
- Cleanup removes matching archives older than seven days using mtime-day semantics.
- Private tokens are excluded; re-enter them on a replacement server.
- Backups remain on the same VPS. Server/disk loss can destroy both live data and backups. Download selected trusted archives to separate storage until an off-server destination is configured.

```sh
systemctl start trader-backup.service
journalctl -u trader-backup.service -n 50 --no-pager
systemctl list-timers trader-backup.timer
```

### Restore a trusted archive

Choose fresh empty staging/restore directories and a preservation destination that does not already exist. Ensure enough disk for current and restored data. Do not restore a ledger merely to troubleshoot a code deployment.

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

The restorer validates manifest version, path containment, JSON destinations and every checksum; a nonempty restore destination is rejected. Integrity checks do not establish authenticity of an untrusted archive. Retain old data until health, history, reports and portfolio accounting are verified. Private credentials are separate. Local research backups are independent of this timer.

## Configuration reference

`.env.example` documents the options. Python does **not** automatically read `.env`: set process variables explicitly or configure the process launcher. Compose already supplies production values.

| Variable | Default / purpose |
|---|---|
| `TRADER_ENV` | `local`; only `production` enables paper APIs/scheduler. Other values fail startup. |
| `TRADER_PUBLIC_ORIGIN` | Empty locally; production's exact HTTPS origin for host/origin checks. |
| `TRADER_DATA_DIR` | `<checkout>/data` locally; `/state/data` in the production container. |
| `TRADER_PRIVATE_DIR` | `<data>/private` locally; `/state/private` in production. |
| `DASHBOARD_ADMIN_USER`, `DASHBOARD_ADMIN_PASSWORD` | Optional Basic Auth; configure both or neither. Only one configured prevents startup. |
| `TRADER_KEY_FILE` | Legacy encrypted-token key path; default `<checkout>/.local-key`. New saves are plaintext. |

PowerShell example before starting a separate research installation:

```powershell
$env:TRADER_ENV = 'local'
$env:TRADER_DATA_DIR = 'C:/TraderResearch/data'
$env:TRADER_PRIVATE_DIR = 'C:/TraderResearch/private'
```

| Runtime file area | Meaning |
|---|---|
| Settings / saved screens | Installation-specific UI configuration. |
| Universe / bars | Real provider cache and requested coverage. |
| Jobs | Persistent job state/logs. |
| `runs/<run_id>.json` | Separate backtest report and configuration. |
| `run_data/<run_id>.json` | Full frozen candle inputs for the saved experiment. |
| `portfolios/<strategy_id>.json` | Paper ledger and durable session checkpoint. |
| `provider_overrides/<ISIN>.json` | Provenance-bearing verified exact-row repairs. |
| Private `upstox.json` | Token storage, excluded from Git and data backups. |

JSON writes flush before atomic replacement. This protects individual files from partial replacement; it is not a multi-process database. Preserve storage across restarts. On Windows, configure suitable private-directory ACLs; Unix mode settings alone do not define Windows access control.

## Troubleshooting

| Symptom | Explanation / next step |
|---|---|
| Token saved, pull fails | Replace an expired/invalid access token; inspect the provider job error and retry. |
| Universe refresh fails | Check NSE/Upstox access and matching logs. Ambiguous/unmatched constituents fail rather than being guessed. |
| 499/500 records, pull failed | Inspect the named failing symbol. One invalid provider dataset can fail the job while preserving the other valid files. |
| IDEA invalid candle, 2024-08-30 | Upstox returned volume `-81259413`; verified NSE volume is `4213707883`. Use only the architecture's exact-match repair. Production retry completed 500/500 on 4 October 2026. |
| Slow backtest popup initialization | Cold history checks read bar files; the popup displays loading immediately and unchanged-file metadata is cached afterward. |
| Run disabled on mobile | Read the status next to Run. Finish the active job or fix missing history/warmup; reopen after newly fetched data. |
| Dates exceed downloaded coverage | Use the available dates or fetch rolling market history. Production on 4 October had coverage ending 1 October, so the 4th exceeded coverage. |
| Loaded symbols excluded from backtest | Recent listings/shorter history can lack configured warmup; inspect report exclusions. |
| Paper view absent / API 403 locally | Expected local research mode. Production explicitly enables paper. |
| Automatic cycle failed | Fix the logged token/provider/data problem and retry manually. The scheduler attempts once per weekday. |
| Paper is enabled but shows no trades | Check the newest **Paper daily cycle** job and Last processed session. A successful cycle can have zero orders or zero new sessions. Older failed jobs remain visible; failed research history fetches/backtests do not mean the paper portfolio is disabled. Do not reset the portfolio to make trades appear. |
| Paper cycle rejects a history range over ten years | Fixed on 5 October 2026: internal paper ingestion preserves the original history start and allows the end to advance past the research form's ten-year limit. Deploy the `PaperIngestionRange` fix and retry; do not recreate the portfolio or shorten its history. |
| Paper cycle fails while fetching older MAZDOCK history | Fixed on 5 October 2026: paper refresh appends later sessions without re-fetching before loaded history. Upstox's older zero-price rows remain invalid and are never accepted. Research backfills still validate and may fail on those provider rows. |
| Processed-history change blocks paper | Investigate changed past candles; do not bypass fingerprints or rewrite accounting. |
| Loopback works, public HTTPS fails | Check DNS, Caddy logs/config, exact public origin, firewalls and certificate issuance. |
| Browser write rejected | Check host/origin configuration and use the UI, which sends the required request header. These checks are not a login. |
| Container cannot write state | Check bind mounts and UID/GID 10001 ownership; private directory mode 700 and token mode 600. |
| RAM/disk pressure | Inspect resources and frozen-input sizes; back up before deliberate pruning or resize the VPS. |
| Backup deferred | A job was queued/running. Wait for completion and retry the backup service. |

## Repository structure and GitHub policy

| Path | Responsibility |
|---|---|
| `dashboard/api/main.py` | API routes, host/origin checks, environment gating and lifecycle. |
| `dashboard/web/` | UI, charts and public vendor assets/licenses. |
| `core/research/` | Config, file storage, provider ingestion, jobs and backtests. |
| `core/portfolio/` | Persistent paper state, strategy dispatch and scheduling. |
| `core/risk/`, `core/execution/`, `strategies/` | Shared sizing, simulated execution and strategy logic. |
| `tests/` | Python and JavaScript regression checks. |
| `scripts/vendor.mjs` | Pinned frontend vendor regeneration. |
| `Dockerfile`, `compose.yaml` | Production image, environment and storage mounts. |
| `deploy/` | Caddy, bootstrap, backup/restore and systemd configuration. |
| `.github/workflows/checks.yml` | Main/PR checks; no deployment job. |
| `architecture.md` | Complete rebuild specification and research/deployment decisions. |

For Linux/macOS checks, use `npm run check`, `npm test` and `.venv/bin/python -m unittest discover -s tests -v`. Also run `git diff --check`. GitHub Actions uses Python 3.13 and Node 22 with locked dependencies. Inspect the actual workflow result; pushing a commit does not establish that CI passed.

Commit shared source, tests, dependency manifests/locks, public vendor assets/licenses, templates, deployment scripts and documentation. Review explicit paths before staging, especially while other threads modify this checkout:

```sh
git status --short
git diff -- path/to/changed-file
git add path/to/changed-file
git commit -m "Describe the reviewed change"
git push origin main
```

Use a branch/PR when review is appropriate. Author routine changes in a development checkout, not by automatically committing server state.

Do not commit `.env`, tokens, private keys, `.local-key`, `data/`, research artifacts, portfolios, backups or virtual environments. Backtests are separate files but stay ignored, so running UI experiments does not cause Git merge conflicts under this policy. Do not force-add runtime state. Application backup and Git source history serve different purposes.

Future plans include broader strategy plugins and database/queue infrastructure. The current application has no live broker execution, Telegram integration, shared local/remote database, external queue or off-server backup service. Working simulation and positive backtests do not by themselves establish a validated trading edge.

Further intraday strategy research and the 24-trial timeframe/selection comparison are in [MOMENTUM_DEEP_RESEARCH.md](MOMENTUM_DEEP_RESEARCH.md). Momentum now separates the opening range from completed 5/10/15/30/60-minute confirmation; execution and protective exits retain five-minute resolution.

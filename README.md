# Trader — research and paper workspace

Remote deployment is now authorized. See [deployment instructions](deploy/README.md) for the current server, HTTPS, public access, plaintext private token storage, independent local/production files and production backups and restore procedure. Earlier local-build notes below describe the original installation; the deployment amendment in architecture.md takes precedence.


A light cream-and-green control panel inspired by Banana Patterns. This first increment uses real Upstox daily data, not demo prices. It includes a configurable Nifty 50 / Nifty 500 universe, historical coverage, KLineChart candlesticks, persistent job logs and a parameterized daily breakout backtest. The backend registry already exposes Swing patterns as active and Intraday momentum / Scalping as planned plugins; the shared navigation reads this registry, while planned tabs remain visibly disabled until their data and execution modules are implemented.

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

## Research boundaries

- Swing backtests follow the Banana Patterns screen set: **VCP**, **Blue sky**, **Multi-year breakouts**, and **IPO base**. The same workflow exposes pivot/close entry, 3/5/8/10 position caps, 7/8/10% stops, 50-day or 30-week trailing exits (or +25%), risk per trade, and a 40%-above-200-day weak-market gate. Costs remain explicit assumptions; defaults are zero for reference-site comparison. Historical membership, RS ranking and broad liquid-universe coverage still need validation before claiming numeric parity.
- Next-open entries use completed previous-session signals (including paper). Backtests also retain Banana pivot/close entry assumptions: pivot fills require the entry-session high to reach the trigger; close fills use the signal close. Daily bars cannot order an entry-session low around a pivot fill, so pivot/close stops start next session. Stops gap at the open where applicable. Closing-price trailing updates activate next session. Slippage and percentage costs apply to both sides. Trade R uses initial price-stop risk; sizing also allows for modeled costs.
- One cash pool per run; no leverage. Simultaneous signals use alphabetical priority. Open-time exits may fund entries; intraday stop proceeds cannot fund earlier open-time buys.
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

Portfolio storage and APIs are scoped by strategy ID. Each strategy has exactly one portfolio at `data/portfolios/<strategy_id>.json`, with its own allocated capital, configuration, positions, cash, trades, equity and schedule checkpoint. The Paper trading strategy selector lists the implemented strategies; momentum/scalping stay disabled until their own execution plugin is registered in `core/portfolio/registry.py`. A new plugin provides its settings schema and cycle runner; the common UI renders its fields and the common scheduler dispatches its own jobs. No strategy can create a second portfolio or reset its existing one through the create action.

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
```

Tests use isolated synthetic unit fixtures and temporary directories only. No synthetic price data is shipped to the dashboard.

Reference APIs: [Upstox historical candles V3](https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/), [instrument master](https://upstox.com/developer/api-documentation/instruments/), [NSE Nifty 50 constituents](https://www.nseindia.com/static/products-services/indices-nifty50-index). KLineChart is vendored from npm with its Apache 2.0 license. No reference-site source code or assets are copied.

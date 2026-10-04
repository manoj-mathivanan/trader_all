# Trader MVP deployment

## Environment separation

The owner authorized remote research/paper hosting on 4 October 2026. Live broker execution remains deferred. Production starts fresh: local market history, backtests and credentials are not copied to the VPS. Each environment owns its data and private credentials; there is no database or automatic synchronization.

`TRADER_ENV=local` is the default. Local runs support market data and backtests, hide paper trading, reject paper API requests and never start the paper scheduler. `TRADER_ENV=production` explicitly enables paper APIs and the scheduler. Compose sets this for the VPS. A portfolio still must be created and configured in the production UI; no portfolio or automatic cycle is enabled merely by deploying.

## Runtime

DigitalOcean `manoj-projects`, Bangalore, Ubuntu 24.04, 1 vCPU / 1 GB RAM / 25 GB disk. Caddy terminates HTTPS for `trader.manojmathivanan.com`. Docker Compose runs one application process with the worker and production paper scheduler. Uvicorn binds only to `127.0.0.1:8765`; Caddy strips forwarded client IPs. Host and browser origin checks remain enabled. The website has no login by owner choice, so its research and paper actions are public. These checks are not authentication.

Install Docker, Compose, Caddy, Git and Python. Run `deploy/bootstrap.sh` and clone the public repository into `/opt/trader`. No GitHub credential or write deploy key is needed by the server. Copy `deploy/Caddyfile` to `/etc/caddy/Caddyfile` and reload Caddy. Cloudflare's DNS-only A record `trader` points to the VPS. The root domain remains reserved for future projects.

```sh
cd /opt/trader
docker compose up -d --build
```

## Files and credentials

- `/srv/trader/data`: production JSON research and paper state, owned by UID/GID 10001.
- `/srv/trader/private/upstox.json`: production plaintext UI-saved token, mode 600; directory mode 700. Enter a fresh token in the production Settings UI. It is excluded from Git, images and data backups.
- Local defaults remain `data/` and `data/private/` in the local checkout. Existing local histories remain intact; legacy encrypted token records are still readable with their original `.local-key`.
- GitHub `main` contains shared source, tests, dependencies, architecture and deployment configuration. No data branch, history, ledgers, backups, environment secrets or private keys are published. No server process commits or pushes to GitHub.
- Python does not load `.env` automatically. Supply process environment explicitly. Compose supplies production variables. Optional Basic Auth remains supported, but is not configured.

## Production backups

Install `deploy/backup.sh` as `/usr/local/sbin/trader-backup`, with the provided backup service/timer under `/etc/systemd/system`, and enable the timer. It runs around 01:30 IST, briefly stopping the container and restarting it with an EXIT trap. Active jobs defer the backup; run it manually after completion. The exporter checks JSON and rejects credentials, storing immutable content-addressed gzip blobs and a filename manifest. Identical candle snapshots share a blob; live application files retain their original format. Archives remain under `/srv/trader/backups` for seven days.

```sh
systemctl start trader-backup.service
systemctl status trader-backup.service
systemctl list-timers trader-backup.timer
```

Backups currently share the server's failure domain. They are not off-server disaster recovery. Provider backups were not purchased; download archives periodically until a separate backup destination is selected. Re-enter the Upstox token after a restore. Check `df -h` and `free -h` as datasets grow; large backtests may need a larger server.

## Updates and restore

Code updates leave live data directories intact. Back up before updating; fast-forward the public source branch and rebuild:

```sh
cd /opt/trader
git pull --ff-only origin main
docker compose up -d --build
```

For restore, extract the chosen archive into a temporary snapshot directory. Run `python3 deploy/data_snapshot.py restore /path/to/extracted-snapshot /srv/trader/restored-data`. The destination must be empty and every file's checksum is verified. Stop Trader, preserve current live data separately, move restored data into place, restore ownership to 10001, then restart. Never overwrite a current paper ledger simply because a code deployment failed.

Verify `/api/bootstrap`, Settings, charts, reports, production paper controls and mobile rendering after changes. Run exactly one server process without reload or multiple workers. Local research can run independently because local mode never schedules paper cycles.

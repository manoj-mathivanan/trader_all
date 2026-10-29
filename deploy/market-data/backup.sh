#!/bin/bash
set -euo pipefail
umask 077
exec 9>/run/market-data-backup.lock
flock -n 9 || exit 0
mountpoint -q /mnt/trader_data || { echo 'Database volume is not mounted.' >&2; exit 1; }
directory=/mnt/trader_data/backups/market-data
mkdir -p "$directory"
path="$directory/market-data-$(date -u +%Y%m%dT%H%M%SZ).dump"
server=market-data-postgres-1
server_memory=$(docker inspect -f '{{.HostConfig.Memory}}' "$server")
server_swap=$(docker inspect -f '{{.HostConfig.MemorySwap}}' "$server")
restore_limits() {
    result=$?
    # Remove an abandoned fragment even if restoring Docker limits fails.
    if [ -f "$path.partial" ]; then
        rm -f -- "$path.partial"
    fi
    docker update --memory "$server_memory" --memory-swap "$server_swap" "$server" > /dev/null
    exit "$result"
}
trap restore_limits EXIT
# PostgreSQL COPY hex-encodes large archived BYTEA values. Permit extra memory
# for this maintenance window, then restore the normal Compose limits.
docker update --memory 512m --memory-swap 768m "$server" > /dev/null
# A separate client keeps COPY's large BYTEA buffers out of the server's
# constrained memory budget. The password stays in a mounted root-only secret.
docker run --rm --log-driver none --network host --memory 256m --memory-swap 384m --cpus 0.5 \
    --mount type=bind,src=/srv/market-data/private/admin_password,dst=/run/secrets/admin_password,readonly \
    postgres:17-alpine sh -c \
    'export PGPASSWORD="$(cat /run/secrets/admin_password)"; exec pg_dump -h 127.0.0.1 -U market_admin -d market_data -Fc -Z 1' \
    > "$path.partial"
docker exec -i "$server" pg_restore --list < "$path.partial" > /dev/null
mv "$path.partial" "$path"
# Keep three daily dumps on this small VM; an external copy is still needed
# for disaster recovery. Never delete database files or original JSON inputs.
find "$directory" -maxdepth 1 -type f -name 'market-data-*.dump' -mtime +2 -delete

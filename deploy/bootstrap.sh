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

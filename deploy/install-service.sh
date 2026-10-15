#!/usr/bin/env bash
# Install/refresh the rail-table user service from the main checkout. No root.
#   bash deploy/install-service.sh
set -euo pipefail
cd "$(dirname "$0")/.."
~/.local/bin/uv sync --no-dev -q
install -D -m 644 deploy/rail-table.service ~/.config/systemd/user/rail-table.service
systemctl --user daemon-reload
systemctl --user enable -q rail-table
systemctl --user restart rail-table
sleep 2
systemctl --user is-active rail-table
curl -sS -o /dev/null -w 'local /api/stations -> %{http_code}\n' http://127.0.0.1:8787/api/stations

#!/usr/bin/env bash
#
# Publish rail-table at https://rail.geocube.work
#
# Run with:  sudo bash /home/dimi/workspace/rail-table/deploy/sudo-setup-rail-hosting.sh
#
# Idempotent. Both config files are backed up before anything is touched.
#
#   1. adds a Caddy vhost on the shared loopback port 8080 that reverse-proxies
#      to the rail-table app (systemd user service on 127.0.0.1:8787)
#   2. adds a cloudflared ingress rule above the 404 catch-all
#   3. restarts both services and verifies
#
# Public, no basic auth (for now) — it's a phone home-screen app, and a
# password prompt there is clumsy. The app holds no personal data.
#
# The DNS record is created separately, as dimi, with:
#   cloudflared tunnel route dns infinity rail.geocube.work

set -euo pipefail

HOSTNAME_="rail.geocube.work"
PORT="8080"                       # shared with the other sites; Caddy routes on Host
APP="127.0.0.1:8787"
TS="$(date -u +%Y%m%dT%H%M%SZ)"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "This script must run as root: sudo bash $0" >&2
  exit 1
fi

echo "==> 1/3  Caddy vhost"
cp -a /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.bak-$TS"
if grep -q "$HOSTNAME_" /etc/caddy/Caddyfile; then
  echo "    already present, leaving as is"
else
  cat >> /etc/caddy/Caddyfile <<EOC

# rail-table — next trains to/from Orpington. FastAPI app (systemd user unit
# rail-table.service) on $APP serves both the API and the page.
# Loopback-only on the shared $PORT, explicit http:// (TLS ends at Cloudflare).
# Deliberately public: no auth import.
http://$HOSTNAME_:$PORT {
	bind 127.0.0.1 ::1
	encode gzip zstd
	reverse_proxy $APP
}
EOC
  echo "    appended (backup: /etc/caddy/Caddyfile.bak-$TS)"
fi
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1
echo "    Caddyfile validates"

echo "==> 2/3  cloudflared ingress rule"
cp -a /etc/cloudflared/config.yml "/etc/cloudflared/config.yml.bak-$TS"
if grep -q "$HOSTNAME_" /etc/cloudflared/config.yml; then
  echo "    already present, leaving as is"
else
  python3 - "$HOSTNAME_" "$PORT" <<'PY'
import sys
host, port = sys.argv[1], sys.argv[2]
path = "/etc/cloudflared/config.yml"
catchall = "  - service: http_status:404"
text = open(path).read()
if catchall not in text:
    sys.exit("catch-all rule not found in %s - refusing to edit blindly" % path)
rule = "  - hostname: %s\n    service: http://localhost:%s\n" % (host, port)
# must land before the catch-all: cloudflared takes the first matching rule
open(path, "w").write(text.replace(catchall, rule + catchall, 1))
PY
  echo "    inserted before the catch-all (backup: /etc/cloudflared/config.yml.bak-$TS)"
fi

echo "==> 3/3  Restarting services"
# restart, not reload: the Caddyfile sets `admin off`, so `caddy reload` cannot
# reach the admin API.
systemctl restart caddy
systemctl restart cloudflared
sleep 3
systemctl is-active caddy cloudflared

echo
echo "==> Verifying"
printf '    local  /api/stations          -> '
curl -sS -o /dev/null -w '%{http_code}  (200 expected)\n' -H "Host: $HOSTNAME_" "http://127.0.0.1:$PORT/api/stations"
printf '    public /                      -> '
curl -sS -o /dev/null -w '%{http_code}  (200 expected)\n' "https://$HOSTNAME_/"
printf '    trains.geocube.work still up  -> '
curl -sS -o /dev/null -w '%{http_code}  (401 expected, unchanged)\n' "https://trains.geocube.work/"
echo
echo "Done — https://$HOSTNAME_"

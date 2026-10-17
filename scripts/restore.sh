#!/usr/bin/env bash
# ==================================================================================
# Restore a backup made by backup.sh.
#   scripts/restore.sh backups/bess-backup_20261017_023000.tar.gz [--with-config] [--yes]
# Steps: verify checksums -> stop gateway (no writes during restore) -> restore historian
# -> restore HMI db -> (optionally) restore configuration -> restart -> health check.
# ==================================================================================
set -euo pipefail
cd "$(dirname "$0")/.."
ARCHIVE="${1:?usage: restore.sh <archive.tar.gz> [--with-config] [--yes]}"
shift
WITH_CONFIG=0; YES=0
for a in "$@"; do case "$a" in --with-config) WITH_CONFIG=1 ;; --yes) YES=1 ;; esac; done
COMPOSE_FILE="${BESS_COMPOSE:-docker-compose.yml}"
dc() { docker compose -f "$COMPOSE_FILE" "$@"; }
log() { echo "[restore] $*"; }
WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT

# 1. integrity
if [ -f "$ARCHIVE.sha256" ]; then
  (cd "$(dirname "$ARCHIVE")" && sha256sum -c "$(basename "$ARCHIVE").sha256" >/dev/null) || { echo "archive checksum FAILED"; exit 1; }
fi
tar -xzf "$ARCHIVE" -C "$WORK"
(cd "$WORK" && sha256sum -c --quiet MANIFEST.sha256) || { echo "manifest verification FAILED"; exit 1; }
log "archive verified"; sed 's/^/          /' "$WORK/METADATA.txt"

if [ "$YES" -ne 1 ]; then
  read -r -p "This REPLACES historian data and HMI settings. Continue? [type yes] " ans
  [ "$ans" = "yes" ] || { echo "aborted"; exit 1; }
fi

# 2. configuration first (it may contain the admin token the backup was taken with)
if [ "$WITH_CONFIG" -eq 1 ]; then
  tar -xf "$WORK/config.tar"
  log "configuration restored (incl. .env)"
fi
# shellcheck disable=SC1091
set -a; . ./.env; set +a

# 3. quiesce writers
dc stop gateway
log "gateway stopped"

# 4. historian
CID=$(dc ps -q influxdb)
docker cp "$WORK/influxdb" "$CID:/tmp/restore"
dc exec -T influxdb influx restore /tmp/restore --full -t "$INFLUX_ADMIN_TOKEN"
dc exec -T influxdb rm -rf /tmp/restore
log "historian restored"

# 5. HMI
dc stop grafana
GCID=$(dc ps -a -q grafana)
docker cp "$WORK/grafana.db" "$GCID:/var/lib/grafana/grafana.db"
log "HMI database restored"

# 6. restart and verify
dc up -d
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:3000/api/health >/dev/null 2>&1; then log "HMI healthy"; break; fi
  sleep 2
done
log "done - run 'make fat' to re-verify the system (SAT step SAT-BR-02)"

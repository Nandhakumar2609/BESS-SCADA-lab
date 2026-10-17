#!/usr/bin/env bash
# ==================================================================================
# Backup: historian (InfluxDB native backup), HMI database, configuration + secrets,
# configuration baseline. Produces one archive with a SHA-256 manifest.
#   scripts/backup.sh                    -> ./backups/bess-backup_<timestamp>.tar.gz
#   BACKUP_DIR=/var/backups/bess-lab RETENTION_DAYS=14 scripts/backup.sh
# ==================================================================================
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)
COMPOSE_FILE="${BESS_COMPOSE:-docker-compose.yml}"
BACKUP_DIR="${BACKUP_DIR:-$ROOT/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
TS=$(date +%Y%m%d_%H%M%S)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
dc() { docker compose -f "$COMPOSE_FILE" "$@"; }
log() { echo "[backup] $*"; }

[ -f .env ] || { echo ".env missing - nothing to back up"; exit 1; }
# shellcheck disable=SC1091
set -a; . ./.env; set +a
mkdir -p "$BACKUP_DIR" "$WORK/bundle"
chmod 0700 "$BACKUP_DIR"

# 1. historian: online, consistent backup through the InfluxDB API
INFLUX_CID=$(dc ps -q influxdb)
[ -n "$INFLUX_CID" ] || { echo "influxdb container not running"; exit 1; }
dc exec -T influxdb influx backup "/tmp/bk_$TS" -t "$INFLUX_ADMIN_TOKEN" >/dev/null
docker cp "$INFLUX_CID:/tmp/bk_$TS" "$WORK/bundle/influxdb"
dc exec -T influxdb rm -rf "/tmp/bk_$TS"
log "historian backed up ($(du -sh "$WORK/bundle/influxdb" | cut -f1))"

# 2. HMI: users, preferences, annotations (dashboards themselves are code in git)
GRAFANA_CID=$(dc ps -q grafana)
docker cp "$GRAFANA_CID:/var/lib/grafana/grafana.db" "$WORK/bundle/grafana.db"
log "HMI database backed up"

# 3. configuration and secrets
tar -cf "$WORK/bundle/config.tar" --exclude='__pycache__' \
    config network grafana docker docker-compose*.yml .env ansible/group_vars \
    $( [ -d baselines/current ] && echo baselines/current )
if [ -r /etc/bess-lab ]; then tar -cf "$WORK/bundle/etc-bess-lab.tar" -C / etc/bess-lab; fi
log "configuration backed up"

# 4. metadata + manifest
{
  echo "created: $(date -Is)"
  echo "host: $(hostname)"
  echo "compose: $COMPOSE_FILE"
  echo "git: $(git rev-parse --short HEAD 2>/dev/null || echo n/a)"
  echo "images:"
  for c in $(dc ps -q); do docker inspect --format '  {{.Name}} {{.Config.Image}} {{.Image}}' "$c"; done
} > "$WORK/bundle/METADATA.txt"
( cd "$WORK/bundle" && find . -type f ! -name MANIFEST.sha256 -print0 | sort -z | xargs -0 sha256sum > MANIFEST.sha256 )

ARCHIVE="$BACKUP_DIR/bess-backup_$TS.tar.gz"
tar -czf "$ARCHIVE" -C "$WORK/bundle" .
chmod 0600 "$ARCHIVE"
sha256sum "$ARCHIVE" > "$ARCHIVE.sha256"
log "archive: $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"

# 5. retention
find "$BACKUP_DIR" -name 'bess-backup_*.tar.gz*' -mtime +"$RETENTION_DAYS" -print -delete | sed 's/^/[backup] expired: /'
log "done"

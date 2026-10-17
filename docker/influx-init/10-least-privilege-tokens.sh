#!/bin/bash
# Runs once, on the first start of an empty InfluxDB (official image init hook).
# Creates least-privilege API tokens instead of handing the admin token to every client:
#   gateway.token  write-only on bucket "bess"  (SCADA gateway)
#   grafana.token  read-only  on bucket "bess"  (HMI dashboards, FAT historian checks)
set -euo pipefail

ORG="${DOCKER_INFLUXDB_INIT_ORG}"
BUCKET="${DOCKER_INFLUXDB_INIT_BUCKET}"
OUT=/secrets

bucket_id=$(influx bucket list --org "$ORG" --name "$BUCKET" --hide-headers | awk '{print $1}')

make_token() {   # $1 = file name, $2.. = permission flags
  local name="$1"; shift
  local json token
  json=$(influx auth create --org "$ORG" --description "bess-lab-${name%.token}" "$@" --json)
  token=$(echo "$json" | sed -n 's/.*"token": *"\([^"]*\)".*/\1/p' | head -n1)
  if [ -z "$token" ]; then
    echo "[influx-init] ERROR: could not create $name" >&2
    return 1
  fi
  umask 022
  printf '%s' "$token" > "$OUT/$name"
  chmod 0644 "$OUT/$name"
  echo "[influx-init] created $name"
}

fallback() {     # never leave the stack unable to start; flag it loudly instead
  echo "[influx-init] WARNING: falling back to the ADMIN token for $1 - fix before production" >&2
  printf '%s' "$DOCKER_INFLUXDB_INIT_ADMIN_TOKEN" > "$OUT/$1"; chmod 0644 "$OUT/$1"
}

make_token gateway.token --write-bucket "$bucket_id" || fallback gateway.token
make_token grafana.token --read-bucket "$bucket_id"  || fallback grafana.token

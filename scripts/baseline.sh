#!/usr/bin/env bash
# ==================================================================================
# Configuration baseline (IEC 62443-3-3 SR 7.6 / CM practice).
#   scripts/baseline.sh capture   record the approved configuration -> baselines/<ts>, baselines/current
#   scripts/baseline.sh check     compare the running system with baselines/current (exit 1 on drift)
# Captures: hashes of all configuration files, the LIVE firewall ruleset (stateless),
# running image digests, published ports, Python package versions, WireGuard peers.
# ==================================================================================
set -euo pipefail
cd "$(dirname "$0")/.."
COMPOSE_FILE="${BESS_COMPOSE:-docker-compose.yml}"
dc() { docker compose -f "$COMPOSE_FILE" "$@"; }

collect() {   # $1 = output directory
  local out=$1; mkdir -p "$out"
  find config network/nftables grafana docker docker-compose*.yml ansible/group_vars -type f \
       ! -name '*.pyc' -print0 2>/dev/null | sort -z | xargs -0 sha256sum > "$out/files.sha256"
  if dc ps --services --status running 2>/dev/null | grep -qx fw; then
    dc exec -T fw nft -s list ruleset > "$out/firewall-live.nft"          # -s: no counters
    dc exec -T fw sh -c 'wg show wg0 peers 2>/dev/null || true' > "$out/wireguard-peers.txt"
  fi
  for c in $(dc ps -q 2>/dev/null); do
    docker inspect --format '{{.Name}} {{.Config.Image}} {{.Image}}' "$c"
  done | sort > "$out/images.txt"
  dc ps --format '{{.Service}} {{.Publishers}}' 2>/dev/null | sort > "$out/published-ports.txt" || true
  if dc ps --services --status running 2>/dev/null | grep -qx gateway; then
    dc exec -T gateway pip freeze 2>/dev/null | sort > "$out/python-packages.txt" || true
  fi
  { echo "# informational, not compared"; date -Is; hostname; git rev-parse HEAD 2>/dev/null || true; } > "$out/INFO"
}

case "${1:-}" in
  capture)
    ts=$(date +%Y%m%d_%H%M%S)
    collect "baselines/$ts"
    ln -sfn "$ts" baselines/current
    echo "[baseline] captured baselines/$ts ($(wc -l < "baselines/$ts/files.sha256") files) -> baselines/current"
    ;;
  check)
    [ -e baselines/current ] || { echo "[baseline] no baseline yet - run: scripts/baseline.sh capture"; exit 2; }
    tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
    collect "$tmp"
    if diff -ru --exclude=INFO baselines/current/ "$tmp/" > "$tmp.diff"; then
      echo "[baseline] OK - running configuration matches baseline $(readlink baselines/current)"
    else
      echo "[baseline] DRIFT DETECTED against $(readlink baselines/current):"
      sed 's/^/    /' "$tmp.diff"
      logger -t bess-baseline "configuration drift detected" 2>/dev/null || true
      exit 1
    fi
    ;;
  *) echo "usage: $0 capture|check"; exit 2 ;;
esac

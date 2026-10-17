#!/usr/bin/env bash
# ==================================================================================
# Bare-Linux network lab: the same zones, firewall policy and applications as the Docker
# stack, built from network namespaces + veth pairs. No Docker needed - just root,
# iproute2, nftables and python3 (with requirements.txt installed).
#
#   sudo lab/netns-lab.sh up      build namespaces, load fw.nft, start sim/gateway/mocks
#   sudo lab/netns-lab.sh test    run the conduit / deny / NAT / anti-spoofing tests
#   sudo lab/netns-lab.sh down    remove everything
#   sudo lab/netns-lab.sh all     up + test + down (used in CI)
#
#        [wan ns]                       [fw ns]                       [field ns]
#   172.30.0.1 ---- wan:172.30.0.254   nftables   vlan10:10.10.10.254 ---- 10.10.10.10-.14 simulator
#                                       |      |
#                    vlan20:10.10.20.254        vlan30:10.10.30.254
#                           |                           |
#                    [ctrl ns] 10.10.20.10        [dmz ns] 10.10.30.10 historian (mock)
#                      SCADA gateway                       10.10.30.11 HMI (mock)
# ==================================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN=/run/bess-lab
NS="fw field ctrl dmz wan"
PY="${PYTHON:-python3}"
TOKEN=labtoken

nsx() { local n=$1; shift; ip netns exec "bess-$n" "$@"; }

link() {  # link <ns> <ifname-in-ns> <ip/cidr> <fw-ifname> <fw-ip/cidr>
  ip link add "$2-$1" type veth peer name "$4"
  ip link set "$2-$1" netns "bess-$1"; ip link set "$4" netns bess-fw
  nsx "$1" ip link set "$2-$1" name "$2"
  nsx "$1" ip addr add "$3" dev "$2"; nsx "$1" ip link set "$2" up
  nsx fw ip addr add "$5" dev "$4";   nsx fw ip link set "$4" up
}

up() {
  mkdir -p "$RUN"
  for n in $NS; do ip netns add "bess-$n"; nsx "$n" ip link set lo up; done
  nsx fw sysctl -qw net.ipv4.ip_forward=1
  link field eth0 10.10.10.10/24 vlan10 10.10.10.254/24
  link ctrl  eth0 10.10.20.10/24 vlan20 10.10.20.254/24
  link dmz   eth0 10.10.30.10/24 vlan30 10.10.30.254/24
  link wan   eth0 172.30.0.1/24  wan    172.30.0.254/24
  for a in 11 12 13 14; do nsx field ip addr add 10.10.10.$a/24 dev eth0; done
  nsx dmz ip addr add 10.10.30.11/24 dev eth0
  nsx field ip route add default via 10.10.10.254
  nsx ctrl  ip route add default via 10.10.20.254
  nsx wan   ip route add default via 172.30.0.254
  # NOTE: the dmz namespace gets NO default route on purpose - zone SNAT means it never needs one
  nsx fw nft -f "$ROOT/network/nftables/fw.nft"
  echo "[lab] namespaces + firewall up"

  cd "$ROOT"
  nsx dmz $PY lab/mock_influx.py --bind 10.10.30.10 --port 8086 --token "$TOKEN" > "$RUN/influx.log" 2>&1 & echo $! > "$RUN/influx.pid"
  nsx dmz $PY -m http.server --bind 10.10.30.11 3000 --directory "$ROOT/docs" > "$RUN/hmi.log" 2>&1 & echo $! > "$RUN/hmi.pid"
  nsx field env BESS_CONFIG_DIR="$ROOT/config" $PY -m bess_lab.sim.server --speed 20 > "$RUN/sim.log" 2>&1 & echo $! > "$RUN/sim.pid"
  sleep 2
  nsx ctrl env INFLUX_TOKEN="$TOKEN" BESS_CONFIG_DIR="$ROOT/config" $PY -m bess_lab.gateway.main > "$RUN/gateway.log" 2>&1 & echo $! > "$RUN/gateway.pid"
  if command -v tcpdump >/dev/null; then
    nsx fw tcpdump -i nflog:1 -nn -l > "$RUN/drops.log" 2>/dev/null & echo $! > "$RUN/tcpdump.pid"
  fi
  echo "[lab] simulator, gateway, historian and HMI mocks started (logs in $RUN)"
}

down() {
  for f in "$RUN"/*.pid; do [ -e "$f" ] && kill "$(cat "$f")" 2>/dev/null || true; done
  for n in $NS; do ip netns del "bess-$n" 2>/dev/null || true; done
  rm -rf "$RUN"
  echo "[lab] removed"
}

PASS=0; FAIL=0
expect() {  # expect <description> <expected> <actual>
  if [ "$2" = "$3" ]; then PASS=$((PASS+1)); printf '  PASS  %-62s %s\n' "$1" "$3"
  else FAIL=$((FAIL+1)); printf '  FAIL  %-62s expected %s got %s\n' "$1" "$2" "$3"; fi
}
probe() { local n=$1; shift; nsx "$n" $PY "$ROOT/lab/probe.py" "$@"; }

test_lab() {
  echo "[lab] waiting for the gateway to complete a few scans..."
  sleep 8
  echo "Conduits that must be OPEN"
  expect "C1 gateway -> PCS 10.10.10.11:502 (Modbus)"          OPEN     "$(probe ctrl 10.10.10.11 502)"
  expect "C1 gateway -> meters 10.10.10.14:502 (Modbus)"       OPEN     "$(probe ctrl 10.10.10.14 502)"
  expect "C2 gateway -> historian 10.10.30.10:8086"            OPEN     "$(probe ctrl 10.10.30.10 8086)"
  expect "C3 wan -> fw:3000 DNAT -> HMI"                       OPEN     "$(probe wan 172.30.0.254 3000)"
  echo "Everything else must be FILTERED (dropped)"
  expect "gateway -> PCS 10.10.10.11:22 (not Modbus)"          FILTERED "$(probe ctrl 10.10.10.11 22)"
  expect "gateway -> unknown field host 10.10.10.50:502"       FILTERED "$(probe ctrl 10.10.10.50 502)"
  expect "gateway -> HMI 10.10.30.11:3000 (not a conduit)"     FILTERED "$(probe ctrl 10.10.30.11 3000)"
  expect "field -> gateway 10.10.20.10:22 (upward)"            FILTERED "$(probe field 10.10.20.10 22)"
  expect "field -> historian 10.10.30.10:8086 (upward)"        FILTERED "$(probe field 10.10.30.10 8086)"
  expect "wan -> PCS 10.10.10.11:502"                          FILTERED "$(probe wan 10.10.10.11 502)"
  expect "wan -> historian 10.10.30.10:8086"                   FILTERED "$(probe wan 10.10.30.10 8086)"
  expect "wan -> gateway 10.10.20.10:22"                       FILTERED "$(probe wan 10.10.20.10 22)"
  expect "wan -> firewall SSH 172.30.0.254:22"                 FILTERED "$(probe wan 172.30.0.254 22)"
  echo "DMZ cannot reach OT (and has no route at all - SNAT design)"
  expect "historian -> PCS 10.10.10.11:502"                    "UNREACHABLE (Network is unreachable)" "$(probe dmz 10.10.10.11 502)"

  echo "Anti-spoofing (reverse-path filter)"
  nsx ctrl ip addr add 10.10.10.99/32 dev eth0
  expect "spoofed field source from control zone"              FILTERED "$(probe ctrl 10.10.30.10 8086 --src 10.10.10.99)"
  nsx ctrl ip addr del 10.10.10.99/32 dev eth0
  spoof=$(nsx fw nft list chain inet bess_fw prerouting_filter | sed -n 's/.*counter packets \([0-9]*\).*/\1/p' | head -n1)
  expect "FW-SPOOF counter incremented"                         yes "$([ "${spoof:-0}" -gt 0 ] && echo yes || echo no)"

  echo "End-to-end data path through the firewall"
  stats=$(nsx dmz $PY -c "import urllib.request;print(urllib.request.urlopen('http://10.10.30.10:8086/stats').read().decode())")
  tel=$(echo "$stats" | $PY -c "import sys,json;print(json.load(sys.stdin)['lines'].get('telemetry',0))")
  clients=$(echo "$stats" | $PY -c "import sys,json;print(','.join(json.load(sys.stdin)['clients']))")
  expect "historian received telemetry from gateway"           yes "$([ "$tel" -gt 0 ] && echo yes || echo no)"
  expect "historian sees firewall SNAT address only"           10.10.30.254 "$clients"
  ok=$(grep -c "pcs01=OK bms01=OK hvac01=OK meter_poi=OK meter_aux=OK" "$RUN/gateway.log" || true)
  expect "gateway polls all 5 devices through conduit C1"      yes "$([ "$ok" -gt 0 ] && echo yes || echo no)"
  drops=$(nsx fw nft list chain inet bess_fw forward | grep -E 'counter packets [0-9]+ bytes [0-9]+ drop' | sed -n 's/.*counter packets \([0-9]*\).*/\1/p' | tail -n1)
  expect "denied flows counted by the default-drop rule"        yes "$([ "${drops:-0}" -gt 0 ] && echo yes || echo no)"
  if [ -s "$RUN/drops.log" ]; then echo "  info  NFLOG drop log: $(wc -l < "$RUN/drops.log") packets captured (sample below)"; head -n 3 "$RUN/drops.log" | sed 's/^/        /'; fi

  echo; echo "Result: $PASS passed, $FAIL failed"
  [ "$FAIL" -eq 0 ]
}

[ "$(id -u)" -eq 0 ] || { echo "run as root (sudo)"; exit 1; }
case "${1:-}" in
  up) up ;;
  down) down ;;
  test) test_lab ;;
  all) down >/dev/null 2>&1 || true; up; rc=0; test_lab || rc=$?; down; exit $rc ;;
  *) echo "usage: $0 up|test|down|all"; exit 2 ;;
esac

#!/bin/bash
# Firewall container init:
#  1. rename interfaces after their zone (Docker names them eth0..ethN in no guaranteed order)
#  2. load the nftables policy (default drop)
#  3. bring up WireGuard if a config is mounted
#  4. log dropped packets (NFLOG group 1) to /var/log/fw/drops.log
set -euo pipefail

# "ip=zone-name" pairs, set in docker-compose.yml
FW_IFMAP="${FW_IFMAP:-10.10.10.254=vlan10 10.10.20.254=vlan20 10.10.30.254=vlan30 172.30.0.254=wan}"
WAN_GW="${WAN_GW:-172.30.0.1}"
NFT_FILE="${NFT_FILE:-/etc/nftables/fw.nft}"
WG_CONF="${WG_CONF:-/etc/wireguard/wg0.conf}"

log() { echo "[fw-init] $*"; }

# --- 1. interface naming -------------------------------------------------------
for pair in $FW_IFMAP; do
  ip_addr="${pair%%=*}"; name="${pair##*=}"
  dev=$(ip -4 -o addr show | awk -v a="$ip_addr" '{split($4,x,"/"); if (x[1]==a) print $2}' | head -n1)
  dev="${dev%%@*}"
  if [ -z "$dev" ]; then log "WARNING: no interface has $ip_addr"; continue; fi
  if [ "$dev" != "$name" ]; then
    ip link set dev "$dev" down
    ip link set dev "$dev" name "$name"
    ip link set dev "$name" up
    log "renamed $dev -> $name ($ip_addr)"
  fi
done
ip route replace default via "$WAN_GW" dev wan 2>/dev/null || log "WARNING: no default route via $WAN_GW"

# --- 2. routing + firewall -------------------------------------------------------
sysctl -qw net.ipv4.ip_forward=1 || true          # also set by compose "sysctls"
nft -c -f "$NFT_FILE"                              # syntax check first: never load a broken policy
nft -f "$NFT_FILE"
log "nftables policy loaded from $NFT_FILE ($(nft list ruleset | grep -c 'accept\|drop') rules)"

# --- 3. WireGuard -----------------------------------------------------------------
if [ -s "$WG_CONF" ]; then
  if ip link add wg0 type wireguard 2>/dev/null; then
    wg setconf wg0 <(wg-quick strip "$WG_CONF")
    addr=$(awk -F' *= *' 'tolower($1)=="address"{print $2}' "$WG_CONF")
    ip addr add "$addr" dev wg0
    ip link set wg0 up
    log "WireGuard wg0 up ($addr), $(wg show wg0 peers | wc -l) peer(s)"
  else
    log "WARNING: kernel has no WireGuard support - VPN disabled, rest of the lab unaffected"
  fi
else
  log "no $WG_CONF - VPN disabled (run scripts/wg-genkeys.sh or the Ansible wireguard role)"
fi

# --- 4. drop logging --------------------------------------------------------------
( tcpdump -i nflog:1 -nn -l -tttt 2>/dev/null >> /var/log/fw/drops.log || log "nflog capture unavailable" ) &

log "ready. interfaces: $(ip -br -4 addr | awk '{print $1"="$3}' | tr '\n' ' ')"
trap 'log "stopping"; exit 0' TERM INT
while sleep 3600 & wait $!; do :; done

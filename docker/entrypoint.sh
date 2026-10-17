#!/bin/sh
# Container network setup, then drop root.
#   NET_ALIASES  extra IPs on eth0, e.g. "10.10.10.11/24 10.10.10.12/24" (one simulator = several devices)
#   NET_ROUTES   ";"-separated routes, e.g. "default via 10.10.20.254"
#   RUN_AS       user to run the application as (default: bess). Needs CAP_SETUID/SETGID.
set -eu

IFACE="${NET_IFACE:-eth0}"

if [ -n "${NET_ALIASES:-}" ]; then
  for a in $NET_ALIASES; do
    ip addr replace "$a" dev "$IFACE" && echo "[entrypoint] alias $a on $IFACE"
  done
fi

if [ -n "${NET_ROUTES:-}" ]; then
  echo "$NET_ROUTES" | tr ';' '\n' | while read -r r; do
    [ -z "$r" ] && continue
    # shellcheck disable=SC2086
    ip route replace $r && echo "[entrypoint] route $r"
  done
fi

echo "[entrypoint] addresses: $(ip -4 -o addr show | awk '{print $2"="$4}' | tr '\n' ' ')"

if [ "$(id -u)" = "0" ] && [ "${RUN_AS:-bess}" != "root" ]; then
  exec setpriv --reuid="${RUN_AS:-bess}" --regid="${RUN_AS:-bess}" --init-groups --inh-caps=-all \
       --bounding-set=-all "$@"
fi
exec "$@"

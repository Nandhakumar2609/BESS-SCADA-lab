#!/usr/bin/env bash
# ==================================================================================
# WireGuard keys + configs without Ansible (the Ansible "wireguard" role does the same).
#   scripts/wg-genkeys.sh <public-ip-or-dns-of-this-host>
# Writes network/wireguard/wg0.conf (mounted into the fw container) and
# network/wireguard/clients/{engineer,viewer}.conf for the laptops. All files 0600, git-ignored.
# ==================================================================================
set -euo pipefail
cd "$(dirname "$0")/.."
ENDPOINT="${1:?usage: wg-genkeys.sh <public ip or hostname of the docker host>}"
D=network/wireguard; K=$D/keys
command -v wg >/dev/null || { echo "install wireguard-tools first"; exit 1; }
umask 077; mkdir -p "$K" "$D/clients"

for n in fw engineer viewer; do
  [ -s "$K/$n.key" ] || { wg genkey > "$K/$n.key"; wg pubkey < "$K/$n.key" > "$K/$n.pub"; wg genpsk > "$K/$n.psk"; }
done
k() { cat "$K/$1.$2"; }

mkdir -p "$D/server"
cat > "$D/server/wg0.conf" <<EOF
[Interface]
Address = 10.99.0.1/24
ListenPort = 51820
PrivateKey = $(k fw key)

# engineer: HMI + historian API + SSH to the control zone
[Peer]
PublicKey = $(k engineer pub)
PresharedKey = $(k engineer psk)
AllowedIPs = 10.99.0.10/32

# viewer: HMI only
[Peer]
PublicKey = $(k viewer pub)
PresharedKey = $(k viewer psk)
AllowedIPs = 10.99.0.20/32
EOF

client() {  # name ip allowed
  cat > "$D/clients/$1.conf" <<EOF
[Interface]
Address = $2/32
PrivateKey = $(k "$1" key)

[Peer]
PublicKey = $(k fw pub)
PresharedKey = $(k "$1" psk)
Endpoint = $ENDPOINT:51820
AllowedIPs = $3
PersistentKeepalive = 25
EOF
}
client engineer 10.99.0.10 "10.10.30.11/32, 10.10.30.10/32, 10.10.20.0/24, 10.99.0.1/32"
client viewer   10.99.0.20 "10.10.30.11/32"

echo "server config: $D/server/wg0.conf  (restart the firewall: docker compose restart fw)"
echo "client configs: $D/clients/engineer.conf, $D/clients/viewer.conf"
echo "on the engineer laptop, the HMI is then at http://10.10.30.11:3000"

# IP plan and VLAN design

Source of truth: `ansible/group_vars/all.yml` (the firewall policy is rendered from it).

## VLANs / zones

| VLAN | Zone | Purdue level | Subnet | Gateway (fw) | Docker bridge | Trust |
|---|---|---|---|---|---|---|
| 10 | Field | 0-1 | 10.10.10.0/24 | 10.10.10.254 | br-vlan10 | low (unauthenticated Modbus) |
| 20 | Control | 2 | 10.10.20.0/24 | 10.10.20.254 | br-vlan20 | high |
| 30 | OT DMZ | 3.5 | 10.10.30.0/24 | 10.10.30.254 | br-vlan30 | medium |
| 99 | Uplink / WAN | 4-5 | 172.30.0.0/24 | 172.30.0.254 | br-wan | untrusted |
| - | VPN (wg0) | remote | 10.99.0.0/24 | 10.99.0.1 | - | per-peer role |

`.1` in each Docker subnet belongs to the Docker host bridge and is **not** used as a gateway; masquerading
is disabled on the OT bridges, so the zones have no path to the internet. Dynamic addresses (if any
container ever gets one) come from `.192/27` so they can never collide with the static plan.

## Address assignments

| Host | IP | Zone | Ports (listening) | Notes |
|---|---|---|---|---|
| fw | 10.10.10.254 / .20.254 / .30.254 / 172.30.0.254 / 10.99.0.1 | all | 51820/udp (wan) | routing, nftables, NAT, WireGuard |
| field-sim (primary) | 10.10.10.10 | field | - | hosts the device aliases below |
| PCS | 10.10.10.11 | field | 502/tcp | unit ID 1 |
| BMS | 10.10.10.12 | field | 502/tcp | unit ID 1 |
| HVAC | 10.10.10.13 | field | 502/tcp | unit ID 1 |
| Meters (POI, AUX) | 10.10.10.14 | field | 502/tcp | unit ID 1 = POI, 2 = AUX (serial gateway style) |
| SCADA gateway | 10.10.20.10 | control | - | client only, initiates all OT traffic |
| Historian (InfluxDB) | 10.10.30.10 | DMZ | 8086/tcp | |
| HMI (Grafana) | 10.10.30.11 | DMZ | 3000/tcp | published as host :3000 via fw DNAT |
| Engineer laptop | 10.99.0.10 | VPN | - | WireGuard peer |
| Viewer | 10.99.0.20 | VPN | - | WireGuard peer |

Reserved for growth: `10.10.10.15-.99` additional field devices (second PCS, fire panel, weather
station), `10.10.20.11-.19` redundant gateway / PPC, `10.10.30.12-.19` additional DMZ services
(patch server, AV mirror, jump host).

## Routing

| Host | Routes |
|---|---|
| gateway | `default via 10.10.20.254` |
| field devices | `default via 10.10.10.254` (only needed for replies; fw SNAT makes it optional) |
| historian, HMI | none beyond the connected /24 (SNAT design) |
| fw | connected subnets, `default via 172.30.0.1` (wan), `10.99.0.0/24 dev wg0` |

## NAT

| Type | Rule | Why |
|---|---|---|
| DNAT | wan tcp/3000 -> 10.10.30.11:3000 | publish only the HMI |
| SNAT (masquerade) | out of vlan30 | DMZ hosts only ever see 10.10.30.254 - no knowledge of, or routes to, OT addressing |
| SNAT (masquerade) | out of vlan10 | field devices only ever see 10.10.10.254 - devices with a missing/wrong default gateway still work |

## Physical deployment (outside Docker)

On a real Linux edge box the same plan maps to 802.1Q sub-interfaces on one trunk port, e.g. with
systemd-networkd / netplan: `eno1.10`, `eno1.20`, `eno1.30` carrying the `.254` addresses, `eno2` as
the uplink. Rename them to `vlan10/vlan20/vlan30/wan` (or edit the interface names in the template)
and the same `fw.nft` applies unchanged. `lab/netns-lab.sh` proves the policy on plain Linux.

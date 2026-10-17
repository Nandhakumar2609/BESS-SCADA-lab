# Interview guide - talking about this project

## 30-second pitch

> "I built a complete SCADA and data-acquisition lab for a 1 MW / 2 MWh battery storage site on Linux.
> Simulated Modbus TCP devices - PCS, BMS, HVAC and two meters - are generated from a protocol mapping
> table with real-world data types and byte orders. A Python gateway polls them with optimised block
> reads, runs an alarm engine and a simple dispatch loop, and writes to an InfluxDB historian with
> store-and-forward. Grafana shows SoC, availability and faults. The network is segmented into VLAN
> zones behind an nftables firewall with WireGuard remote access, following IEC 62443 zones and
> conduits, and the whole thing deploys with Ansible. I wrote FAT/SAT checklists and automated most
> of the FAT, plus backup/restore and configuration-baseline scripts."

## Demo script (5 minutes)

1. Topology diagram (`docs/topology.png`) - zones, conduits, why SNAT into lower-trust zones.
2. `docs/register_map.md` - point out CDAB on the BMS and the 30001/40001 reference convention.
3. Grafana overview - SoC sawtooth, power flow (PCS vs POI vs AUX - the difference is losses and
   auxiliary load), availability %.
4. `make cli ARGS="dump bms01"` - raw registers next to decoded values.
5. Inject a fault: `make cli ARGS="write pcs01 test_fault_inject 2"` -> PCS trips to 0 kW, alarm
   journal shows RAISED, gateway auto-resets after 30 s.
6. `make fat` - 19 automated tests, Markdown report with sign-off table.
7. `sudo lab/netns-lab.sh all` - 20 network tests: open conduits, denied flows, NAT, spoofing.

## Questions you should expect - and short answers

**Why is Modbus a security problem, and what did you do about it?**
No authentication, no integrity, any client can write. You cannot fix the protocol on legacy devices,
so you protect the zone: only the gateway's IP may reach port 502 of known device IPs, field devices
cannot initiate anything, writes are logged, and remote users never get a path to port 502.

**Holding vs input registers? Function codes?**
Input registers (FC04) are read-only measurements; holding registers (FC03 read, FC06 single write,
FC16 multiple write) hold setpoints/commands. 30001/40001 are 1-based "references"; the wire address is
0-based - a classic off-by-one during commissioning.

**How do you handle 32-bit values?**
Two registers; the device documentation tells you word order (and sometimes byte order). I model
ABCD, CDAB, BADC, DCBA explicitly and test them with known vectors (123.456f = 0x42F6E979). In the
field I cross-check against an independent measurement - a word-swapped float is still a number.

**How did you optimise polling?**
Block reads: contiguous points merged up to 100 registers with a small gap tolerance - 73 points in
8 requests. One TCP connection per IP, shared across unit IDs, with a lock because many devices
handle only one transaction at a time. Fallback to single-point reads if a device rejects a block.

**How do you know data is fresh?**
Comms status per device per scan, latency and error counters, and a heartbeat watchdog: a device can
answer Modbus while its application is frozen - the heartbeat catches that.

**Alarm design?**
On-delay against nuisance alarms, deadband against chattering, severities with an agreed meaning,
bitfield expansion, alarm journal (sequence of events) separate from the live alarm list, "bad actor"
top-10 for alarm rationalisation. Don't clear process alarms when comms are lost.

**Availability - how is it calculated?**
Share of scans where PCS and BMS are online, not faulted and the DC contactor is closed. In a real
contract you'd align it with the definition in the O&M agreement (e.g. exclusions for grid outages).

**Why InfluxDB and not SQL?**
Time-series workload: high-rate append, time-range queries, downsampling, retention policies. Tags
(device, profile) are indexed, fields are values. Store-and-forward in the gateway covers outages.

**Explain your firewall.**
Default drop on input and forward. Explicit conduits by source, destination and port, conntrack for
replies, rate-limited logging of drops, reverse-path anti-spoofing, DNAT to publish only the HMI,
SNAT into the DMZ and field zones. Reload is atomic and only touches its own table - never
`flush ruleset`, which would kill Docker's rules.

**Why WireGuard instead of OpenVPN/IPsec?**
Small code base, modern crypto, per-peer keys + PSK, roles enforced by AllowedIPs plus firewall rules
on the peer's tunnel address. Split tunnel so the laptop doesn't route everything into OT.

**What is IEC 62443 in one sentence?**
A family of standards for industrial cyber security: zones and conduits with target security levels
(3-2), technical requirements for systems (3-3, FR1-FR7) and components (4-2), and a secure
development process for suppliers (4-1).

**FAT vs SAT?**
FAT proves the system against the specification in a controlled environment before shipping; SAT
proves the installed system with real devices, wiring and network on site, plus handover items.

**What would you change for production?**
Redundant gateway, TLS everywhere inside the DMZ, central identity, SIEM/IDS on the field VLAN,
unidirectional data diode at SL 3, signed images, monitoring of the host itself, and an alarm
philosophy agreed with the operator (EEMUA 191 / ISA-18.2).

## Numbers worth remembering

1 MW / 2 MWh, 416 LFP cells (~1.33 kV DC), 690 V AC, 20 kV POI, 2 s scan, 73 points / 8 requests,
46 alarm instances, 4 zones + VPN, 5 conduits, 19 automated FAT tests, 20 network tests, 86 unit /
integration tests.

# Site Acceptance Test (SAT) - BESS site SCADA

SAT repeats the critical FAT items on the installed system with the **real** devices, and adds
what cannot be tested in the factory: field wiring, real device firmware, site network, grid
interaction, and handover. In this lab the "site" is a fresh host deployed with `make deploy`
(Ansible), so the SAT also proves the deployment is reproducible.

| | |
|---|---|
| Pre-conditions | FAT passed and punch list closed; devices energised; site network patched; time source available |
| Deployment | `cd ansible && ansible-playbook site.yml` on the site host |
| Reference | FAT report, configuration baseline from FAT, as-built IP plan |

## 1. Installation

| ID | Check | Expected | Result |
|---|---|---|---|
| SAT-INS-01 | Deployment from Ansible completes with no failed tasks | `failed=0` | |
| SAT-INS-02 | Second Ansible run is idempotent | `changed=0` (except baseline capture) | |
| SAT-INS-03 | Host hardening applied | `sshd -T` shows no root login; `nft list table inet bess_host`; `auditctl -l` | |
| SAT-INS-04 | Time sync | `chronyc tracking` offset < 100 ms | |
| SAT-INS-05 | Configuration equals FAT baseline (except site-specific IPs/keys) | `scripts/baseline.sh check` diff reviewed | |

## 2. Field devices (point-to-point check)

For every point in `docs/register_map.md`: force or observe the value at the device (vendor HMI,
multimeter, test set) and compare with the SCADA value.

| ID | Check | Expected | Result |
|---|---|---|---|
| SAT-P2P-01 | PCS measurements vs PCS local display | Within device accuracy | |
| SAT-P2P-02 | BMS SoC, cell min/max vs BMS service tool | Identical | |
| SAT-P2P-03 | Meter values vs utility meter / power analyser | Within 0.5 % | |
| SAT-P2P-04 | Each fault/alarm bit simulated at the device | Correct alarm text and severity in SCADA | |
| SAT-P2P-05 | Commands (run/stop, setpoints) | Device reacts, readback correct | |

## 3. Functional

| ID | Check | Expected | Result |
|---|---|---|---|
| SAT-FUN-01 | Run automated FAT on site (`make fat`) | 0 failed | |
| SAT-FUN-02 | Full charge/discharge cycle | SoC window respected, energy counters plausible, round-trip efficiency ~93 % | |
| SAT-FUN-03 | Comms loss per device (unplug cable) | Alarm within 10 s, no false process alarms, dispatch stops | |
| SAT-FUN-04 | Power cycle of the SCADA host | Stack restarts automatically, no data loss beyond outage, alarms re-evaluated | |
| SAT-FUN-05 | Historian outage during operation | Store-and-forward back-fills | |

## 4. Network and cyber security

| ID | Check | Expected | Result |
|---|---|---|---|
| SAT-NET-01 | `make netlab`-equivalent probes from each zone | Only listed conduits open | |
| SAT-NET-02 | External port scan of site uplink | Only 51820/udp (and 3000 if agreed) | |
| SAT-NET-03 | VPN with site public IP; engineer and viewer roles | As FAT-VPN-01/02 | |
| SAT-NET-04 | Firewall drop log forwarded / retained | Visible, rotated | |
| SAT-SEC-01 | Default passwords changed, `.env` generated on site | No lab defaults | |
| SAT-SEC-02 | Accounts list reviewed with client | Named users only, no shared admin | |

## 5. Backup / restore and handover

| ID | Check | Expected | Result |
|---|---|---|---|
| SAT-BR-01 | Scheduled backup ran (`systemctl list-timers bess-*`) | Archive in `/var/backups/bess-lab` | |
| SAT-BR-02 | Restore test on a spare host or after `make clean` | System back, FAT passes | |
| SAT-HO-01 | As-built documents | IP plan, register map, alarm list, topology, FAT/SAT reports, baseline | |
| SAT-HO-02 | Credentials handed over securely | WireGuard client configs and `.env` transferred, removed from integrator laptop | |
| SAT-HO-03 | Operator training | Dashboards, alarm handling, reset procedure | |

## Sign-off

| Role | Name | Signature | Date |
|---|---|---|---|
| Commissioning engineer | | | |
| Client representative | | | |
| Open punch-list items | | | |

# Factory Acceptance Test (FAT) - BESS site SCADA

| | |
|---|---|
| Project | BESS Lab Site 01 - 1 MW / 2 MWh |
| System under test | SCADA gateway, historian, HMI, OT network, firewall, remote access |
| Test environment | Docker stack (`make up`) with simulated field devices |
| Pre-conditions | All containers healthy (`make ps`), `.env` present, baseline captured |
| Automated part | `make fat` -> `reports/FAT_report_<date>.md` (tests marked **A**) |

Result codes: P = pass, F = fail (raise a punch-list item), N/A.

## 1. Documentation and configuration

| ID | Check | Method | Expected | Result |
|---|---|---|---|---|
| FAT-DOC-01 | Register map matches device documentation | Review `docs/register_map.md` against vendor maps | Every point: address, type, byte order, scale, unit | |
| FAT-DOC-02 | IP plan matches running system | `docker network inspect`, `make ps` | Addresses as `docs/ip_plan.md` | |
| FAT-DOC-03 | Configuration baseline captured | `make baseline` | `baselines/current` exists | |
| FAT-DOC-04 | Software versions recorded | `baselines/current/images.txt`, `python-packages.txt` | Pinned versions | |

## 2. Field communications (Modbus TCP)

| ID | Check | Method | Expected | Result |
|---|---|---|---|---|
| FAT-COM-01..05 **A** | Each device answers all mapped points | FAT runner | All points read, no exception | |
| FAT-COM-06 **A** | Unit-ID routing behind one IP | FAT runner | Meter unit 1 = MV (~20 kV), unit 2 = LV (~400 V) | |
| FAT-COM-07 | Comms-loss detection | `docker compose stop field-sim` for 15 s | `COMMS_LOSS` critical per device within 6 s + scan; comms panel red; restart -> alarms clear | |
| FAT-COM-08 | Scan time | Alarms dashboard "Gateway scan time" | < 200 ms at 2 s cycle | |

## 3. Data integrity

| ID | Check | Method | Expected | Result |
|---|---|---|---|---|
| FAT-DAT-01 **A** | Heartbeats increment | FAT runner | All devices increment | |
| FAT-DAT-02 **A** | Engineering ranges plausible | FAT runner | SoC 0-100 %, f 49-51 Hz, cell V 2.5-3.7 V ... | |
| FAT-DAT-03 **A** | Scaling / word order cross-check | PCS DC V (uint16 x0.1) vs BMS pack V (uint32 CDAB x0.01) | Within 1 % | |
| FAT-DAT-04 **A** | Byte-swapped float (BADC) | Meter `energy_check` vs export - import | Within 1 kWh | |
| FAT-DAT-05 **A** | Power balance | PCS - AUX vs POI | Within 3 % of rated (losses) | |
| FAT-DAT-06 | Sign conventions | Charge the battery | PCS power negative, POI negative (import), SoC rising | |
| FAT-DAT-07 | Timestamps | Compare Grafana time with host clock (chrony) | < 1 s | |

## 4. Control

| ID | Check | Method | Expected | Result |
|---|---|---|---|---|
| FAT-CTL-01 **A** | Setpoint write / readback | FAT runner (HVAC setpoint 24.5 °C) | Readback equals written value; original restored | |
| FAT-CTL-02 **A** | Writes outside the map rejected | FAT runner (holding 40061) | Modbus exception | |
| FAT-CTL-03 **A** | PCS follows P setpoint | FAT runner | Within 2 % of the (limit-clamped) setpoint | |
| FAT-CTL-04 | SoC window dispatch | Watch "State of charge" over one cycle | Charges to 90 %, discharges to 20 %, repeats | |
| FAT-CTL-05 | BMS limit clamp | Let SoC approach 100 % (set `soc_high: 99`) | PCS power tapers, `SETPOINT_CLAMPED` warning | |
| FAT-CTL-06 | LOCAL mode blocks SCADA | `make cli ARGS="write pcs01 control_mode 0"` | Dispatcher stops writing; restore with 1 | |
| FAT-CTL-07 | No dispatch on missing data | Stop field-sim | Gateway issues no writes (log) | |

## 5. Alarms

| ID | Check | Method | Expected | Result |
|---|---|---|---|---|
| FAT-ALM-01 **A** | PCS trip, latch, reset | FAT runner (fault injection bit 0) | 0 kW within one tick, FAULT latched until reset | |
| FAT-ALM-02 **A** | Non-trip BMS alarm | FAT runner (imbalance) | Alarm raised and cleared, contactor stays closed | |
| FAT-ALM-03 **A** | Watchdog input | FAT runner (heartbeat freeze) | Heartbeat frozen, then resumes | |
| FAT-ALM-04 | Stale-data alarm | `make cli ARGS="write hvac01 test_fault_inject 16384"` for 20 s | `HEARTBEAT_STALE` (major) after ~14 s; clears after reset to 0 | |
| FAT-ALM-05 | Auto fault-reset supervision | Inject PCS fault bit 1 for 3 s | Gateway resets after 30 s; after 3 resets/h logs "manual intervention required" | |
| FAT-ALM-06 | Alarm journal | Alarms dashboard | Every RAISED has a CLEARED with timestamps | |
| FAT-ALM-07 | Alarm list complete | Compare `docs/alarm_list.md` with client alarm philosophy | All alarms, severities, delays agreed | |

## 6. Historian and HMI

| ID | Check | Method | Expected | Result |
|---|---|---|---|---|
| FAT-HIS-01 **A** | Telemetry stored | FAT runner (Flux query, read-only token) | Samples in last 30 s | |
| FAT-HIS-02 **A** | Alarm events stored | FAT runner | PCS fault event present | |
| FAT-HIS-03 | Store-and-forward | `docker compose stop influxdb` 60 s, start | Gap back-filled (no hole in SoC trend) | |
| FAT-HIS-04 | Token privileges | Use gateway token to query; Grafana token to write | Both refused (401/403) | |
| FAT-HMI-01 | Dashboards load | Open both dashboards | All panels show data, no errors | |
| FAT-HMI-02 | Availability KPI | Inject a PCS fault for 2 min | Availability % drops accordingly | |
| FAT-HMI-03 | Dashboards are read-only | Try to save an edit | Refused (provisioned, `allowUiUpdates: false`) | |

## 7. Network and security (also proven automatically by `make netlab`)

| ID | Check | Method | Expected | Result |
|---|---|---|---|---|
| FAT-NET-01 | Conduit C1 only | From gateway: `nc -zv 10.10.10.11 22` | Timeout (dropped) | |
| FAT-NET-02 | No upward connections | From field-sim: connect to 10.10.20.10 | Timeout | |
| FAT-NET-03 | DMZ cannot reach OT | From historian: connect to 10.10.10.11:502 | No route | |
| FAT-NET-04 | No internet from OT | From gateway: `ping 1.1.1.1` | Fails | |
| FAT-NET-05 | Only HMI published | `nmap` the host from another machine | 3000/tcp, 51820/udp (+ SSH) only | |
| FAT-NET-06 | Drops are logged | `docker compose exec fw tail /var/log/fw/drops.log` | Denied attempts above visible | |
| FAT-NET-07 | Anti-spoofing | `make netlab` test "spoofed field source" | Dropped, FW-SPOOF counter > 0 | |
| FAT-VPN-01 | Engineer VPN | Connect engineer peer | HMI, historian API reachable; field 502 not reachable | |
| FAT-VPN-02 | Viewer VPN | Connect viewer peer | Only HMI reachable | |
| FAT-SEC-01 | Containers run unprivileged | `docker compose exec gateway grep Uid /proc/1/status` | uid 10001 (`bess`) | |
| FAT-SEC-02 | Secrets not in git | `git status`, `.gitignore` | `.env`, keys, configs excluded | |

## 8. Backup and recovery

| ID | Check | Method | Expected | Result |
|---|---|---|---|---|
| FAT-BR-01 | Backup | `make backup` | Archive + manifest + .sha256 | |
| FAT-BR-02 | Restore | `make clean && make up && make restore FILE=...` | History back, FAT passes | |
| FAT-BR-03 | Drift detection | Edit `config/alarms.yaml`, `make drift` | Drift reported, exit 1 | |

## Sign-off

| Role | Name | Signature | Date |
|---|---|---|---|
| Tested by (integrator) | | | |
| Witnessed by (client) | | | |
| Punch-list items open | | | |

# Operations runbook

## Everyday commands

| Task | Command |
|---|---|
| Start (segmented) / demo (flat) | `make up` / `make demo` |
| Status, logs | `make ps`, `make logs` |
| Read a device like a commissioning tool | `make cli ARGS="dump bms01"` |
| Write a setpoint | `make cli ARGS="write hvac01 cooling_setpoint_c 24"` |
| Automated FAT | `make fat` (report in `reports/`) |
| Backup / restore | `make backup`, `make restore FILE=backups/bess-backup_<ts>.tar.gz` |
| Baseline / drift | `make baseline`, `make drift` |
| Firewall counters | `docker compose exec fw nft list ruleset` |
| Dropped traffic | `docker compose exec fw tail -f /var/log/fw/drops.log` |
| VPN status | `docker compose exec fw wg show` |

Add `MODE=simple` to any target when running the flat demo stack.

## Alarm handling

1. Alarms dashboard -> "Active alarms": sort by severity.
2. `COMMS_LOSS` on all devices at once -> check `fw` container and field network first (one cause,
   many symptoms). On one device only -> device / cable / IP conflict.
3. `PCS_FAULT_*` -> the gateway auto-resets after 30 s, max 3 times per hour. After the limit, find the
   cause before a manual reset: `make cli ARGS="write pcs01 fault_reset 1"`.
4. `HEARTBEAT_STALE` -> device answers but its application is hung: power-cycle the device controller.

## Backup and restore

- Timer: daily 02:30 (`systemctl list-timers bess-backup.timer`), retention 14 days.
- Contents: InfluxDB native backup, Grafana DB, all configuration incl. `.env`, WireGuard server
  config, baseline; `MANIFEST.sha256` inside, `.sha256` next to the archive.
- Restore always verifies checksums first, stops the gateway (no writes during restore), restores,
  restarts and tells you to re-run the FAT.
- Restore test is part of SAT (SAT-BR-02) - an untested backup is not a backup.

## Configuration changes (management of change)

1. Change the source (`config/*.csv|yaml`, `ansible/group_vars/all.yml`, `tools/build_dashboards.py`).
2. Regenerate: `make render dashboards` and `python tools/gen_docs.py`.
3. `make check` (render up to date, nft syntax, Ansible syntax, tests).
4. Deploy (`make up` or `make deploy`), run `make fat`.
5. `make baseline` to approve the new configuration. The daily drift check compares against it.

## Troubleshooting

| Symptom | Check |
|---|---|
| Grafana "No data" | `make logs` - gateway writing? `docker compose exec gateway cat /secrets/gateway.token` non-empty? |
| `influxdb` never healthy | `docker compose logs influxdb` - first-start init must create the two tokens; delete volumes (`make clean`) to re-run it |
| Gateway: all devices DOWN | `docker compose exec gateway ip route` must show `default via 10.10.20.254`; `docker compose logs fw` for interface renaming |
| localhost:3000 not answering (segmented mode) | Docker Engine 28+ needed for `gw_priority`; `docker compose exec fw nft list chain inet bess_fw prerouting_nat` counter rising? Use `make demo` meanwhile |
| VPN disabled message | host kernel lacks WireGuard (`modprobe wireguard`); rest of the lab works |
| Wrong values after editing the map | run `make cli ARGS="dump <device>"`: raw registers are printed next to decoded values - check byte order and scale |

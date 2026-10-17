"""Automated Factory Acceptance Test (FAT) runner.

Runs the automatable part of docs/FAT_checklist.md against a running system and writes
a timestamped Markdown report to reports/. Run it from the OT control zone:

    docker compose exec gateway python -m bess_lab.fat
    python -m bess_lab.fat --local          # against a --local simulator
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import time
import urllib.request
from pathlib import Path

from pymodbus.client import ModbusTcpClient

from .config import CONFIG_DIR, load_site
from .regmap import RegisterMap


class Fat:
    def __init__(self, local: bool):
        self.site = load_site(local=local)
        self.map = RegisterMap.load(CONFIG_DIR / "register_map.csv")
        self.dev = {d.name: d for d in self.site["devices"]}
        self.clients: dict = {}
        self.results: list[dict] = []

    # --------------------------------------------------------------- helpers
    def client(self, name):
        d = self.dev[name]
        key = (d.host, d.port)
        if key not in self.clients:
            c = ModbusTcpClient(d.host, port=d.port, timeout=2, retries=1)
            c.connect()
            self.clients[key] = c
        return self.clients[key], d

    def read(self, name, point):
        c, d = self.client(name)
        p = self.map.get(d.profile, point)
        fn = c.read_input_registers if p.table == "input" else c.read_holding_registers
        rr = fn(p.address, count=p.count, device_id=d.unit_id)
        if rr.isError():
            raise RuntimeError(f"{name}.{point}: {rr}")
        return p.decode(rr.registers)

    def write(self, name, point, value):
        c, d = self.client(name)
        p = self.map.get(d.profile, point)
        rr = c.write_registers(p.address, p.encode(value), device_id=d.unit_id)
        if rr.isError():
            raise RuntimeError(f"write {name}.{point}: {rr}")

    def wait_for(self, fn, timeout=10.0, every=0.5):
        end = time.time() + timeout
        while time.time() < end:
            if fn():
                return True
            time.sleep(every)
        return False

    def check(self, test_id, title, func):
        t0 = time.time()
        try:
            ok, detail = func()
            status = "PASS" if ok else "FAIL"
        except SkipTest as s:
            status, detail = "SKIP", str(s)
        except Exception as exc:  # noqa: BLE001 - a FAT runner must never stop on one test
            status, detail = "FAIL", f"{type(exc).__name__}: {exc}"
        self.results.append({"id": test_id, "title": title, "status": status, "detail": detail,
                             "duration_s": round(time.time() - t0, 1)})
        print(f"[{status}] {test_id} {title} - {detail}")

    # --------------------------------------------------------------- historian
    def flux(self, query: str) -> int:
        path = os.environ.get("INFLUX_READ_TOKEN_FILE", "")
        token = open(path).read().strip() if path and os.path.exists(path) else os.environ.get("INFLUX_READ_TOKEN")
        if not token:
            raise SkipTest("no historian read token (INFLUX_READ_TOKEN or INFLUX_READ_TOKEN_FILE)")
        h = self.site["historian"]
        url = f"{os.environ.get('INFLUX_URL', h['url'])}/api/v2/query?org={os.environ.get('INFLUX_ORG', h['org'])}"
        req = urllib.request.Request(url, method="POST", data=json.dumps({"query": query, "type": "flux"}).encode(),
                                     headers={"Authorization": f"Token {token}", "Content-Type": "application/json",
                                              "Accept": "application/csv"})
        with urllib.request.urlopen(req, timeout=10) as r:
            rows = [ln for ln in r.read().decode().splitlines() if ln and not ln.startswith(("#", ",result"))]
        return len(rows)

    # --------------------------------------------------------------- tests
    def run(self):
        bucket = os.environ.get("INFLUX_BUCKET", self.site["historian"]["bucket"])

        for i, name in enumerate(self.dev, start=1):
            def comms(name=name):
                d = self.dev[name]
                pts = self.map.select(d.profile)
                vals = {p.name: self.read(name, p.name) for p in pts}
                return True, f"{len(vals)} points read from {d.host}:{d.port} unit {d.unit_id}"
            self.check(f"FAT-COM-{i:02d}", f"Modbus communication {name}", comms)

        self.check("FAT-COM-06", "Unit-ID routing behind shared endpoint (meter_poi vs meter_aux)", lambda: (
            (a := self.read("meter_poi", "voltage_ll_v")) > 10000 and (b := self.read("meter_aux", "voltage_ll_v")) < 1000,
            f"POI {a:.0f} V (MV), AUX {b:.0f} V (LV)"))

        def heartbeat():
            h1 = {n: self.read(n, "heartbeat") for n in ("pcs01", "bms01", "hvac01")}
            time.sleep(3)
            h2 = {n: self.read(n, "heartbeat") for n in h1}
            return all(h2[n] != h1[n] for n in h1), f"{h1} -> {h2}"
        self.check("FAT-DAT-01", "Device heartbeats increment", heartbeat)

        def ranges():
            limits = {("bms01", "soc_pct"): (0, 100), ("pcs01", "frequency_hz"): (49, 51),
                      ("bms01", "max_cell_voltage_v"): (2.5, 3.7), ("bms01", "min_cell_voltage_v"): (2.5, 3.7),
                      ("hvac01", "container_temp_c"): (-20, 60), ("pcs01", "ac_voltage_v"): (600, 780)}
            bad = []
            for (n, p), (lo, hi) in limits.items():
                v = self.read(n, p)
                if not lo <= v <= hi:
                    bad.append(f"{n}.{p}={v}")
            return not bad, "all within engineering range" if not bad else "out of range: " + ", ".join(bad)
        self.check("FAT-DAT-02", "Engineering-range plausibility", ranges)

        self.check("FAT-DAT-03", "Scaling/word order: PCS DC voltage (uint16 x0.1) = BMS pack voltage (uint32 CDAB x0.01)",
                   lambda: (abs((a := self.read("pcs01", "dc_voltage_v")) - (b := self.read("bms01", "pack_voltage_v"))) < 0.01 * b,
                            f"PCS {a} V vs BMS {b} V"))

        def badc():
            imp, exp_, chk = (self.read("meter_poi", p) for p in ("energy_import_kwh", "energy_export_kwh", "energy_check"))
            return abs((exp_ - imp) - chk) < 1.0, f"export-import={exp_ - imp:.1f} kWh, BADC float={chk:.1f} kWh"
        self.check("FAT-DAT-04", "Byte-swapped float (BADC) decodes correctly", badc)

        def balance():
            p_pcs, p_aux, p_poi = (self.read(n, "active_power_kw" if n == "pcs01" else "p_total_kw")
                                   for n in ("pcs01", "meter_aux", "meter_poi"))
            err = p_poi - (p_pcs - p_aux)
            return abs(err) < 0.03 * self.site["site"]["rated_power_kw"], \
                f"PCS {p_pcs:.1f} - AUX {p_aux:.1f} vs POI {p_poi:.1f} kW (losses {-err:.1f} kW)"
        self.check("FAT-DAT-05", "Site power balance PCS - AUX = POI + losses", balance)

        def setpoint_rw():
            orig = self.read("hvac01", "cooling_setpoint_c")
            self.write("hvac01", "cooling_setpoint_c", 24.5)
            back = self.read("hvac01", "cooling_setpoint_c")
            self.write("hvac01", "cooling_setpoint_c", orig)
            return back == 24.5 and self.read("hvac01", "cooling_setpoint_c") == orig, \
                f"wrote 24.5, read back {back}, restored {orig}"
        self.check("FAT-CTL-01", "Setpoint write / readback (HVAC cooling setpoint, int16 x0.1)", setpoint_rw)

        def reject():
            c, d = self.client("pcs01")
            rr = c.write_register(60, 1, device_id=d.unit_id)
            return rr.isError(), f"write to unmapped holding 40061 -> {'rejected' if rr.isError() else 'ACCEPTED'}"
        self.check("FAT-CTL-02", "Write outside the map is rejected (exception response)", reject)

        def follows():
            def close():
                sp, p = self.read("pcs01", "p_setpoint_kw"), self.read("pcs01", "active_power_kw")
                lim = self.read("pcs01", "available_discharge_kw" if sp > 0 else "available_charge_kw")
                target = max(-lim, min(lim, sp))
                follows.last = (sp, p, target)
                return abs(p - target) <= 0.02 * self.site["site"]["rated_power_kw"]
            ok = self.wait_for(close, timeout=20)
            sp, p, target = follows.last
            return ok, f"setpoint {sp:.0f} kW, limited target {target:.0f} kW, measured {p:.1f} kW"
        self.check("FAT-CTL-03", "PCS active power follows SCADA setpoint", follows)

        def pcs_fault():
            self.write("pcs01", "test_fault_inject", 1)
            tripped = self.wait_for(lambda: self.read("pcs01", "state") == 4 and int(self.read("pcs01", "fault_word")) & 1, 8)
            p_trip = self.read("pcs01", "active_power_kw")
            self.write("pcs01", "test_fault_inject", 0)
            time.sleep(4)                                  # fault must stay latched (and be seen by SCADA scans)
            latched = self.read("pcs01", "state") == 4
            self.write("pcs01", "fault_reset", 1)
            recovered = self.wait_for(lambda: self.read("pcs01", "state") != 4, 10)
            return tripped and abs(p_trip) < 1 and latched and recovered, \
                f"trip={tripped}, power at trip={p_trip:.1f} kW, latched until reset={latched}, recovered={recovered}"
        self.check("FAT-ALM-01", "PCS fault trips to 0 kW, stays latched, reset recovers", pcs_fault)

        def bms_alarm():
            self.write("bms01", "test_fault_inject", 1 << 4)
            seen = self.wait_for(lambda: int(self.read("bms01", "alarm_word")) >> 4 & 1 == 1, 6)
            time.sleep(4)                                  # hold for two SCADA scans
            contactor = self.read("bms01", "contactor_closed")
            self.write("bms01", "test_fault_inject", 0)
            cleared = self.wait_for(lambda: int(self.read("bms01", "alarm_word")) >> 4 & 1 == 0, 6)
            return seen and contactor == 1 and cleared, \
                f"imbalance alarm seen={seen}, contactor stayed closed={contactor == 1} (non-trip alarm), cleared={cleared}"
        self.check("FAT-ALM-02", "BMS non-trip alarm (cell imbalance) raised and cleared", bms_alarm)

        def watchdog():
            self.write("hvac01", "test_fault_inject", 1 << 14)
            time.sleep(1.5)
            a = self.read("hvac01", "heartbeat"); time.sleep(3); b = self.read("hvac01", "heartbeat")
            self.write("hvac01", "test_fault_inject", 0)
            time.sleep(2.5)
            c = self.read("hvac01", "heartbeat")
            return a == b and c != b, f"frozen {a}->{b}, resumed ->{c}"
        self.check("FAT-ALM-03", "Heartbeat freeze detectable (watchdog input)", watchdog)

        self.check("FAT-HIS-01", "Historian receives telemetry (last 30 s)", lambda: (
            (n := self.flux(f'from(bucket:"{bucket}") |> range(start:-30s) |> filter(fn:(r)=>r._measurement=="telemetry" and r._field=="soc_pct")')) > 0,
            f"{n} SoC samples in the last 30 s"))
        self.check("FAT-HIS-02", "Alarm journal contains the FAT-ALM-01 PCS fault event", lambda: (
            (n := self.flux(f'from(bucket:"{bucket}") |> range(start:-5m) |> filter(fn:(r)=>r._measurement=="alarm_event" and r.alarm_id=="PCS_FAULT_IGBT_OVERTEMP" and r._field=="active")')) > 0,
            f"{n} journal entries"))

    def report(self, out_dir: Path) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        now = dt.datetime.now().astimezone()
        path = out_dir / f"FAT_report_{now:%Y%m%d_%H%M%S}.md"
        n = {s: sum(r["status"] == s for r in self.results) for s in ("PASS", "FAIL", "SKIP")}
        lines = [f"# FAT report - {self.site['site']['name']}", "",
                 f"- Date: {now:%Y-%m-%d %H:%M:%S %Z}", f"- Host: {platform.node()}",
                 f"- Result: **{n['PASS']} passed, {n['FAIL']} failed, {n['SKIP']} skipped**", "",
                 "| ID | Test | Result | Evidence | s |", "|---|---|---|---|---|"]
        lines += [f"| {r['id']} | {r['title']} | {r['status']} | {r['detail']} | {r['duration_s']} |" for r in self.results]
        lines += ["", "Manual FAT items (network, firewall, VPN, backup) are in docs/FAT_checklist.md.", "",
                  "| Role | Name | Signature | Date |", "|---|---|---|---|",
                  "| Tested by | | | |", "| Witnessed by (client) | | | |"]
        path.write_text("\n".join(lines) + "\n")
        (path.with_suffix(".json")).write_text(json.dumps(self.results, indent=2))
        return path


class SkipTest(Exception):
    pass


def main() -> None:
    ap = argparse.ArgumentParser(description="Automated FAT runner")
    ap.add_argument("--local", action="store_true")
    ap.add_argument("--out", default=os.environ.get("FAT_REPORT_DIR", "reports"))
    args = ap.parse_args()
    fat = Fat(args.local)
    try:
        fat.run()
    finally:
        for c in fat.clients.values():
            c.close()
    path = fat.report(Path(args.out))
    print(f"\nreport: {path}")
    raise SystemExit(1 if any(r["status"] == "FAIL" for r in fat.results) else 0)


if __name__ == "__main__":
    main()

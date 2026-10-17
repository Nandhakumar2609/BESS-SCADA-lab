#!/usr/bin/env python3
"""Generate docs/register_map.md and docs/alarm_list.md from the configuration files,
so documentation can never disagree with what the code actually polls and alarms on."""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from bess_lab.config import load_site  # noqa: E402
from bess_lab.gateway.alarms import AlarmEngine  # noqa: E402
from bess_lab.regmap import RegisterMap  # noqa: E402

regmap = RegisterMap.load(ROOT / "config/register_map.csv")
site = load_site(ROOT / "config/site.yaml")
TITLES = {"pcs": "PCS - power conversion system", "bms": "BMS - battery management system",
          "hvac": "HVAC - container climate", "meter": "Power meters (POI and auxiliary)"}

out = ["# Protocol mapping table (register map)", "",
       "_Generated from `config/register_map.csv` by `tools/gen_docs.py` - edit the CSV, not this file._", "",
       "Conventions:", "",
       "- **Address** is the 0-based protocol address on the wire; **Ref** is the classic Modicon reference "
       "(30001 + address for input registers / FC04, 40001 + address for holding registers / FC03, FC06, FC16).",
       "- **Byte order**: `AB`/`ABCD` big-endian, `CDAB` word-swapped, `BADC` byte-swapped, `DCBA` little-endian.",
       "- **Engineering value = raw x scale.** Signed power: + discharge / export, - charge / import.", "",
       "## Device instances", "", "| Device | Profile | IP:port | Unit ID |", "|---|---|---|---|"]
out += [f"| {d.name} | {d.profile} | {d.host}:{d.port} | {d.unit_id} |" for d in site["devices"]]
for prof in ("pcs", "bms", "hvac", "meter"):
    out += ["", f"## {TITLES[prof]}", ""]
    for table, fc in (("input", "FC04"), ("holding", "FC03 / FC06 / FC16")):
        pts = regmap.select(prof, table)
        if not pts:
            continue
        blocks = regmap.plan_blocks(prof, table)
        out += [f"**{table.title()} registers** ({fc}) - polled in {len(blocks)} block read(s): "
                + ", ".join(f"{s}..{s + c - 1}" for s, c, _ in blocks), "",
                "| Ref | Addr | Name | Type | Order | Scale | Unit | Access | Description | Values |",
                "|---|---|---|---|---|---|---|---|---|---|"]
        for p in pts:
            vals = "; ".join(f"{k}={v}" for k, v in p.enum.items()) or \
                   "; ".join(f"bit{k}={v}" for k, v in p.bits.items())
            addr = f"{p.address}" if p.count == 1 else f"{p.address}-{p.end - 1}"
            out.append(f"| {p.reference} | {addr} | `{p.name}` | {p.data_type} | {p.byte_order} | {p.scale:g} | "
                       f"{p.unit} | {p.access} | {p.description} | {vals} |")
(ROOT / "docs/register_map.md").write_text("\n".join(out) + "\n")

cfg = yaml.safe_load((ROOT / "config/alarms.yaml").read_text())
eng = AlarmEngine(cfg, site["devices"], regmap)
rows = ["# Alarm list", "",
        "_Generated from `config/alarms.yaml` by `tools/gen_docs.py`. Bitfield alarms are expanded per bit._", "",
        f"{len(eng.defs)} alarm instances. Severity: critical = trip / loss of function, major = action today, "
        "minor = action this week, warning = information.", "",
        "| Alarm ID | Device | Severity | Type | Condition | Deadband | On-delay | Message |",
        "|---|---|---|---|---|---|---|---|"]
for d in sorted(eng.defs, key=lambda d: ({"critical": 0, "major": 1, "minor": 2, "warning": 3}[d.severity], d.device, d.id)):
    cond = {"high": f"`{d.point}` > {d.setpoint}", "low": f"`{d.point}` < {d.setpoint}",
            "spread": f"`{d.a}` - `{d.b}` > {d.setpoint}", "bitfield": f"`{d.point}` bit {d.bit}",
            "comms": "no Modbus response", "stale": f"`{d.point}` frozen"}[d.type]
    rows.append(f"| {d.id} | {d.device} | {d.severity} | {d.type} | {cond} | {d.deadband or ''} | "
                f"{d.delay_s:g} s | {d.message} |")
(ROOT / "docs/alarm_list.md").write_text("\n".join(rows) + "\n")
print("wrote docs/register_map.md and docs/alarm_list.md")

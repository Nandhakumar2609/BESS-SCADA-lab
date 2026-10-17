"""Commissioning tool: read / write / dump points by name, showing raw registers.

    python -m bess_lab.cli dump pcs01
    python -m bess_lab.cli read bms01 soc_pct pack_voltage_v
    python -m bess_lab.cli write hvac01 cooling_setpoint_c 24.5
    python -m bess_lab.cli map            # print the register map with 3xxxx/4xxxx references
Add --local to talk to a simulator started with --local.
"""
from __future__ import annotations

import argparse
import sys

from pymodbus.client import ModbusTcpClient

from .config import CONFIG_DIR, load_site
from .regmap import RegisterMap


def _client(dev):
    c = ModbusTcpClient(dev.host, port=dev.port, timeout=2, retries=1)
    if not c.connect():
        sys.exit(f"cannot connect to {dev.name} at {dev.host}:{dev.port}")
    return c


def _read(c, dev, p):
    fn = c.read_input_registers if p.table == "input" else c.read_holding_registers
    rr = fn(p.address, count=p.count, device_id=dev.unit_id)
    if rr.isError():
        return None, str(rr)
    return rr.registers, None


def main() -> None:
    ap = argparse.ArgumentParser(description="Modbus commissioning tool")
    ap.add_argument("--local", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("map")
    d = sub.add_parser("dump"); d.add_argument("device")
    r = sub.add_parser("read"); r.add_argument("device"); r.add_argument("points", nargs="+")
    w = sub.add_parser("write"); w.add_argument("device"); w.add_argument("point"); w.add_argument("value", type=float)
    args = ap.parse_args()

    regmap = RegisterMap.load(CONFIG_DIR / "register_map.csv")
    if args.cmd == "map":
        print(f"{'profile':7} {'ref':>6} {'name':24} {'type':8} {'order':5} {'scale':>6} {'unit':5} access")
        for p in regmap.points:
            print(f"{p.profile:7} {p.reference:>6} {p.name:24} {p.data_type:8} {p.byte_order:5} {p.scale:>6g} {p.unit:5} {p.access}")
        return

    devices = {x.name: x for x in load_site(local=args.local)["devices"]}
    dev = devices.get(args.device) or sys.exit(f"unknown device; choose from {', '.join(devices)}")
    c = _client(dev)
    try:
        if args.cmd == "write":
            p = regmap.get(dev.profile, args.point)
            regs = p.encode(args.value)
            rr = c.write_registers(p.address, regs, device_id=dev.unit_id)
            print(f"WRITE {dev.name}.{p.name} = {args.value} raw={[hex(x) for x in regs]} -> "
                  f"{'OK' if not rr.isError() else rr}")
            regs, err = _read(c, dev, p)
            print(f"readback: {p.decode(regs) if regs else err}")
            return
        points = regmap.select(dev.profile) if args.cmd == "dump" else [regmap.get(dev.profile, n) for n in args.points]
        print(f"{dev.name} @ {dev.host}:{dev.port} unit {dev.unit_id}")
        print(f"{'ref':>6} {'name':24} {'raw registers':22} {'value':>14} unit  meaning")
        for p in points:
            regs, err = _read(c, dev, p)
            if err:
                print(f"{p.reference:>6} {p.name:24} ERROR {err}")
                continue
            val = p.decode(regs)
            meaning = p.enum.get(int(val), "") if p.enum else \
                ",".join(n for b, n in p.bits.items() if int(val) >> b & 1) if p.bits else ""
            raw = " ".join(f"{x:04X}" for x in regs)
            print(f"{p.reference:>6} {p.name:24} {raw:22} {val:>14g} {p.unit:5} {meaning}")
    finally:
        c.close()


if __name__ == "__main__":
    main()

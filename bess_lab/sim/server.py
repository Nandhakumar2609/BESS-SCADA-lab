"""Modbus TCP field-device simulator.

Starts one Modbus TCP server per (IP, port) endpoint in site.yaml. Devices that share an
endpoint (the two meters) are served as different unit IDs, like a serial gateway.

    python -m bess_lab.sim.server            # bind the IPs from site.yaml (Docker / lab network)
    python -m bess_lab.sim.server --local    # bind 127.0.0.1:5020.. for a laptop run
"""
from __future__ import annotations

import argparse
import asyncio
import functools
import logging
import os

from pymodbus.constants import ExcCodes
from pymodbus.server import ModbusTcpServer
from pymodbus.simulator import DataType, SimData, SimDevice

from ..config import CONFIG_DIR, load_site
from ..regmap import RegisterMap
from .model import DeviceImage, SiteModel

log = logging.getLogger("sim")
audit = logging.getLogger("sim.audit")


async def _action(img: DeviceImage, fc: int, start: int, address: int, count: int,
                  registers: list[int], values) -> ExcCodes | None:
    """Called by pymodbus on every request: serve reads from / apply writes to the device image."""
    table = img.input if fc == 4 else img.holding
    off = address - start
    if values is None:                                   # read
        registers[off:off + count] = table[off:off + count]
        return None
    values = list(values)
    if fc == 4 or not img.writable(address, len(values)):
        audit.warning("REJECTED write %s holding[%d..%d] (not writable)", img.name, address, address + len(values) - 1)
        return ExcCodes.ILLEGAL_ADDRESS
    table[off:off + len(values)] = values
    audit.info("WRITE %s fc=%d holding[%d..%d] = %s", img.name, fc, address, address + len(values) - 1, values)
    return None


def _sim_device(img: DeviceImage, unit_id: int) -> SimDevice:
    def block(size: int) -> list[SimData]:
        return [SimData(0, count=max(1, size), values=0, datatype=DataType.REGISTERS)]
    bits = [SimData(0, count=1, values=False, datatype=DataType.BITS)]
    return SimDevice(unit_id, simdata=(bits, bits, block(len(img.holding)), block(len(img.input))),
                     action=functools.partial(_action, img))


async def run(local: bool, speed: float, tick: float, seed: int | None) -> None:
    site = load_site(local=local)
    regmap = RegisterMap.load(CONFIG_DIR / "register_map.csv")
    model = SiteModel(regmap, site["devices"], site["site"], speed=speed, seed=seed)
    model.step(tick)

    endpoints: dict[tuple[str, int], list[SimDevice]] = {}
    for d in site["devices"]:
        endpoints.setdefault((d.host, d.port), []).append(_sim_device(model.images[d.name], d.unit_id))
    servers = []
    for (host, port), devs in endpoints.items():
        srv = ModbusTcpServer(devs, address=(host, port))
        servers.append(asyncio.create_task(srv.serve_forever()))
        names = [d.name for d in site["devices"] if (d.host, d.port) == (host, port)]
        log.info("Modbus TCP server %s:%d -> %s", host, port, ", ".join(names))

    log.info("simulation running: speed x%.0f, tick %.1fs", speed, tick)
    loop = asyncio.get_running_loop()
    last = loop.time()
    while True:
        await asyncio.sleep(tick)
        now = loop.time()
        model.step(now - last)
        last = now
        if any(t.done() for t in servers):
            for t in servers:
                if t.done() and t.exception():
                    raise t.exception()
            raise RuntimeError("a Modbus server stopped")


def main() -> None:
    ap = argparse.ArgumentParser(description="BESS field device simulator")
    ap.add_argument("--local", action="store_true", help="bind 127.0.0.1:5020+ instead of site IPs")
    ap.add_argument("--speed", type=float, default=float(os.environ.get("SIM_SPEED", 1)),
                    help="time acceleration (20 = one simulated minute every 3 s)")
    ap.add_argument("--tick", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    logging.getLogger("pymodbus").setLevel(logging.ERROR)
    asyncio.run(run(args.local, args.speed, args.tick, args.seed))


if __name__ == "__main__":
    main()

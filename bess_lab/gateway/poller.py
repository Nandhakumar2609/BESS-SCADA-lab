"""Modbus TCP poller: block reads, decoding, comms supervision, setpoint writes."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException

from ..config import Device
from ..regmap import FC_READ, RegisterMap

log = logging.getLogger("gateway.poller")


@dataclass
class DeviceResult:
    device: str
    profile: str
    ok: bool = False
    values: dict = field(default_factory=dict)
    latency_ms: float = 0.0
    error: str = ""
    requests: int = 0


class Endpoint:
    """One TCP connection, shared by all unit IDs behind the same IP:port."""

    def __init__(self, host: str, port: int, timeout: float, retries: int):
        self.host, self.port = host, port
        self.client = AsyncModbusTcpClient(host, port=port, timeout=timeout, retries=retries,
                                           reconnect_delay=1, reconnect_delay_max=10)
        self.lock = asyncio.Lock()   # Modbus TCP devices often handle one transaction at a time

    async def ensure(self) -> bool:
        if not self.client.connected:
            await self.client.connect()
        return self.client.connected

    def close(self) -> None:
        self.client.close()


class Poller:
    def __init__(self, devices: list[Device], regmap: RegisterMap, polling: dict):
        self.devices = devices
        self.map = regmap
        self.timeout = float(polling.get("timeout_s", 1.0))
        self.max_regs = int(polling.get("max_block_registers", 100))
        self.max_gap = int(polling.get("max_gap", 4))
        self.endpoints: dict[tuple[str, int], Endpoint] = {}
        for d in devices:
            key = (d.host, d.port)
            if key not in self.endpoints:
                self.endpoints[key] = Endpoint(d.host, d.port, self.timeout, int(polling.get("retries", 1)))
        # read plan per profile, computed once
        self.plans = {
            prof: {t: regmap.plan_blocks(prof, t, self.max_regs, self.max_gap) for t in ("input", "holding")}
            for prof in {d.profile for d in devices}
        }
        self.error_count = {d.name: 0 for d in devices}
        for prof, plan in self.plans.items():
            n_points = len(regmap.select(prof))
            n_req = sum(len(b) for b in plan.values())
            log.info("read plan %-6s: %2d points in %d requests", prof, n_points, n_req)

    def endpoint(self, d: Device) -> Endpoint:
        return self.endpoints[(d.host, d.port)]

    async def _read(self, ep: Endpoint, table: str, start: int, count: int, unit: int) -> list[int]:
        fn = ep.client.read_input_registers if table == "input" else ep.client.read_holding_registers
        rr = await asyncio.wait_for(fn(start, count=count, device_id=unit), timeout=self.timeout * 2)
        if rr.isError():
            code = getattr(rr, "exception_code", "?")
            raise ModbusException(f"exception code {code} reading {table}[{start}+{count}] fc={FC_READ[table]}")
        return list(rr.registers)

    async def poll_device(self, d: Device) -> DeviceResult:
        res = DeviceResult(d.name, d.profile)
        ep = self.endpoint(d)
        t0 = time.perf_counter()
        async with ep.lock:
            try:
                if not await ep.ensure():
                    raise ConnectionError(f"cannot connect to {d.host}:{d.port}")
                for table, blocks in self.plans[d.profile].items():
                    for start, count, points in blocks:
                        try:
                            regs = await self._read(ep, table, start, count, d.unit_id)
                            res.requests += 1
                            for p in points:
                                off = p.address - start
                                res.values[p.name] = p.decode(regs[off:off + p.count])
                        except ModbusException as exc:
                            if "exception code 2" not in str(exc):
                                raise
                            # device refuses the merged block (gap not readable): fall back to point reads
                            log.debug("%s: block read refused (%s), reading points individually", d.name, exc)
                            for p in points:
                                regs = await self._read(ep, table, p.address, p.count, d.unit_id)
                                res.requests += 1
                                res.values[p.name] = p.decode(regs)
                res.ok = True
            except (ModbusException, ConnectionError, asyncio.TimeoutError, OSError) as exc:
                res.error = f"{type(exc).__name__}: {exc}"
                self.error_count[d.name] += 1
                res.values = {}
        res.latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        return res

    async def poll_all(self) -> dict[str, DeviceResult]:
        results = await asyncio.gather(*(self.poll_device(d) for d in self.devices))
        return {r.device: r for r in results}

    async def write_point(self, device_name: str, point_name: str, value: float) -> bool:
        d = next(x for x in self.devices if x.name == device_name)
        p = self.map.get(d.profile, point_name)
        if p.table != "holding" or "W" not in p.access:
            raise ValueError(f"{device_name}.{point_name} is not writable")
        ep = self.endpoint(d)
        async with ep.lock:
            try:
                if not await ep.ensure():
                    return False
                regs = p.encode(value)
                if len(regs) == 1:
                    rr = await ep.client.write_register(p.address, regs[0], device_id=d.unit_id)
                else:
                    rr = await ep.client.write_registers(p.address, regs, device_id=d.unit_id)
                ok = not rr.isError()
            except (ModbusException, asyncio.TimeoutError, OSError) as exc:
                log.error("write %s.%s failed: %s", device_name, point_name, exc)
                return False
        log.info("WRITE %s.%s = %s -> %s", device_name, point_name, value, "OK" if ok else "REJECTED")
        return ok

    def close(self) -> None:
        for ep in self.endpoints.values():
            ep.close()

"""Minimal site controller: SoC-window cycling and supervised automatic fault reset.

This stands in for an EMS / power plant controller so the lab has realistic closed-loop
behaviour (gateway writes P setpoint -> PCS -> battery -> BMS -> back to the gateway).
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("gateway.dispatch")

PCS_FAULT_STATE = 4


class Dispatcher:
    def __init__(self, cfg: dict, poller, pcs: str = "pcs01", bms: str = "bms01"):
        self.enabled = bool(cfg.get("enabled", False))
        self.mode = cfg.get("mode", "cycle")
        self.power = float(cfg.get("power_kw", 500))
        self.soc_high = float(cfg.get("soc_high", 90))
        self.soc_low = float(cfg.get("soc_low", 20))
        self.poller, self.pcs, self.bms = poller, pcs, bms
        self.direction = None          # "charge" | "discharge"
        self.last_sp = None
        self.fault_since = None
        self.reset_times: list[float] = []
        self.max_resets_per_hour = 3
        self.reset_after_s = 30

    async def step(self, results: dict) -> None:
        if not self.enabled:
            return
        pcs, bms = results.get(self.pcs), results.get(self.bms)
        if not (pcs and bms and pcs.ok and bms.ok):
            return                     # never dispatch blind
        if int(pcs.values.get("control_mode", 0)) != 1:
            return                     # PCS in LOCAL: site operator has control
        await self._auto_reset(pcs.values)

        soc = bms.values["soc_pct"]
        if self.direction is None:
            self.direction = "charge" if soc < (self.soc_low + self.soc_high) / 2 else "discharge"
        if self.direction == "charge" and soc >= self.soc_high:
            self.direction = "discharge"
            log.info("SoC %.1f%% reached upper limit -> discharging", soc)
        elif self.direction == "discharge" and soc <= self.soc_low:
            self.direction = "charge"
            log.info("SoC %.1f%% reached lower limit -> charging", soc)
        sp = self.power if self.direction == "discharge" else -self.power
        if sp != self.last_sp or abs(pcs.values.get("p_setpoint_kw", sp) - sp) > 0.5:
            if await self.poller.write_point(self.pcs, "p_setpoint_kw", sp):
                self.last_sp = sp

    async def _auto_reset(self, v: dict) -> None:
        now = time.time()
        if int(v.get("state", 0)) != PCS_FAULT_STATE:
            self.fault_since = None
            return
        if self.fault_since is None:
            self.fault_since = now
        self.reset_times = [t for t in self.reset_times if now - t < 3600]
        if now - self.fault_since < self.reset_after_s:
            return
        if len(self.reset_times) >= self.max_resets_per_hour:
            if len(self.reset_times) == self.max_resets_per_hour:
                log.error("PCS auto-reset limit reached (%d/h): manual intervention required",
                          self.max_resets_per_hour)
                self.reset_times.append(now)   # log once
            return
        log.warning("PCS in FAULT for %ds (fault_word=0x%04x): sending fault reset",
                    now - self.fault_since, int(v.get("fault_word", 0)))
        await self.poller.write_point(self.pcs, "fault_reset", 1)
        self.reset_times.append(now)
        self.fault_since = now

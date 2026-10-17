"""Coupled physical model of a 1 MW / 2 MWh LFP battery site.

One model drives every simulated device so the numbers are consistent with each other:
PCS power -> DC current -> cell voltages and state of charge -> BMS power limits -> PCS clamp;
PCS losses -> container heat -> HVAC compressor -> auxiliary load -> POI meter.

Each device exposes its state through a "register image" built from register_map.csv,
exactly like device firmware would. Modbus writes land in the holding image and are
picked up on the next model step.
"""
from __future__ import annotations

import logging
import math
import random
import time

from ..regmap import RegisterMap

log = logging.getLogger("sim.model")

N_CELLS = 416                 # LFP cells in series (~1331 V nominal)
EFFICIENCY = 0.965            # PCS one-way efficiency
R_CELL = 5.5e-5               # effective cell resistance (ohm) incl. parallel strings
OCV_TABLE = [(0.00, 2.80), (0.05, 3.10), (0.10, 3.20), (0.20, 3.25), (0.30, 3.27), (0.50, 3.29),
             (0.70, 3.31), (0.80, 3.33), (0.90, 3.35), (0.95, 3.40), (1.00, 3.55)]
FREEZE_HEARTBEAT_BIT = 1 << 14


def ocv(soc: float) -> float:
    for (s0, v0), (s1, v1) in zip(OCV_TABLE, OCV_TABLE[1:]):
        if soc <= s1:
            return v0 + (v1 - v0) * (soc - s0) / (s1 - s0)
    return OCV_TABLE[-1][1]


def approach(value: float, target: float, dt: float, tau: float) -> float:
    """First-order lag."""
    return target + (value - target) * math.exp(-dt / tau)


class DeviceImage:
    """Register memory of one simulated device."""

    def __init__(self, name: str, profile: str, regmap: RegisterMap):
        self.name, self.profile, self.map = name, profile, regmap
        self.input = [0] * regmap.table_size(profile, "input")
        self.holding = [0] * regmap.table_size(profile, "holding")
        self.heartbeat = 0

    def set(self, point_name: str, value: float) -> None:
        p = self.map.get(self.profile, point_name)
        regs = p.encode(value)
        target = self.input if p.table == "input" else self.holding
        target[p.address:p.end] = regs

    def get(self, point_name: str) -> float:
        p = self.map.get(self.profile, point_name)
        src = self.input if p.table == "input" else self.holding
        return p.decode(src[p.address:p.end])

    def writable(self, address: int, count: int) -> bool:
        """True if [address, address+count) is fully covered by RW holding points."""
        covered = set()
        for p in self.map.select(self.profile, "holding"):
            if "W" in p.access:
                covered.update(range(p.address, p.end))
        return all(a in covered for a in range(address, address + count))


class SiteModel:
    def __init__(self, regmap: RegisterMap, devices: list, site: dict, speed: float = 1.0, seed: int | None = None):
        self.map = regmap
        self.speed = speed
        self.rng = random.Random(seed)
        self.rated_kw = float(site.get("rated_power_kw", 1000))
        self.capacity_kwh = float(site.get("capacity_kwh", 2000))
        self.images = {d.name: DeviceImage(d.name, d.profile, regmap) for d in devices}
        self.by_profile: dict[str, list[DeviceImage]] = {}
        for img in self.images.values():
            self.by_profile.setdefault(img.profile, []).append(img)
        self.sim_time = time.time()
        # --- physical state
        self.soc, self.soh = 0.55, 0.972
        self.p_ac = self.q_ac = 0.0
        self.igbt_t = 30.0
        self.container_t, self.cell_t_max, self.cell_t_min = 24.0, 26.0, 24.5
        self.humidity = 48.0
        self.compressor = False
        self.freq = 50.0
        self.insulation = 2600.0
        self.e_chg = 41250.0           # lifetime counters (kWh) so the site looks "in service"
        self.e_dis = 38910.0
        self.cycles_base = 19.0
        self.poi_imp = 18234.0
        self.poi_exp = 37120.0
        self.aux_imp = 6120.0
        self.pcs_faults = 0            # latched random faults
        self.hvac_faults = 0
        self.fault_rate_per_h = 0.04   # random PCS faults per simulated hour
        self._init_holding()

    # ------------------------------------------------------------------ setup
    def _first(self, profile: str) -> DeviceImage | None:
        lst = self.by_profile.get(profile)
        return lst[0] if lst else None

    def _init_holding(self) -> None:
        if pcs := self._first("pcs"):
            pcs.set("run_command", 1)
            pcs.set("control_mode", 1)
            pcs.set("p_setpoint_kw", 0)
        if bms := self._first("bms"):
            bms.set("contactor_command", 1)
        if hvac := self._first("hvac"):
            hvac.set("enable", 1)
            hvac.set("cooling_setpoint_c", 25.0)
            hvac.set("heating_setpoint_c", 12.0)

    # ------------------------------------------------------------------ helpers
    def ambient(self) -> float:
        hour = time.localtime(self.sim_time).tm_hour + time.localtime(self.sim_time).tm_min / 60
        return 14.0 + 6.0 * math.sin(2 * math.pi * (hour - 9) / 24)

    def bms_limits(self, max_cell_v: float, cell_t: float) -> tuple[float, float]:
        chg = self.rated_kw * min(1.0, max(0.0, (1.0 - self.soc) / 0.08))
        dis = self.rated_kw * min(1.0, max(0.0, (self.soc - 0.02) / 0.08))
        if max_cell_v > 3.58:
            chg = min(chg, 100.0)
        if cell_t > 40:
            derate = max(0.0, 1 - (cell_t - 40) / 15)
            chg, dis = chg * derate, dis * derate
        return chg, dis

    # ------------------------------------------------------------------ main step
    def step(self, real_dt: float) -> None:
        sim_dt = real_dt * self.speed
        self.sim_time += sim_dt
        n = max(1, math.ceil(sim_dt / 5.0))
        for _ in range(n):
            self._physics(sim_dt / n)
        self._heartbeats(real_dt)
        self._publish()

    def _physics(self, dt: float) -> None:
        pcs, bms, hvac = self._first("pcs"), self._first("bms"), self._first("hvac")
        dt_h = dt / 3600.0

        # ---- inputs written by SCADA
        run = int(pcs.get("run_command")) if pcs else 0
        p_sp = pcs.get("p_setpoint_kw") if pcs else 0.0
        q_sp = pcs.get("q_setpoint_kvar") if pcs else 0.0
        pcs_inject = int(pcs.get("test_fault_inject")) & 0xFF if pcs else 0
        bms_inject = int(bms.get("test_fault_inject")) & 0xFF if bms else 0
        hvac_inject = int(hvac.get("test_fault_inject")) & 0xFF if hvac else 0
        if pcs and int(pcs.get("fault_reset")) == 1:
            if self.pcs_faults:
                log.info("PCS fault reset by SCADA (cleared 0x%04x)", self.pcs_faults)
            self.pcs_faults = 0
            pcs.set("fault_reset", 0)

        # ---- grid
        self.freq += self.rng.gauss(0, 0.004) - (self.freq - 50.0) * 0.05
        self.freq = min(50.4, max(49.6, self.freq))
        v_ac = 690.0 * (1 + 0.008 * math.sin(self.sim_time / 900) + self.rng.gauss(0, 0.001))

        # ---- random PCS fault (Poisson)
        if pcs and self.rng.random() < self.fault_rate_per_h * dt_h:
            bit = self.rng.choice([0, 3, 5])
            self.pcs_faults |= 1 << bit
            log.warning("PCS random fault raised: bit %d", bit)

        # ---- BMS protection
        i_est = self.p_ac * 1000 / max(1.0, N_CELLS * ocv(self.soc))
        v_cell_avg = ocv(self.soc) - i_est * R_CELL
        spread = 0.008 + 0.035 * abs(self.soc - 0.5) ** 3 * 8 + abs(self.rng.gauss(0, 0.001))
        v_max, v_min = v_cell_avg + 0.6 * spread, v_cell_avg - 0.4 * spread
        bms_alarm = bms_inject
        if v_max > 3.65: bms_alarm |= 1 << 0
        if v_min < 2.75: bms_alarm |= 1 << 1
        if self.cell_t_max > 55: bms_alarm |= 1 << 2
        if spread > 0.10: bms_alarm |= 1 << 4
        if self.insulation < 300: bms_alarm |= 1 << 5
        trip = bms_alarm & 0b1010_0111  # OV, UV, OT, insulation, fire => open contactor
        contactor = bool(bms and int(bms.get("contactor_command")) == 1 and not trip)
        chg_lim, dis_lim = self.bms_limits(v_max, self.cell_t_max)

        # ---- PCS control
        self.pcs_faults |= pcs_inject          # PCS faults latch until SCADA writes fault_reset
        fault_word = self.pcs_faults
        warning = 0
        if fault_word:
            target = 0.0
            self.p_ac = 0.0  # trip: instant
        elif run != 1 or not contactor:
            target = 0.0
        else:
            target = max(-min(self.rated_kw, chg_lim), min(min(self.rated_kw, dis_lim), p_sp))
            if abs(target - p_sp) > 1:
                warning |= 1 << 2 | 1 << 0
        ramp = 200.0 * dt  # kW per simulated second
        self.p_ac += max(-ramp, min(ramp, target - self.p_ac))
        q_target = 0.0 if (fault_word or run != 1 or not contactor) else max(-300.0, min(300.0, q_sp))
        self.q_ac += max(-ramp, min(ramp, q_target - self.q_ac))
        if self.igbt_t > 70:
            warning |= 1 << 1

        # ---- DC side / battery
        p_dc = self.p_ac / EFFICIENCY if self.p_ac > 0 else self.p_ac * EFFICIENCY
        self.soc -= p_dc * dt_h / (self.capacity_kwh * self.soh)
        self.soc = min(1.0, max(0.0, self.soc))
        if self.p_ac > 0:
            self.e_dis += self.p_ac * dt_h
        else:
            self.e_chg += -self.p_ac * dt_h
        load = abs(self.p_ac) / self.rated_kw

        # ---- thermal
        amb = self.ambient()
        self.igbt_t = approach(self.igbt_t, self.container_t + 6 + 48 * load ** 1.5, dt, 120)
        self.cell_t_max = approach(self.cell_t_max, self.container_t + 2.0 + 11 * load ** 1.5, dt, 900)
        self.cell_t_min = approach(self.cell_t_min, self.container_t + 0.5 + 3 * load, dt, 900)
        enabled = bool(hvac and int(hvac.get("enable")) == 1)
        cool_sp = hvac.get("cooling_setpoint_c") if hvac else 25.0
        heat_sp = hvac.get("heating_setpoint_c") if hvac else 12.0
        if hvac and self.rng.random() < 0.01 * dt_h:
            self.hvac_faults |= 1 << 0
            log.warning("HVAC random compressor fault")
        hvac_fault = self.hvac_faults | hvac_inject
        if self.hvac_faults and self.rng.random() < 2.0 * dt_h:   # technician fixes it (~30 min)
            self.hvac_faults = 0
        compressor_ok = enabled and not (hvac_fault & 0b0111)
        if self.container_t > cool_sp + 1.0 and compressor_ok:
            self.compressor = True
        elif self.container_t < cool_sp - 1.0 or not compressor_ok:
            self.compressor = False
        heating = enabled and self.container_t < heat_sp
        heat_in = 0.035 * abs(self.p_ac) + 2.0 + 0.6 * (amb - self.container_t)   # kW thermal
        heat_in -= 45.0 if self.compressor else 0.0
        heat_in += 10.0 if heating else 0.0
        self.container_t += heat_in * dt / 9000.0                                # kJ/K
        self.humidity = approach(self.humidity, 40 if self.compressor else 55, dt, 1800)
        # insulation resistance: mean-reverting, lower in humid air
        self.insulation = approach(self.insulation, 2600 - 25 * max(0.0, self.humidity - 50), dt, 3600) + self.rng.gauss(0, 1.5)
        self.insulation = min(3000.0, max(200.0, self.insulation))
        hvac_kw = (1.5 if enabled else 0.0) + (14.0 if self.compressor else 0.0) + (10.0 if heating else 0.0)
        mode = 0 if not enabled else 1 if self.compressor else 2 if heating else 3

        # ---- meters
        aux_kw = hvac_kw + 6.0 + self.rng.gauss(0, 0.2)
        aux_kvar = aux_kw * 0.45
        trafo_loss = 2.0 + 0.008 * abs(self.p_ac)
        poi_kw = self.p_ac - aux_kw - trafo_loss
        poi_kvar = self.q_ac - aux_kvar
        if poi_kw > 0:
            self.poi_exp += poi_kw * dt_h
        else:
            self.poi_imp += -poi_kw * dt_h
        self.aux_imp += aux_kw * dt_h

        # ---- keep values for publishing
        self._v = dict(
            v_ac=v_ac, fault_word=fault_word, warning=warning, contactor=contactor, chg_lim=chg_lim,
            dis_lim=dis_lim, p_dc=p_dc, v_max=v_max, v_min=v_min, v_avg=v_cell_avg, bms_alarm=bms_alarm,
            run=run, hvac_fault=hvac_fault, mode=mode, hvac_kw=hvac_kw, amb=amb, aux_kw=aux_kw,
            aux_kvar=aux_kvar, poi_kw=poi_kw, poi_kvar=poi_kvar)

    def _heartbeats(self, real_dt: float) -> None:
        for img in self.images.values():
            try:
                frozen = int(img.get("test_fault_inject")) & FREEZE_HEARTBEAT_BIT
            except KeyError:
                frozen = 0
            if not frozen:
                img.heartbeat = (img.heartbeat + max(1, round(real_dt))) & 0xFFFF

    # ------------------------------------------------------------------ registers
    def _publish(self) -> None:
        v = self._v
        if pcs := self._first("pcs"):
            state = 4 if v["fault_word"] else 0 if (v["run"] != 1 or not v["contactor"]) else \
                1 if abs(self.p_ac) < 1 else 3 if self.p_ac > 0 else 2
            v_dc = N_CELLS * v["v_avg"]
            s_kva = math.hypot(self.p_ac, self.q_ac)
            for name, val in dict(
                heartbeat=pcs.heartbeat, state=state, fault_word=v["fault_word"], warning_word=v["warning"],
                active_power_kw=self.p_ac, reactive_power_kvar=self.q_ac, ac_voltage_v=v["v_ac"],
                ac_current_a=s_kva * 1000 / (math.sqrt(3) * v["v_ac"]), frequency_hz=self.freq,
                dc_voltage_v=v_dc, dc_current_a=v["p_dc"] * 1000 / v_dc, igbt_temp_c=self.igbt_t,
                available_charge_kw=min(self.rated_kw, v["chg_lim"]) if v["contactor"] else 0,
                available_discharge_kw=min(self.rated_kw, v["dis_lim"]) if v["contactor"] else 0,
                energy_charged_kwh=self.e_chg, energy_discharged_kwh=self.e_dis,
            ).items():
                pcs.set(name, val)
        if bms := self._first("bms"):
            i_pack = v["p_dc"] * 1000 / (N_CELLS * v["v_avg"])
            status = 4 if v["bms_alarm"] & 0b1010_0111 else 0 if not v["contactor"] else \
                1 if abs(i_pack) < 1 else 3 if i_pack > 0 else 2
            for name, val in dict(
                heartbeat=bms.heartbeat, status=status, alarm_word=v["bms_alarm"], soc_pct=self.soc * 100,
                soh_pct=self.soh * 100, pack_voltage_v=N_CELLS * v["v_avg"], pack_current_a=i_pack,
                max_cell_voltage_v=v["v_max"], min_cell_voltage_v=v["v_min"], max_cell_temp_c=self.cell_t_max,
                min_cell_temp_c=self.cell_t_min, max_charge_power_kw=v["chg_lim"],
                max_discharge_power_kw=v["dis_lim"], contactor_closed=int(v["contactor"]),
                cycle_count=self.cycles_base + self.e_dis / self.capacity_kwh, insulation_kohm=self.insulation,
            ).items():
                bms.set(name, val)
        if hvac := self._first("hvac"):
            for name, val in dict(
                heartbeat=hvac.heartbeat, mode=v["mode"], fault_word=v["hvac_fault"],
                container_temp_c=self.container_t, humidity_pct=self.humidity, ambient_temp_c=v["amb"],
                supply_air_temp_c=self.container_t - (11 if self.compressor else 0),
                compressor_on=int(self.compressor), power_kw=v["hvac_kw"],
            ).items():
                hvac.set(name, val)
        meters = self.by_profile.get("meter", [])
        for i, m in enumerate(meters):
            if i == 0:   # POI meter on MV side
                p, q, volt, imp, exp = v["poi_kw"], v["poi_kvar"], 20000.0, self.poi_imp, self.poi_exp
            else:        # auxiliary consumption meter (LV)
                p, q, volt, imp, exp = v["aux_kw"], v["aux_kvar"], 400.0, self.aux_imp, 0.0
            volt *= 1 + self.rng.gauss(0, 0.0015)
            s = math.hypot(p, q)
            for name, val in dict(
                p_total_kw=p, q_total_kvar=q, s_total_kva=s, power_factor=(abs(p) / s if s > 0.1 else 1.0),
                voltage_ll_v=volt, current_avg_a=s * 1000 / (math.sqrt(3) * volt), frequency_hz=self.freq,
                energy_import_kwh=imp, energy_export_kwh=exp, energy_check=exp - imp,
            ).items():
                m.set(name, val)

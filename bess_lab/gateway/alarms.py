"""Alarm engine: limits with deadband and on-delay, bitfields, comms loss, stale heartbeat.

Each alarm instance goes NORMAL -> PENDING (condition true, waiting for delay) -> ACTIVE,
and back to NORMAL once the value returns past setpoint +/- deadband. Every ACTIVE/NORMAL
transition is emitted as an event (for the historian alarm journal).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

log = logging.getLogger("gateway.alarms")
SEVERITY_RANK = {"critical": 1, "major": 2, "minor": 3, "warning": 4}


@dataclass
class AlarmDef:
    id: str
    device: str
    type: str
    severity: str
    message: str
    point: str | None = None
    setpoint: float | None = None
    deadband: float = 0.0
    delay_s: float = 0.0
    a: str | None = None
    b: str | None = None
    bit: int | None = None


@dataclass
class AlarmState:
    active: bool = False
    pending_since: float | None = None
    raised_at: float | None = None
    value: float | None = None


@dataclass
class AlarmEvent:
    ts: float
    alarm_id: str
    device: str
    severity: str
    state: str          # RAISED | CLEARED
    message: str
    value: float | None


class AlarmEngine:
    def __init__(self, cfg: dict, devices: list, regmap, stale_after_s: float = 10.0):
        defaults = cfg.get("defaults", {})
        self.defs: list[AlarmDef] = []
        self.stale_after = stale_after_s
        self.hb_last: dict[str, tuple[float, float]] = {}   # device -> (value, time it last changed)
        profiles = {d.name: d.profile for d in devices}
        for raw in cfg["alarms"]:
            raw = {**defaults, **raw}
            targets = list(profiles) if raw["device"] == "*" else [raw["device"]]
            only = raw.pop("only_profiles", None)
            bit_sev = raw.pop("bit_severity", {}) or {}
            for dev in targets:
                if dev not in profiles:
                    raise ValueError(f"alarm {raw['id']}: unknown device {dev}")
                if only and profiles[dev] not in only:
                    continue
                base = dict(raw, device=dev)
                if raw["type"] == "bitfield":
                    # expand into one alarm per named bit, names from the register map
                    for bit, name in regmap.get(profiles[dev], raw["point"]).bits.items():
                        self.defs.append(AlarmDef(**dict(base, id=f"{raw['id']}_{name}", bit=bit,
                                                         severity=bit_sev.get(name, raw["severity"]),
                                                         message=f"{raw['message']}: {name}")))
                else:
                    self.defs.append(AlarmDef(**base))
        self.state = {(d.device, d.id): AlarmState() for d in self.defs}
        log.info("alarm engine: %d alarm instances configured", len(self.defs))

    # ---------------------------------------------------------------- evaluation
    def _condition(self, d: AlarmDef, res, active: bool, now: float) -> tuple[bool | None, float | None]:
        """Return (condition, value). condition None = cannot evaluate (no data) -> hold state."""
        if d.type == "comms":
            return (not res.ok), None
        if not res.ok:
            return None, None
        v = res.values
        if d.type == "stale":
            hb = v.get(d.point)
            last = self.hb_last.get(d.device)
            if last is None or hb != last[0]:
                self.hb_last[d.device] = (hb, now)
                return False, hb
            return (now - last[1]) > self.stale_after, hb
        if d.type == "bitfield":
            word = int(v.get(d.point, 0))
            return bool(word >> d.bit & 1), float(word)
        if d.type == "spread":
            x = v[d.a] - v[d.b]
            limit = d.setpoint - (d.deadband if active else 0)
            return x > limit, round(x, 4)
        x = v.get(d.point)
        if x is None:
            return None, None
        if d.type == "high":
            return x > (d.setpoint - d.deadband if active else d.setpoint), x
        if d.type == "low":
            return x < (d.setpoint + d.deadband if active else d.setpoint), x
        raise ValueError(f"unknown alarm type {d.type}")

    def evaluate(self, results: dict, now: float | None = None) -> list[AlarmEvent]:
        now = time.time() if now is None else now
        events = []
        for d in self.defs:
            st = self.state[(d.device, d.id)]
            res = results.get(d.device)
            if res is None:
                continue
            # when a device is offline, only the comms alarm is evaluated; others hold their state
            cond, value = self._condition(d, res, st.active, now)
            if cond is None:
                continue
            st.value = value
            if cond and not st.active:
                if st.pending_since is None:
                    st.pending_since = now
                if now - st.pending_since >= d.delay_s:
                    st.active, st.raised_at = True, now
                    events.append(AlarmEvent(now, d.id, d.device, d.severity, "RAISED", d.message, value))
            elif not cond:
                st.pending_since = None
                if st.active:
                    st.active = False
                    events.append(AlarmEvent(now, d.id, d.device, d.severity, "CLEARED", d.message, value))
        for e in events:
            (log.warning if e.state == "RAISED" else log.info)(
                "ALARM %-7s %-8s %-10s %s (%s) value=%s", e.state, e.severity, e.device, e.alarm_id, e.message, e.value)
        return events

    def active(self) -> list[tuple[AlarmDef, AlarmState]]:
        items = [(d, self.state[(d.device, d.id)]) for d in self.defs if self.state[(d.device, d.id)].active]
        return sorted(items, key=lambda x: (SEVERITY_RANK.get(x[0].severity, 9), x[1].raised_at or 0))

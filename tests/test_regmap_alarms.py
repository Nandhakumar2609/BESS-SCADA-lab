from pathlib import Path

import pytest
import yaml

from bess_lab.config import CONFIG_DIR, Device, load_site
from bess_lab.gateway.alarms import AlarmEngine
from bess_lab.gateway.poller import DeviceResult
from bess_lab.regmap import Point, RegisterMap

MAP = RegisterMap.load(CONFIG_DIR / "register_map.csv")


def test_map_loads_and_validates():
    assert set(MAP.profiles()) == {"pcs", "bms", "hvac", "meter"}
    assert MAP.get("pcs", "p_setpoint_kw").reference == 40002
    assert MAP.get("bms", "soc_pct").reference == 30004
    assert MAP.get("pcs", "state").enum[4] == "FAULT"
    assert MAP.get("bms", "alarm_word").bits[4] == "CELL_IMBALANCE"


def test_overlap_detected():
    pts = [Point("x", "input", 0, "a", "float32", "ABCD", 1, "", "R", ""),
           Point("x", "input", 1, "b", "uint16", "AB", 1, "", "R", "")]
    with pytest.raises(ValueError, match="overlaps"):
        RegisterMap(pts)


def test_writable_input_rejected():
    with pytest.raises(ValueError, match="read-only"):
        RegisterMap([Point("x", "input", 0, "a", "uint16", "AB", 1, "", "RW", "")])


def test_block_planner_merges_and_splits():
    pts = [Point("x", "input", a, f"p{a}", "uint16", "AB", 1, "", "R", "") for a in (0, 1, 2, 10, 50)]
    m = RegisterMap(pts)
    blocks = m.plan_blocks("x", "input", max_regs=100, max_gap=8)
    assert [(s, c) for s, c, _ in blocks] == [(0, 11), (50, 1)]
    blocks = m.plan_blocks("x", "input", max_regs=5, max_gap=8)
    assert [(s, c) for s, c, _ in blocks] == [(0, 3), (10, 1), (50, 1)]


def test_local_endpoint_mapping_keeps_shared_meter_endpoint():
    devs = {d.name: d for d in load_site(local=True)["devices"]}
    assert devs["meter_poi"].port == devs["meter_aux"].port
    assert devs["meter_poi"].unit_id != devs["meter_aux"].unit_id
    assert len({d.port for d in devs.values()}) == 4


# ------------------------------------------------------------------ alarms
DEVICES = [Device("bms01", "bms", "h", 1, 1), Device("pcs01", "pcs", "h", 2, 1)]
CFG = {"defaults": {"delay_s": 0, "deadband": 0}, "alarms": [
    {"id": "SOC_LOW", "device": "bms01", "type": "low", "point": "soc_pct", "setpoint": 10, "deadband": 2,
     "delay_s": 5, "severity": "minor", "message": "low"},
    {"id": "COMMS", "device": "*", "type": "comms", "delay_s": 4, "severity": "critical", "message": "comms"},
    {"id": "PCS_FAULT", "device": "pcs01", "type": "bitfield", "point": "fault_word", "severity": "critical",
     "message": "f", "bit_severity": {"GRID_FREQUENCY": "major"}},
]}


def res(name, profile, ok=True, **values):
    return DeviceResult(name, profile, ok=ok, values=values)


def test_on_delay_and_deadband():
    eng = AlarmEngine(CFG, DEVICES, MAP)
    pcs = res("pcs01", "pcs", fault_word=0)
    assert eng.evaluate({"bms01": res("bms01", "bms", soc_pct=9), "pcs01": pcs}, now=0) == []
    ev = eng.evaluate({"bms01": res("bms01", "bms", soc_pct=9), "pcs01": pcs}, now=5)
    assert [(e.alarm_id, e.state) for e in ev] == [("SOC_LOW", "RAISED")]
    # inside the deadband (10..12): stays active
    assert eng.evaluate({"bms01": res("bms01", "bms", soc_pct=11), "pcs01": pcs}, now=6) == []
    ev = eng.evaluate({"bms01": res("bms01", "bms", soc_pct=12.5), "pcs01": pcs}, now=7)
    assert [(e.alarm_id, e.state) for e in ev] == [("SOC_LOW", "CLEARED")]


def test_transient_shorter_than_delay_is_filtered():
    eng = AlarmEngine(CFG, DEVICES, MAP)
    pcs = res("pcs01", "pcs", fault_word=0)
    eng.evaluate({"bms01": res("bms01", "bms", soc_pct=9), "pcs01": pcs}, now=0)
    eng.evaluate({"bms01": res("bms01", "bms", soc_pct=15), "pcs01": pcs}, now=3)
    assert eng.evaluate({"bms01": res("bms01", "bms", soc_pct=9), "pcs01": pcs}, now=6) == []


def test_bitfield_expansion_and_severity_override():
    eng = AlarmEngine(CFG, DEVICES, MAP)
    ev = eng.evaluate({"bms01": res("bms01", "bms", soc_pct=50),
                       "pcs01": res("pcs01", "pcs", fault_word=(1 << 0) | (1 << 3))}, now=0)
    got = {(e.alarm_id, e.severity) for e in ev}
    assert got == {("PCS_FAULT_IGBT_OVERTEMP", "critical"), ("PCS_FAULT_GRID_FREQUENCY", "major")}


def test_comms_loss_holds_other_alarms():
    eng = AlarmEngine(CFG, DEVICES, MAP)
    pcs = res("pcs01", "pcs", fault_word=0)
    eng.evaluate({"bms01": res("bms01", "bms", soc_pct=5), "pcs01": pcs}, now=0)
    eng.evaluate({"bms01": res("bms01", "bms", soc_pct=5), "pcs01": pcs}, now=10)
    down = res("bms01", "bms", ok=False)
    eng.evaluate({"bms01": down, "pcs01": pcs}, now=11)
    ev = eng.evaluate({"bms01": down, "pcs01": pcs}, now=16)
    assert [(e.alarm_id, e.state) for e in ev] == [("COMMS", "RAISED")]
    active = {d.id for d, _ in eng.active()}
    assert active == {"COMMS", "SOC_LOW"}     # SOC_LOW is held, not cleared, while data is missing


def test_shipped_alarm_config_is_valid():
    site = load_site()
    cfg = yaml.safe_load((CONFIG_DIR / "alarms.yaml").read_text())
    eng = AlarmEngine(cfg, site["devices"], MAP)
    assert len(eng.defs) > 30

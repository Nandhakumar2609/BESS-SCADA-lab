#!/usr/bin/env python3
"""Generate the Grafana dashboards (grafana/dashboards/*.json) from code.

Dashboards-as-code keeps them reviewable and part of the configuration baseline.
    python tools/build_dashboards.py
"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "grafana" / "dashboards"
DS = {"type": "influxdb", "uid": "bess-influx"}
BUCKET = "bess"
RANGE = 'range(start: v.timeRangeStart, stop: v.timeRangeStop)'


# ------------------------------------------------------------------ flux helpers
def tel(device: str, fields: dict[str, str], fn: str = "mean") -> list[dict]:
    """One query per field, renamed to a human label."""
    targets = []
    for i, (field, label) in enumerate(fields.items()):
        q = (f'from(bucket: "{BUCKET}")\n  |> {RANGE}\n'
             f'  |> filter(fn: (r) => r._measurement == "telemetry" and r.device == "{device}" and r._field == "{field}")\n'
             f'  |> aggregateWindow(every: v.windowPeriod, fn: {fn}, createEmpty: false)\n'
             f'  |> set(key: "_field", value: "{label}")\n'
             f'  |> keep(columns: ["_time", "_value", "_field"])')
        targets.append({"refId": chr(65 + i), "datasource": DS, "query": q})
    return targets


def last_value(measurement: str, field: str, device: str | None = None) -> list[dict]:
    dev = f' and r.device == "{device}"' if device else ""
    q = (f'from(bucket: "{BUCKET}")\n  |> range(start: -1m)\n'
         f'  |> filter(fn: (r) => r._measurement == "{measurement}"{dev} and r._field == "{field}")\n'
         f'  |> last()\n  |> keep(columns: ["_time", "_value"])')
    return [{"refId": "A", "datasource": DS, "query": q}]


def flux(q: str) -> list[dict]:
    return [{"refId": "A", "datasource": DS, "query": q}]


# ------------------------------------------------------------------ panel helpers
_id = 0


def panel(kind, title, targets, x, y, w, h, unit=None, decimals=None, mappings=None, thresholds=None,
          options=None, min_=None, max_=None, custom=None, overrides=None, description=None, display_name=None):
    global _id
    _id += 1
    defaults = {"mappings": mappings or [], "thresholds": thresholds or steps(("green", None))}
    if unit: defaults["unit"] = unit
    if decimals is not None: defaults["decimals"] = decimals
    if min_ is not None: defaults["min"] = min_
    if max_ is not None: defaults["max"] = max_
    if custom: defaults["custom"] = custom
    if display_name: defaults["displayName"] = display_name
    p = {"id": _id, "type": kind, "title": title, "datasource": DS, "targets": targets,
         "gridPos": {"x": x, "y": y, "w": w, "h": h},
         "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
         "options": options or {}}
    if description: p["description"] = description
    return p


def steps(*pairs):
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for c, v in pairs]}


def value_map(mapping: dict) -> list[dict]:
    return [{"type": "value", "options": {str(k): {"text": t, "color": c, "index": i}
                                          for i, (k, (t, c)) in enumerate(mapping.items())}}]


def row(title, y):
    global _id
    _id += 1
    return {"id": _id, "type": "row", "title": title, "collapsed": False, "panels": [],
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}}


STAT_OPTS = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
             "colorMode": "background", "graphMode": "none", "textMode": "value_and_name", "justifyMode": "center"}
TS_CUSTOM = {"drawStyle": "line", "lineWidth": 2, "fillOpacity": 8, "showPoints": "never", "spanNulls": True}
TS_OPTS = {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
           "tooltip": {"mode": "multi", "sort": "none"}}

PCS_STATE = {0: ("STOPPED", "text"), 1: ("STANDBY", "blue"), 2: ("CHARGING", "green"),
             3: ("DISCHARGING", "orange"), 4: ("FAULT", "red")}
ONLINE = {0: ("OFFLINE", "red"), 1: ("ONLINE", "green")}


def dashboard(uid, title, panels, tags, refresh="5s", time_from="now-1h"):
    return {"uid": uid, "title": title, "tags": tags, "timezone": "browser", "editable": False,
            "graphTooltip": 1, "refresh": refresh, "schemaVersion": 39, "version": 1,
            "time": {"from": time_from, "to": "now"},
            "timepicker": {"refresh_intervals": ["2s", "5s", "10s", "30s", "1m"]},
            "panels": panels, "templating": {"list": []}, "annotations": {"list": []},
            "links": [{"title": "Dashboards", "type": "dashboards", "tags": ["bess"], "asDropdown": True}]}


# ================================================================== overview
def overview():
    global _id
    _id = 0
    P = []
    P.append(row("Site status", 0))
    P.append(panel("gauge", "State of charge", last_value("telemetry", "soc_pct", "bms01"), 0, 1, 4, 7,
                   unit="percent", decimals=1, min_=0, max_=100,
                   thresholds=steps(("red", None), ("orange", 10), ("green", 20), ("orange", 90), ("red", 95)),
                   options={"reduceOptions": {"calcs": ["lastNotNull"], "values": False},
                            "showThresholdMarkers": True, "showThresholdLabels": False}))
    P.append(panel("stat", "PCS state", last_value("telemetry", "state", "pcs01"), 4, 1, 4, 3,
                   mappings=value_map(PCS_STATE), options={**STAT_OPTS, "textMode": "value"}))
    P.append(panel("stat", "Active power (PCS)", last_value("telemetry", "active_power_kw", "pcs01"), 4, 4, 4, 4,
                   unit="kwatt", decimals=0, options={**STAT_OPTS, "colorMode": "value", "textMode": "value"},
                   description="+ discharge / - charge"))
    q_avail = (f'from(bucket: "{BUCKET}")\n  |> {RANGE}\n'
               f'  |> filter(fn: (r) => r._measurement == "site" and r._field == "available")\n'
               f'  |> mean()\n  |> map(fn: (r) => ({{r with _value: r._value * 100.0}}))\n'
               f'  |> keep(columns: ["_value"])')
    P.append(panel("stat", "Availability (time range)", flux(q_avail), 8, 1, 4, 3, unit="percent", decimals=2,
                   thresholds=steps(("red", None), ("orange", 95), ("green", 98)),
                   options={**STAT_OPTS, "textMode": "value"},
                   description="Share of scans where PCS and BMS are online, not faulted and the DC contactor is closed"))
    q_alarms = (f'from(bucket: "{BUCKET}")\n  |> range(start: -1m)\n'
                f'  |> filter(fn: (r) => r._measurement == "site" and r._field =~ /^alarms_/)\n'
                f'  |> last()\n  |> keep(columns: ["_value", "_field"])')
    P.append(panel("stat", "Active alarms", flux(q_alarms), 8, 4, 4, 4,
                   thresholds=steps(("green", None), ("red", 1)), options={**STAT_OPTS, "textMode": "value_and_name"},
                   overrides=[{"matcher": {"id": "byName", "options": n},
                               "properties": [{"id": "displayName", "value": n.split("_")[1].title()}]}
                              for n in ("alarms_critical", "alarms_major", "alarms_minor", "alarms_warning")]))
    P.append(panel("stat", "State of health", last_value("telemetry", "soh_pct", "bms01"), 12, 1, 3, 3,
                   unit="percent", decimals=1, options={**STAT_OPTS, "colorMode": "none", "textMode": "value"}))
    P.append(panel("stat", "Equivalent cycles", last_value("telemetry", "cycle_count", "bms01"), 15, 1, 3, 3,
                   decimals=0, options={**STAT_OPTS, "colorMode": "none", "textMode": "value"}))
    q_energy = (f'from(bucket: "{BUCKET}")\n  |> {RANGE}\n'
                f'  |> filter(fn: (r) => r._measurement == "telemetry" and r.device == "pcs01" and '
                f'(r._field == "energy_charged_kwh" or r._field == "energy_discharged_kwh"))\n'
                f'  |> spread()\n  |> keep(columns: ["_value", "_field"])')
    P.append(panel("stat", "Energy in time range", flux(q_energy), 12, 4, 6, 4, unit="kwatth", decimals=0,
                   options={**STAT_OPTS, "colorMode": "none"},
                   overrides=[{"matcher": {"id": "byName", "options": "energy_charged_kwh"},
                               "properties": [{"id": "displayName", "value": "Charged"}]},
                              {"matcher": {"id": "byName", "options": "energy_discharged_kwh"},
                               "properties": [{"id": "displayName", "value": "Discharged"}]}]))
    q_comms = (f'from(bucket: "{BUCKET}")\n  |> range(start: -1m)\n'
               f'  |> filter(fn: (r) => r._measurement == "comms" and r._field == "ok")\n'
               f'  |> last()\n  |> keep(columns: ["_value", "device"])')
    P.append(panel("stat", "Device communications", flux(q_comms), 18, 1, 6, 7,
                   mappings=value_map(ONLINE), display_name="${__field.labels.device}",
                   thresholds=steps(("red", None), ("green", 1)),
                   options={**STAT_OPTS, "textMode": "value_and_name", "orientation": "horizontal"}))

    P.append(row("Power and energy", 8))
    P.append(panel("timeseries", "Power flow", tel("pcs01", {"active_power_kw": "PCS"}) +
                   [dict(t, refId=chr(66 + i)) for i, t in enumerate(
                       tel("meter_poi", {"p_total_kw": "POI (grid)"}) + tel("meter_aux", {"p_total_kw": "Auxiliary"}))],
                   0, 9, 12, 8, unit="kwatt", custom=TS_CUSTOM, options=TS_OPTS,
                   description="PCS: + discharge. POI: + export to grid. AUX: site consumption (HVAC, controls)."))
    P.append(panel("timeseries", "State of charge", tel("bms01", {"soc_pct": "SoC"}), 12, 9, 12, 8,
                   unit="percent", min_=0, max_=100, custom={**TS_CUSTOM, "fillOpacity": 20,
                                                             "thresholdsStyle": {"mode": "line+area"}},
                   thresholds=steps(("transparent", None), ("transparent", 10), ("transparent", 95)),
                   options=TS_OPTS))
    q_state = (f'from(bucket: "{BUCKET}")\n  |> {RANGE}\n'
               f'  |> filter(fn: (r) => r._measurement == "telemetry" and r.device == "pcs01" and r._field == "state")\n'
               f'  |> aggregateWindow(every: v.windowPeriod, fn: last, createEmpty: false)\n'
               f'  |> set(key: "_field", value: "PCS")\n  |> keep(columns: ["_time", "_value", "_field"])')
    P.append(panel("state-timeline", "PCS operating state", flux(q_state), 0, 17, 24, 4,
                   mappings=value_map(PCS_STATE),
                   options={"showValue": "never", "mergeValues": True, "rowHeight": 0.8,
                            "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True}}))

    P.append(row("Battery and thermal", 21))
    P.append(panel("timeseries", "Cell voltages", tel("bms01", {"max_cell_voltage_v": "Max cell",
                                                                  "min_cell_voltage_v": "Min cell"}),
                   0, 22, 8, 8, unit="volt", decimals=3, custom=TS_CUSTOM, options=TS_OPTS))
    P.append(panel("timeseries", "Temperatures", tel("bms01", {"max_cell_temp_c": "Cell max", "min_cell_temp_c": "Cell min"}) +
                   [dict(t, refId=chr(67 + i)) for i, t in enumerate(
                       tel("pcs01", {"igbt_temp_c": "PCS IGBT"}) +
                       tel("hvac01", {"container_temp_c": "Container", "ambient_temp_c": "Ambient"}))],
                   8, 22, 8, 8, unit="celsius", custom=TS_CUSTOM, options=TS_OPTS))
    P.append(panel("timeseries", "HVAC", tel("hvac01", {"power_kw": "HVAC power"}) +
                   [dict(t, refId=chr(66 + i)) for i, t in enumerate(tel("hvac01", {"humidity_pct": "Humidity %"}))],
                   16, 22, 8, 8, unit="kwatt", custom=TS_CUSTOM, options=TS_OPTS,
                   overrides=[{"matcher": {"id": "byName", "options": "Humidity %"},
                               "properties": [{"id": "unit", "value": "percent"},
                                              {"id": "custom.axisPlacement", "value": "right"}]}]))
    P.append(panel("timeseries", "DC pack", tel("bms01", {"pack_voltage_v": "Pack voltage"}) +
                   [dict(t, refId=chr(66 + i)) for i, t in enumerate(tel("bms01", {"pack_current_a": "Pack current"}))],
                   0, 30, 12, 7, unit="volt", custom=TS_CUSTOM, options=TS_OPTS,
                   overrides=[{"matcher": {"id": "byName", "options": "Pack current"},
                               "properties": [{"id": "unit", "value": "amp"},
                                              {"id": "custom.axisPlacement", "value": "right"}]}]))
    P.append(panel("timeseries", "Grid frequency", tel("pcs01", {"frequency_hz": "Frequency"}),
                   12, 30, 12, 7, unit="hertz", decimals=3, custom=TS_CUSTOM, options=TS_OPTS))
    return dashboard("bess-overview", "BESS Site Overview", P, ["bess", "overview"])


# ================================================================== alarms & comms
def alarms():
    global _id
    _id = 0
    P = []
    q_active = (f'from(bucket: "{BUCKET}")\n  |> range(start: -6s)\n'
                f'  |> filter(fn: (r) => r._measurement == "alarm_active")\n  |> last()\n'
                f'  |> group(columns: ["device", "alarm_id", "severity"])\n'
                f'  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")\n  |> group()\n'
                f'  |> keep(columns: ["severity", "device", "alarm_id", "message", "value", "since_s"])')
    sev_colors = {"critical": "red", "major": "orange", "minor": "yellow", "warning": "blue"}
    sev_map = [{"type": "value", "options": {k: {"color": c, "index": i, "text": k.upper()}
                                             for i, (k, c) in enumerate(sev_colors.items())}}]
    table_opts = {"showHeader": True, "cellHeight": "sm", "footer": {"show": False}}
    sev_override = {"matcher": {"id": "byName", "options": "severity"},
                    "properties": [{"id": "mappings", "value": sev_map},
                                   {"id": "custom.cellOptions", "value": {"type": "color-background"}},
                                   {"id": "custom.width", "value": 110}]}
    P.append(panel("table", "Active alarms (live)", flux(q_active), 0, 0, 24, 8, options=table_opts,
                   overrides=[sev_override, {"matcher": {"id": "byName", "options": "since_s"},
                                             "properties": [{"id": "unit", "value": "s"},
                                                            {"id": "displayName", "value": "active for"}]}],
                   description="Snapshot written by the gateway alarm engine every scan"))
    q_journal = (f'from(bucket: "{BUCKET}")\n  |> {RANGE}\n'
                 f'  |> filter(fn: (r) => r._measurement == "alarm_event")\n'
                 f'  |> group(columns: ["device", "alarm_id", "severity", "state"])\n'
                 f'  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")\n  |> group()\n'
                 f'  |> sort(columns: ["_time"], desc: true)\n'
                 f'  |> keep(columns: ["_time", "state", "severity", "device", "alarm_id", "message", "value"])')
    state_override = {"matcher": {"id": "byName", "options": "state"},
                      "properties": [{"id": "mappings", "value": [{"type": "value", "options": {
                          "RAISED": {"color": "red", "index": 0}, "CLEARED": {"color": "green", "index": 1}}}]},
                                     {"id": "custom.cellOptions", "value": {"type": "color-text"}},
                                     {"id": "custom.width", "value": 100}]}
    P.append(panel("table", "Alarm journal (sequence of events)", flux(q_journal), 0, 8, 24, 10,
                   options=table_opts, overrides=[sev_override, state_override]))
    q_counts = (f'from(bucket: "{BUCKET}")\n  |> {RANGE}\n'
                f'  |> filter(fn: (r) => r._measurement == "alarm_event" and r._field == "active" and r.state == "RAISED")\n'
                f'  |> group(columns: ["alarm_id"])\n  |> count()\n  |> group()\n'
                f'  |> sort(columns: ["_value"], desc: true)\n  |> limit(n: 10)')
    P.append(panel("bargauge", "Top 10 alarms (bad actors)", flux(q_counts), 0, 18, 8, 9,
                   display_name="${__field.labels.alarm_id}", thresholds=steps(("blue", None)),
                   options={"orientation": "horizontal", "displayMode": "basic", "showUnfilled": True,
                            "reduceOptions": {"calcs": ["lastNotNull"], "values": True}}))
    q_lat = (f'from(bucket: "{BUCKET}")\n  |> {RANGE}\n'
             f'  |> filter(fn: (r) => r._measurement == "comms" and r._field == "latency_ms")\n'
             f'  |> aggregateWindow(every: v.windowPeriod, fn: max, createEmpty: false)\n'
             f'  |> keep(columns: ["_time", "_value", "device"])')
    P.append(panel("timeseries", "Modbus poll latency per device", flux(q_lat), 8, 18, 8, 9, unit="ms",
                   display_name="${__field.labels.device}", custom=TS_CUSTOM, options=TS_OPTS))
    q_ok = (f'from(bucket: "{BUCKET}")\n  |> {RANGE}\n'
            f'  |> filter(fn: (r) => r._measurement == "comms" and r._field == "ok")\n'
            f'  |> aggregateWindow(every: v.windowPeriod, fn: min, createEmpty: false)\n'
            f'  |> keep(columns: ["_time", "_value", "device"])')
    P.append(panel("state-timeline", "Communication status", flux(q_ok), 16, 18, 8, 9,
                   display_name="${__field.labels.device}", mappings=value_map(ONLINE),
                   options={"showValue": "never", "mergeValues": True, "rowHeight": 0.8,
                            "legend": {"showLegend": False}}))
    q_scan = (f'from(bucket: "{BUCKET}")\n  |> {RANGE}\n'
              f'  |> filter(fn: (r) => r._measurement == "site" and r._field == "scan_ms")\n'
              f'  |> aggregateWindow(every: v.windowPeriod, fn: max, createEmpty: false)\n'
              f'  |> set(key: "_field", value: "Scan time")\n  |> keep(columns: ["_time", "_value", "_field"])')
    P.append(panel("timeseries", "Gateway scan time", flux(q_scan), 0, 27, 12, 7, unit="ms", custom=TS_CUSTOM,
                   options=TS_OPTS))
    q_err = (f'from(bucket: "{BUCKET}")\n  |> {RANGE}\n'
             f'  |> filter(fn: (r) => r._measurement == "comms" and r._field == "errors_total")\n'
             f'  |> last()\n  |> keep(columns: ["_value", "device"])')
    P.append(panel("stat", "Communication errors (since gateway start)", flux(q_err), 12, 27, 12, 7,
                   display_name="${__field.labels.device}", thresholds=steps(("green", None), ("orange", 1)),
                   options={**STAT_OPTS, "colorMode": "value", "orientation": "horizontal"}))
    return dashboard("bess-alarms", "BESS Alarms & Communications", P, ["bess", "alarms"])


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, d in (("bess-overview.json", overview()), ("bess-alarms.json", alarms())):
        (OUT / name).write_text(json.dumps(d, indent=2) + "\n")
        print(f"wrote {OUT / name} ({len(d['panels'])} panels)")

#!/usr/bin/env python3
"""Render a Grafana-style dashboard preview PNG (docs/img/dashboard-preview.png) and a compact
JSON data set from a gateway capture (`--sink jsonl:capture.jsonl`). Used for the README and the
project showcase page when no live Grafana is at hand.

    python -m bess_lab.sim.server --local --speed 60 &
    python -m bess_lab.gateway.main --local --sink jsonl:capture.jsonl
    python tools/render_preview.py capture.jsonl
"""
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def parse(path):
    series = defaultdict(list)       # (measurement, device, field) -> [(t, v)]
    events = []
    for raw in open(path):
        ln = json.loads(raw)["lp"]
        # "measurement,tags fields timestamp" (tag values in this lab contain no spaces)
        head, rest = ln.split(" ", 1)
        fstr, ts = rest.rsplit(" ", 1)
        meas, *tags = head.split(",")
        tags = dict(t.split("=", 1) for t in tags)
        t = int(ts) / 1e9
        vals, buf, q = {}, "", False
        for ch in fstr + ",":
            if ch == '"':
                q = not q
            if ch == "," and not q:
                k, v = buf.split("=", 1)
                vals[k] = v
                buf = ""
            else:
                buf += ch
        if meas == "alarm_event":
            events.append({"t": t, "device": tags["device"], "id": tags["alarm_id"], "severity": tags["severity"],
                           "state": tags["state"], "message": vals.get("message", "").strip('"')})
            continue
        for k, v in vals.items():
            if v.startswith('"'):
                continue
            series[(meas, tags.get("device", ""), k)].append((t, float(v.rstrip("i"))))
    return series, events


BG, PANEL, GRID, TXT, MUTED = "#111217", "#181b1f", "#2a2d33", "#d8d9da", "#8e8e8e"
C = {"green": "#73bf69", "yellow": "#fade2a", "orange": "#ff9830", "red": "#f2495c", "blue": "#5794f2",
     "purple": "#b877d9", "cyan": "#8ab8ff"}


def style(ax, title):
    ax.set_facecolor(PANEL)
    for s in ax.spines.values():
        s.set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.grid(color=GRID, linewidth=0.6)
    ax.set_title(title, color=TXT, loc="left", fontsize=10, pad=6)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))


def main(path):
    s, events = parse(path)
    get = lambda m, d, f: ([datetime.fromtimestamp(t) for t, _ in s[(m, d, f)]], [v for _, v in s[(m, d, f)]])
    fig = plt.figure(figsize=(16, 9), facecolor=BG)
    gs = fig.add_gridspec(3, 4, height_ratios=[0.8, 1.25, 1.25], hspace=0.45, wspace=0.22,
                          left=0.04, right=0.985, top=0.9, bottom=0.06)
    fig.text(0.04, 0.95, "BESS Site Overview", color=TXT, fontsize=16, weight="bold")
    fig.text(0.04, 0.925, "BESS Lab Site 01 - 1 MW / 2 MWh   |   data from the running simulator + gateway (x60 speed)",
             color=MUTED, fontsize=9)

    # --- stat row
    soc_t, soc = get("telemetry", "bms01", "soc_pct")
    _, avail = get("site", "", "available")
    _, p = get("telemetry", "pcs01", "active_power_kw")
    _, soh = get("telemetry", "bms01", "soh_pct")
    stats = [("State of charge", f"{soc[-1]:.1f} %", C["green"]),
             ("Availability", f"{100 * sum(avail) / len(avail):.2f} %", C["green"] if sum(avail) / len(avail) > .98 else C["orange"]),
             ("PCS active power", f"{p[-1]:+.0f} kW", C["blue"]),
             ("Alarm events", f"{sum(1 for e in events if e['state'] == 'RAISED')} raised", C["orange"])]
    for i, (title, val, col) in enumerate(stats):
        ax = fig.add_subplot(gs[0, i]); ax.set_facecolor(col); ax.set_xticks([]); ax.set_yticks([])
        for sp in ax.spines.values(): sp.set_visible(False)
        ax.text(0.04, 0.82, title, color="#111", fontsize=10, transform=ax.transAxes, weight="bold")
        ax.text(0.5, 0.35, val, color="#111", fontsize=26, weight="bold", ha="center", transform=ax.transAxes)

    ax = fig.add_subplot(gs[1, :2]); style(ax, "Power flow (kW)  - PCS: + discharge, POI: + export")
    for (d, f, lab, col) in [("pcs01", "active_power_kw", "PCS", C["blue"]), ("meter_poi", "p_total_kw", "POI (grid)", C["green"]),
                             ("meter_aux", "p_total_kw", "Auxiliary", C["orange"])]:
        t, v = get("telemetry", d, f); ax.plot(t, v, color=col, lw=1.6, label=lab)
    ax.legend(facecolor=PANEL, edgecolor=GRID, labelcolor=TXT, fontsize=8, loc="lower left")

    ax = fig.add_subplot(gs[1, 2:]); style(ax, "State of charge (%)")
    ax.fill_between(soc_t, soc, color=C["green"], alpha=0.18); ax.plot(soc_t, soc, color=C["green"], lw=1.8)
    ax.axhline(90, color=C["orange"], ls="--", lw=0.8); ax.axhline(20, color=C["orange"], ls="--", lw=0.8)
    ax.set_ylim(0, 100)

    ax = fig.add_subplot(gs[2, :2]); style(ax, "Temperatures (°C)")
    for (d, f, lab, col) in [("bms01", "max_cell_temp_c", "Cell max", C["red"]), ("pcs01", "igbt_temp_c", "PCS IGBT", C["purple"]),
                             ("hvac01", "container_temp_c", "Container", C["cyan"]), ("hvac01", "ambient_temp_c", "Ambient", MUTED)]:
        t, v = get("telemetry", d, f); ax.plot(t, v, color=col, lw=1.4, label=lab)
    ax.legend(facecolor=PANEL, edgecolor=GRID, labelcolor=TXT, fontsize=8, loc="upper left", ncol=4)

    ax = fig.add_subplot(gs[2, 2:]); style(ax, "Alarm journal")
    ax.axis("off")
    rows = sorted(events, key=lambda e: e["t"], reverse=True)[:8]
    ax.text(0.0, 0.95, "time        state     severity   alarm", color=MUTED, family="monospace", fontsize=8.5,
            transform=ax.transAxes)
    for i, e in enumerate(rows):
        col = C["red"] if e["state"] == "RAISED" else C["green"]
        ax.text(0.0, 0.84 - i * 0.105, f"{datetime.fromtimestamp(e['t']):%H:%M:%S}  {e['state']:<8}  {e['severity']:<9}  {e['id']}",
                color=col, family="monospace", fontsize=8.5, transform=ax.transAxes)

    out = ROOT / "docs/img/dashboard-preview.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=110, facecolor=BG)
    print(f"wrote {out}")

    # compact data set for the showcase page
    keep = {"soc": ("telemetry", "bms01", "soc_pct"), "p_pcs": ("telemetry", "pcs01", "active_power_kw"),
            "p_poi": ("telemetry", "meter_poi", "p_total_kw"), "p_aux": ("telemetry", "meter_aux", "p_total_kw"),
            "t_cell": ("telemetry", "bms01", "max_cell_temp_c"), "t_cont": ("telemetry", "hvac01", "container_temp_c"),
            "t_igbt": ("telemetry", "pcs01", "igbt_temp_c"), "t_amb": ("telemetry", "hvac01", "ambient_temp_c"),
            "v_max": ("telemetry", "bms01", "max_cell_voltage_v"), "v_min": ("telemetry", "bms01", "min_cell_voltage_v"),
            "state": ("telemetry", "pcs01", "state"), "avail": ("site", "", "available"),
            "lat_pcs": ("comms", "pcs01", "latency_ms"), "scan": ("site", "", "scan_ms")}
    t0 = s[keep["soc"]][0][0]
    data = {"t": [round(t - t0, 1) for t, _ in s[keep["soc"]]],
            **{k: [round(v, 3) for _, v in s[key]] for k, key in keep.items()},
            "events": [dict(e, t=round(e["t"] - t0, 1)) for e in events]}
    (ROOT / "docs/img/capture.json").write_text(json.dumps(data))
    print("wrote docs/img/capture.json", len(data["t"]), "samples")


if __name__ == "__main__":
    main(sys.argv[1])

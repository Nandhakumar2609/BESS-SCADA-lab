"""SCADA gateway: poll field devices -> alarms -> dispatch -> historian.

    python -m bess_lab.gateway.main                  # Docker / lab network, writes to InfluxDB
    python -m bess_lab.gateway.main --local --sink stdout
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import time

from ..config import CONFIG_DIR, load_site, load_yaml
from ..regmap import RegisterMap
from .alarms import AlarmEngine
from .dispatch import Dispatcher
from .poller import Poller
from .sinks import InfluxSink, JsonlSink, StdoutSink, line

log = logging.getLogger("gateway")


def read_secret(name: str) -> str:
    """VAR or VAR_FILE (Docker-secrets style: the token never appears in the environment)."""
    path = os.environ.get(f"{name}_FILE")
    if path and os.path.exists(path):
        return open(path).read().strip()
    return os.environ.get(name, "")


def build_lines(site_id: str, results: dict, alarms: AlarmEngine, events: list, poller: Poller,
                ts: float, cycle_ms: float) -> list[str]:
    ns = int(ts * 1e9)
    out = []
    for r in results.values():
        tags = {"site": site_id, "device": r.device, "profile": r.profile}
        if r.ok and r.values:
            out.append(line("telemetry", tags, {k: float(v) for k, v in r.values.items()}, ns))
        out.append(line("comms", tags, {"ok": int(r.ok), "latency_ms": float(r.latency_ms),
                                        "requests": r.requests, "errors_total": poller.error_count[r.device]}, ns))

    # site-level KPIs
    pcs, bms = results.get("pcs01"), results.get("bms01")
    available = int(bool(
        pcs and bms and pcs.ok and bms.ok and pcs.values.get("state") != 4 and bms.values.get("status") != 4
        and bms.values.get("contactor_closed") == 1))
    active = alarms.active()
    counts = {s: sum(1 for d, _ in active if d.severity == s) for s in ("critical", "major", "minor", "warning")}
    out.append(line("site", {"site": site_id}, {
        "available": available,
        "soc_pct": bms.values.get("soc_pct") if bms and bms.ok else None,
        "pcs_power_kw": pcs.values.get("active_power_kw") if pcs and pcs.ok else None,
        "poi_power_kw": results["meter_poi"].values.get("p_total_kw") if results.get("meter_poi", None) and results["meter_poi"].ok else None,
        "alarms_critical": counts["critical"], "alarms_major": counts["major"],
        "alarms_minor": counts["minor"], "alarms_warning": counts["warning"],
        "scan_ms": float(round(cycle_ms, 1)),
    }, ns))

    # snapshot of active alarms (for "current alarms" panels) and the event journal
    for d, st in active:
        out.append(line("alarm_active", {"site": site_id, "device": d.device, "alarm_id": d.id, "severity": d.severity},
                        {"active": 1, "message": d.message,
                         "value": float(st.value) if st.value is not None else None,
                         "since_s": float(round(ts - (st.raised_at or ts), 1))}, ns))
    for e in events:
        out.append(line("alarm_event", {"site": site_id, "device": e.device, "alarm_id": e.alarm_id,
                                        "severity": e.severity, "state": e.state},
                        {"active": int(e.state == "RAISED"), "message": e.message,
                         "value": float(e.value) if e.value is not None else None}, int(e.ts * 1e9)))
    return out


async def run(args) -> None:
    site = load_site(local=args.local)
    regmap = RegisterMap.load(CONFIG_DIR / "register_map.csv")
    polling = site["polling"]
    poller = Poller(site["devices"], regmap, polling)
    alarms = AlarmEngine(load_yaml("alarms.yaml"), site["devices"], regmap,
                         stale_after_s=float(polling.get("stale_heartbeat_s", 10)))
    dispatch = Dispatcher(site.get("dispatch", {}), poller)
    if args.no_dispatch:
        dispatch.enabled = False

    if args.sink == "influx":
        h = site["historian"]
        sink = InfluxSink(os.environ.get("INFLUX_URL", h["url"]), os.environ.get("INFLUX_ORG", h["org"]),
                          os.environ.get("INFLUX_BUCKET", h["bucket"]), read_secret("INFLUX_TOKEN"))
    elif args.sink.startswith("jsonl:"):
        sink = JsonlSink(args.sink.split(":", 1)[1])
    else:
        sink = StdoutSink()

    interval = float(polling.get("interval_s", 2.0))
    site_id = site["site"]["id"]
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    log.info("gateway started: %d devices, scan %.1fs, dispatch %s, sink %s",
             len(site["devices"]), interval, "ON" if dispatch.enabled else "OFF", args.sink)

    cycles = 0
    next_t = loop.time()
    while not stop.is_set():
        t0 = time.perf_counter()
        ts = time.time()
        results = await poller.poll_all()
        events = alarms.evaluate(results, ts)
        await dispatch.step(results)
        cycle_ms = (time.perf_counter() - t0) * 1000
        await sink.write(build_lines(site_id, results, alarms, events, poller, ts, cycle_ms))
        cycles += 1
        if cycles % 30 == 1:
            summary = " ".join(f"{n}={'OK' if r.ok else 'DOWN'}" for n, r in results.items())
            log.info("scan %d: %s | %.0f ms | %d active alarms", cycles, summary, cycle_ms, len(alarms.active()))
        if args.cycles and cycles >= args.cycles:
            break
        next_t += interval
        try:
            await asyncio.wait_for(stop.wait(), timeout=max(0.0, next_t - loop.time()))
        except asyncio.TimeoutError:
            pass
        if loop.time() - next_t > interval:     # overrun: resynchronise instead of bursting
            log.warning("scan overrun, resynchronising")
            next_t = loop.time()
    poller.close()
    log.info("gateway stopped after %d scans", cycles)


def main() -> None:
    ap = argparse.ArgumentParser(description="BESS SCADA gateway")
    ap.add_argument("--local", action="store_true", help="talk to a simulator started with --local")
    ap.add_argument("--sink", default=os.environ.get("GATEWAY_SINK", "influx"),
                    help="influx | stdout | jsonl:/path/file.jsonl")
    ap.add_argument("--no-dispatch", action="store_true")
    ap.add_argument("--cycles", type=int, default=0, help="stop after N scans (0 = run forever)")
    args = ap.parse_args()
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    logging.getLogger("pymodbus").setLevel(logging.CRITICAL)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()

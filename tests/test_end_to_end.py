"""Simulator + gateway + historian (mock InfluxDB) + FAT runner, all on localhost."""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from bess_lab.gateway.sinks import InfluxSink, line

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable


def test_line_protocol_escaping():
    ln = line("alarm_event", {"device": "pcs 01", "alarm_id": "A,B"}, {"message": 'say "hi"', "active": 1,
                                                                       "value": 1.5, "skip": None}, 123)
    assert ln == 'alarm_event,alarm_id=A\\,B,device=pcs\\ 01 message="say \\"hi\\"",active=1i,value=1.5 123'


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    procs = [
        subprocess.Popen([PY, "lab/mock_influx.py", "--port", "18086", "--token", "t0k"], cwd=ROOT, env=env),
        subprocess.Popen([PY, "-m", "bess_lab.sim.server", "--local", "--speed", "30", "--seed", "1"], cwd=ROOT, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
    ]
    time.sleep(2)
    gw = subprocess.Popen([PY, "-m", "bess_lab.gateway.main", "--local", "--sink", "influx"], cwd=ROOT,
                          env=dict(env, INFLUX_URL="http://127.0.0.1:18086", INFLUX_TOKEN="t0k"),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    procs.append(gw)
    time.sleep(7)
    yield procs
    for p in procs:
        p.terminate()
    for p in procs:
        p.wait(timeout=10)


def stats():
    return json.loads(urllib.request.urlopen("http://127.0.0.1:18086/stats").read())


def test_gateway_writes_to_historian(stack):
    s = stats()
    assert s["lines"]["telemetry"] >= 5 * 2        # 5 devices, at least 2 scans
    assert s["lines"]["comms"] >= 5 * 2
    assert s["lines"]["site"] >= 2
    assert s["rejected"] == 0


def test_store_and_forward(stack):
    import asyncio
    sink = InfluxSink("http://127.0.0.1:1", "o", "b", "t")    # nothing listens on port 1
    asyncio.run(sink.write(["m f=1i 1", "m f=2i 2"]))
    assert len(sink.buffer) == 2 and not sink.online
    sink.endpoint = "http://127.0.0.1:18086/api/v2/write?org=o&bucket=b"
    sink.token = "t0k"
    asyncio.run(sink.write(["m f=3i 3"]))
    assert len(sink.buffer) == 0 and sink.online


def test_fat_passes(stack, tmp_path):
    r = subprocess.run([PY, "-m", "bess_lab.fat", "--local", "--out", str(tmp_path)], cwd=ROOT,
                       env=dict(os.environ, PYTHONPATH=str(ROOT)), capture_output=True, text=True, timeout=120)
    print(r.stdout)
    assert r.returncode == 0, r.stdout
    report = next(tmp_path.glob("FAT_report_*.md")).read_text()
    assert "0 failed" in report
    # the alarm raised by the FAT must have reached the historian journal
    assert stats()["lines"].get("alarm_event", 0) >= 2

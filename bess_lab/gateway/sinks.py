"""Historian writers. InfluxDB 2.x via the HTTP line-protocol API, with store-and-forward."""
from __future__ import annotations

import asyncio
import collections
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("gateway.sink")


def _esc_tag(v) -> str:
    return str(v).replace("\\", "\\\\").replace(",", "\\,").replace("=", "\\=").replace(" ", "\\ ")


def _field(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return f"{v}i"
    if isinstance(v, float):
        return repr(v)
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def line(measurement: str, tags: dict, fields: dict, ts_ns: int) -> str:
    tag_str = "".join(f",{_esc_tag(k)}={_esc_tag(v)}" for k, v in sorted(tags.items()) if v not in (None, ""))
    field_str = ",".join(f"{_esc_tag(k)}={_field(v)}" for k, v in fields.items() if v is not None)
    return f"{_esc_tag(measurement)}{tag_str} {field_str} {ts_ns}"


class InfluxSink:
    """Writes batches; if the historian is unreachable, keeps up to max_buffer lines and
    flushes them (with their original timestamps) when it comes back."""

    def __init__(self, url: str, org: str, bucket: str, token: str, max_buffer: int = 200_000):
        q = urllib.parse.urlencode({"org": org, "bucket": bucket, "precision": "ns"})
        self.endpoint = f"{url.rstrip('/')}/api/v2/write?{q}"
        self.token = token
        self.buffer: collections.deque[str] = collections.deque(maxlen=max_buffer)
        self.online = True

    def _post(self, body: bytes) -> None:
        req = urllib.request.Request(self.endpoint, data=body, method="POST", headers={
            "Authorization": f"Token {self.token}", "Content-Type": "text/plain; charset=utf-8"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status not in (200, 204):
                raise urllib.error.HTTPError(self.endpoint, resp.status, "write failed", resp.headers, None)

    async def write(self, lines: list[str]) -> None:
        self.buffer.extend(lines)
        while self.buffer:
            batch = [self.buffer[i] for i in range(min(5000, len(self.buffer)))]
            try:
                await asyncio.to_thread(self._post, "\n".join(batch).encode())
            except (urllib.error.URLError, OSError) as exc:
                if self.online:
                    log.error("historian unreachable (%s) - buffering", exc)
                self.online = False
                if len(self.buffer) == self.buffer.maxlen:
                    log.warning("store-and-forward buffer full, oldest data is being dropped")
                return
            for _ in batch:
                self.buffer.popleft()
            if not self.online:
                log.info("historian back online - backlog flushed")
                self.online = True


class JsonlSink:
    def __init__(self, path: str):
        self.path = path

    async def write(self, lines: list[str]) -> None:
        with open(self.path, "a") as fh:
            for ln in lines:
                fh.write(json.dumps({"lp": ln}) + "\n")


class StdoutSink:
    async def write(self, lines: list[str]) -> None:
        for ln in lines:
            print(ln)

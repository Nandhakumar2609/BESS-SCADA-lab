#!/usr/bin/env python3
"""Tiny stand-in for the InfluxDB 2 write API, for the namespace network lab and tests.

POST /api/v2/write   counts line-protocol lines per measurement, records client IPs
GET  /ping           204
GET  /stats          JSON summary
"""
import argparse
import collections
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATS = {"lines": collections.Counter(), "clients": collections.Counter(), "rejected": 0, "sample": []}


class Handler(BaseHTTPRequestHandler):
    token = ""

    def log_message(self, *args):
        pass

    def _send(self, code, body=b"", ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/ping"):
            return self._send(204)
        if self.path.startswith("/stats"):
            return self._send(200, json.dumps({"lines": STATS["lines"], "clients": STATS["clients"],
                                               "rejected": STATS["rejected"], "sample": STATS["sample"][-5:]}).encode())
        self._send(404)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
        if not self.path.startswith("/api/v2/write"):
            return self._send(404)
        if self.headers.get("Authorization") != f"Token {self.token}":
            STATS["rejected"] += 1
            return self._send(401, b'{"code":"unauthorized"}')
        STATS["clients"][self.client_address[0]] += 1
        for ln in filter(None, body.splitlines()):
            STATS["lines"][ln.split(",", 1)[0].split(" ", 1)[0]] += 1
            STATS["sample"].append(ln[:160])
        STATS["sample"] = STATS["sample"][-20:]
        self._send(204)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8086)
    ap.add_argument("--token", default="labtoken")
    a = ap.parse_args()
    Handler.token = a.token
    ThreadingHTTPServer((a.bind, a.port), Handler).serve_forever()

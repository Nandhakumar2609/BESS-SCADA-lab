#!/usr/bin/env python3
"""TCP probe: prints OPEN (connected), CLOSED (RST = reachable, nothing listening) or
FILTERED (no answer = dropped by a firewall).   probe.py HOST PORT [--src IP]"""
import argparse
import socket
import sys

ap = argparse.ArgumentParser()
ap.add_argument("host")
ap.add_argument("port", type=int)
ap.add_argument("--src")
ap.add_argument("--timeout", type=float, default=1.5)
a = ap.parse_args()
s = socket.socket()
s.settimeout(a.timeout)
if a.src:
    s.bind((a.src, 0))
try:
    s.connect((a.host, a.port))
    print("OPEN")
except ConnectionRefusedError:
    print("CLOSED")
except (socket.timeout, TimeoutError):
    print("FILTERED")
except OSError as e:
    print(f"UNREACHABLE ({e.strerror})")
finally:
    s.close()
sys.exit(0)

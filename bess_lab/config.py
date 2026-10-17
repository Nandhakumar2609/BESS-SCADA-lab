"""Load site.yaml and resolve file locations."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

CONFIG_DIR = Path(os.environ.get("BESS_CONFIG_DIR", Path(__file__).resolve().parent.parent / "config"))


@dataclass
class Device:
    name: str
    profile: str
    host: str
    port: int
    unit_id: int


def load_site(path: str | Path | None = None, local: bool = False, base_port: int = 5020) -> dict:
    """Return the site config dict with cfg['devices'] as a list of Device.

    local=True rewrites every Modbus endpoint to 127.0.0.1 with one port per distinct
    endpoint (5020, 5021, ...). Simulator and gateway apply the same rule, so they can
    run on a laptop without the Docker networks.
    """
    path = Path(path) if path else CONFIG_DIR / "site.yaml"
    cfg = yaml.safe_load(path.read_text())
    devices = [Device(**d) for d in cfg["devices"]]
    if local:
        endpoints: dict[tuple[str, int], int] = {}
        for d in devices:
            endpoints.setdefault((d.host, d.port), base_port + len(endpoints))
            d.host, d.port = "127.0.0.1", endpoints[(d.host, d.port)]
    cfg["devices"] = devices
    return cfg


def load_yaml(name: str) -> dict:
    return yaml.safe_load((CONFIG_DIR / name).read_text())

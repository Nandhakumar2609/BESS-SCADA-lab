"""Protocol mapping table (register_map.csv) loader, validator and read-block planner."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from . import codec

TABLES = ("input", "holding")
FC_READ = {"input": 4, "holding": 3}
REF_BASE = {"input": 30001, "holding": 40001}  # classic "Modicon" reference numbers


@dataclass(frozen=True)
class Point:
    profile: str
    table: str
    address: int
    name: str
    data_type: str
    byte_order: str
    scale: float
    unit: str
    access: str
    description: str
    enum: dict = field(default_factory=dict, hash=False, compare=False)
    bits: dict = field(default_factory=dict, hash=False, compare=False)

    @property
    def count(self) -> int:
        return codec.register_count(self.data_type)

    @property
    def end(self) -> int:  # exclusive
        return self.address + self.count

    @property
    def reference(self) -> int:
        return REF_BASE[self.table] + self.address

    def encode(self, value: float) -> list[int]:
        return codec.encode(value, self.data_type, self.byte_order, self.scale)

    def decode(self, regs: list[int]) -> float:
        return codec.decode(regs, self.data_type, self.byte_order, self.scale)


def _parse_enum(text: str) -> tuple[dict, dict]:
    """'0=STOP;1=RUN' -> ({0:'STOP',1:'RUN'}, {}) ; 'b0=X;b1=Y' -> ({}, {0:'X',1:'Y'})"""
    enum, bits = {}, {}
    for item in filter(None, (t.strip() for t in (text or "").split(";"))):
        key, _, label = item.partition("=")
        if key.startswith("b"):
            bits[int(key[1:])] = label.strip()
        else:
            enum[int(key)] = label.strip()
    return enum, bits


class RegisterMap:
    def __init__(self, points: list[Point]):
        self.points = points
        self.validate()

    @classmethod
    def load(cls, path: str | Path) -> "RegisterMap":
        points = []
        with open(path, newline="") as fh:
            for lineno, row in enumerate(csv.DictReader(fh), start=2):
                try:
                    enum, bits = _parse_enum(row.get("enum", ""))
                    points.append(Point(
                        profile=row["profile"].strip(), table=row["table"].strip(),
                        address=int(row["address"]), name=row["name"].strip(),
                        data_type=row["data_type"].strip(), byte_order=row["byte_order"].strip(),
                        scale=float(row["scale"] or 1), unit=row.get("unit", "").strip(),
                        access=row["access"].strip(), description=row.get("description", "").strip(),
                        enum=enum, bits=bits))
                except (KeyError, ValueError) as exc:
                    raise ValueError(f"{path}:{lineno}: {exc}") from exc
        return cls(points)

    def validate(self) -> None:
        seen_names, errors = set(), []
        for p in self.points:
            if p.table not in TABLES:
                errors.append(f"{p.profile}.{p.name}: unknown table {p.table}")
            try:
                codec.check_order(p.data_type, p.byte_order)
            except codec.CodecError as exc:
                errors.append(f"{p.profile}.{p.name}: {exc}")
            if p.table == "input" and "W" in p.access:
                errors.append(f"{p.profile}.{p.name}: input registers are read-only")
            if (p.profile, p.name) in seen_names:
                errors.append(f"{p.profile}.{p.name}: duplicate name")
            seen_names.add((p.profile, p.name))
        for prof in self.profiles():
            for table in TABLES:
                pts = sorted(self.select(prof, table), key=lambda x: x.address)
                for a, b in zip(pts, pts[1:]):
                    if b.address < a.end:
                        errors.append(f"{prof}/{table}: {a.name}@{a.address} overlaps {b.name}@{b.address}")
        if errors:
            raise ValueError("register map invalid:\n  " + "\n  ".join(errors))

    def profiles(self) -> list[str]:
        return sorted({p.profile for p in self.points})

    def select(self, profile: str, table: str | None = None) -> list[Point]:
        return [p for p in self.points if p.profile == profile and (table is None or p.table == table)]

    def get(self, profile: str, name: str) -> Point:
        for p in self.points:
            if p.profile == profile and p.name == name:
                return p
        raise KeyError(f"{profile}.{name}")

    def table_size(self, profile: str, table: str) -> int:
        pts = self.select(profile, table)
        return max((p.end for p in pts), default=0)

    def plan_blocks(self, profile: str, table: str, max_regs: int = 100, max_gap: int = 4):
        """Group points into as few read requests as possible.

        Points closer than max_gap registers are merged into one request, as long as the
        request stays below max_regs. Fewer requests = faster scan and less load on devices.
        Returns a list of (start, count, [points]).
        """
        blocks = []
        for p in sorted(self.select(profile, table), key=lambda x: x.address):
            if blocks:
                start, count, pts = blocks[-1]
                if p.address - (start + count) <= max_gap and p.end - start <= max_regs:
                    blocks[-1] = (start, max(count, p.end - start), pts + [p])
                    continue
            blocks.append((p.address, p.count, [p]))
        return blocks

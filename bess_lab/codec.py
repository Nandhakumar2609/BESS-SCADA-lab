"""Modbus register codec.

Modbus only defines 16-bit registers. Everything else (int32, float32, scaling,
byte/word order) is a vendor convention, and getting it wrong is the most common
commissioning bug. This module makes those conventions explicit.

Byte-order notation (A = most significant byte of the value):
    16-bit:  AB  big-endian (Modbus default)      BA  byte-swapped
    32-bit:  ABCD big-endian                      CDAB word-swapped ("little-endian word order")
             BADC byte-swapped inside each word   DCBA fully little-endian
"""
from __future__ import annotations

import math
import struct

SIZES = {"uint16": 1, "int16": 1, "uint32": 2, "int32": 2, "float32": 2}
_STRUCT = {"uint16": ">H", "int16": ">h", "uint32": ">I", "int32": ">i", "float32": ">f"}
_VALID_ORDERS = {1: {"AB", "BA"}, 2: {"ABCD", "CDAB", "BADC", "DCBA"}}


class CodecError(ValueError):
    pass


def register_count(data_type: str) -> int:
    try:
        return SIZES[data_type]
    except KeyError:
        raise CodecError(f"unsupported data type {data_type!r}") from None


def check_order(data_type: str, byte_order: str) -> None:
    if byte_order not in _VALID_ORDERS[register_count(data_type)]:
        raise CodecError(f"byte order {byte_order!r} invalid for {data_type}")


def _reorder(raw: bytes, byte_order: str) -> bytes:
    """Map between canonical big-endian bytes (A,B,C,D) and wire order. The mapping is
    its own inverse for all supported orders, so it is used for encode and decode."""
    if byte_order in ("AB", "ABCD"):
        return raw
    if byte_order == "BA":
        return raw[::-1]
    a, b, c, d = raw
    return {"CDAB": bytes((c, d, a, b)), "BADC": bytes((b, a, d, c)), "DCBA": bytes((d, c, b, a))}[byte_order]


def encode(value: float, data_type: str, byte_order: str = "ABCD", scale: float = 1.0) -> list[int]:
    """Engineering value -> list of 16-bit register values as seen on the wire."""
    check_order(data_type, byte_order)
    if data_type == "float32":
        raw_value = float(value) / scale
        packed = struct.pack(">f", raw_value)
    else:
        raw_value = round(float(value) / scale)
        fmt = _STRUCT[data_type]
        bits = 16 * register_count(data_type)
        lo, hi = (-(1 << (bits - 1)), (1 << (bits - 1)) - 1) if data_type.startswith("int") else (0, (1 << bits) - 1)
        raw_value = max(lo, min(hi, raw_value))  # saturate like a real device would
        packed = struct.pack(fmt, raw_value)
    wire = _reorder(packed, byte_order)
    return [int.from_bytes(wire[i:i + 2], "big") for i in range(0, len(wire), 2)]


def decode(registers: list[int], data_type: str, byte_order: str = "ABCD", scale: float = 1.0) -> float:
    """List of 16-bit registers (wire order) -> engineering value."""
    check_order(data_type, byte_order)
    n = register_count(data_type)
    if len(registers) != n:
        raise CodecError(f"{data_type} needs {n} registers, got {len(registers)}")
    wire = b"".join(int(r & 0xFFFF).to_bytes(2, "big") for r in registers)
    raw_value = struct.unpack(_STRUCT[data_type], _reorder(wire, byte_order))[0]
    if data_type == "float32" and not math.isfinite(raw_value):
        raise CodecError("non-finite float (NaN/Inf) - check byte order")
    value = raw_value * scale
    # trim float noise from scaling (e.g. 0.1 * 3 = 0.30000000000000004)
    return round(value, 6) if isinstance(value, float) else value

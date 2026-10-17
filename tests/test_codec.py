import math

import pytest

from bess_lab import codec


@pytest.mark.parametrize("order,expected", [
    # 123.456f = 0x42F6E979 -> bytes A=42 B=F6 C=E9 D=79
    ("ABCD", [0x42F6, 0xE979]),
    ("CDAB", [0xE979, 0x42F6]),
    ("BADC", [0xF642, 0x79E9]),
    ("DCBA", [0x79E9, 0xF642]),
])
def test_float32_known_vectors(order, expected):
    assert codec.encode(123.456, "float32", order) == expected
    assert math.isclose(codec.decode(expected, "float32", order), 123.456, rel_tol=1e-6)


@pytest.mark.parametrize("dtype,order", [(t, o) for t in ("uint32", "int32", "float32")
                                         for o in ("ABCD", "CDAB", "BADC", "DCBA")] +
                         [(t, o) for t in ("uint16", "int16") for o in ("AB", "BA")])
@pytest.mark.parametrize("value,scale", [(0, 1), (1234.5, 0.1), (42, 1), (3.141, 0.001)])
def test_roundtrip(dtype, order, value, scale):
    if dtype.startswith("uint") or value >= 0:
        regs = codec.encode(value, dtype, order, scale)
        assert len(regs) == codec.register_count(dtype)
        assert all(0 <= r <= 0xFFFF for r in regs)
        got = codec.decode(regs, dtype, order, scale)
        tol = 1e-4 * max(1, abs(value)) if dtype == "float32" else scale / 2 + 1e-9
        assert abs(got - value) <= tol


def test_negative_int32_word_swapped():
    # -500.0 kW with scale 0.1 -> raw -5000 = 0xFFFFEC78; CDAB puts the low word first
    assert codec.encode(-500, "int32", "CDAB", 0.1) == [0xEC78, 0xFFFF]
    assert codec.decode([0xEC78, 0xFFFF], "int32", "CDAB", 0.1) == -500.0


def test_saturation_like_a_device():
    assert codec.encode(70000, "uint16", "AB") == [0xFFFF]
    assert codec.encode(-5, "uint16", "AB") == [0]
    assert codec.decode(codec.encode(-40000, "int16", "AB"), "int16", "AB") == -32768


def test_wrong_byte_order_is_obvious():
    regs = codec.encode(1331.2, "float32", "ABCD")
    wrong = codec.decode(regs, "float32", "CDAB")
    assert abs(wrong - 1331.2) > 1000   # word swap gives garbage, which the FAT cross-checks catch


def test_invalid_order_rejected():
    with pytest.raises(codec.CodecError):
        codec.encode(1, "uint16", "ABCD")
    with pytest.raises(codec.CodecError):
        codec.decode([1], "float32", "ABCD")

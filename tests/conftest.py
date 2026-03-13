from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jpeg_fault.core.models import EntropyRange


@pytest.fixture
def tiny_jpeg_bytes() -> bytes:
    # SOI
    data = bytearray([0xFF, 0xD8])

    # APP0 (len=16, payload=14) JFIF\0 + standard fields
    app0_payload = bytes([
        0x4A, 0x46, 0x49, 0x46, 0x00,
        0x01, 0x02,
        0x01,
        0x00, 0x48,
        0x00, 0x48,
        0x00, 0x00,
    ])
    data.extend([0xFF, 0xE0, 0x00, 0x10])
    data.extend(app0_payload)

    # SOS (len=8, payload=6): Ns=1, component/table selectors + Ss/Se/AhAl
    data.extend([0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01, 0x00, 0x00, 0x3F, 0x00])

    # Entropy bytes containing stuffed FF00 and restart marker FFD0
    data.extend([0x01, 0x02, 0xFF, 0x00, 0x03, 0xFF, 0xD0, 0x04, 0x05])

    # EOI
    data.extend([0xFF, 0xD9])
    return bytes(data)


@pytest.fixture
def tiny_jpeg_path(tmp_path: Path, tiny_jpeg_bytes: bytes) -> Path:
    p = tmp_path / "tiny.jpg"
    p.write_bytes(tiny_jpeg_bytes)
    return p


@pytest.fixture
def simple_entropy_ranges() -> list[EntropyRange]:
    return [EntropyRange(2, 8, 0)]

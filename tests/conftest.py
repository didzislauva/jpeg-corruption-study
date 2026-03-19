from __future__ import annotations

"""
Shared pytest fixtures for JPEG fault tolerance tests.

These fixtures provide small in-memory JPEGs and entropy ranges to keep tests
fast and deterministic.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jpeg_fault.core.models import EntropyRange


@pytest.fixture
def tiny_jpeg_bytes() -> bytes:
    """
    Return a minimal JPEG byte sequence with one SOS and a short entropy stream.
    """
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
    """
    Write tiny_jpeg_bytes to a temp path and return the file path.
    """
    p = tmp_path / "tiny.jpg"
    p.write_bytes(tiny_jpeg_bytes)
    return p


@pytest.fixture
def rich_jpeg_bytes() -> bytes:
    """
    Return a synthetic JPEG with APP0, DQT, SOF0, DHT, DRI, SOS, and EOI.
    """
    data = bytearray([0xFF, 0xD8])

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

    dqt_payload = bytes([0x00] + list(range(1, 65)))
    data.extend([0xFF, 0xDB, 0x00, 0x43])
    data.extend(dqt_payload)

    sof0_payload = bytes([
        0x08,
        0x00, 0x08,
        0x00, 0x08,
        0x03,
        0x01, 0x22, 0x00,
        0x02, 0x11, 0x00,
        0x03, 0x11, 0x00,
    ])
    data.extend([0xFF, 0xC0, 0x00, 0x11])
    data.extend(sof0_payload)

    dht_payload = bytes(
        [0x00] + [0, 1] + [0] * 14 + [0x00] +
        [0x10] + [0, 2] + [0] * 14 + [0x00, 0xF0]
    )
    data.extend([0xFF, 0xC4, 0x00, 0x27])
    data.extend(dht_payload)

    data.extend([0xFF, 0xDD, 0x00, 0x04, 0x00, 0x04])

    sos_payload = bytes([
        0x03,
        0x01, 0x00,
        0x02, 0x10,
        0x03, 0x10,
        0x00, 0x3F, 0x00,
    ])
    data.extend([0xFF, 0xDA, 0x00, 0x0C])
    data.extend(sos_payload)
    data.extend([0x11, 0x22, 0xFF, 0xD0, 0x33, 0x44, 0x55])
    data.extend([0xFF, 0xD9])
    return bytes(data)


@pytest.fixture
def rich_jpeg_path(tmp_path: Path, rich_jpeg_bytes: bytes) -> Path:
    """
    Write rich_jpeg_bytes to a temp path and return the file path.
    """
    p = tmp_path / "rich.jpg"
    p.write_bytes(rich_jpeg_bytes)
    return p


@pytest.fixture
def decodable_jpeg_bytes() -> bytes:
    """
    Return a tiny baseline JPEG whose entropy stream decodes to one all-zero block.
    """
    data = bytearray([0xFF, 0xD8])

    dqt_payload = bytes([0x00] + [1] * 64)
    data.extend([0xFF, 0xDB, 0x00, 0x43])
    data.extend(dqt_payload)

    sof0_payload = bytes([
        0x08,
        0x00, 0x08,
        0x00, 0x08,
        0x01,
        0x01, 0x11, 0x00,
    ])
    data.extend([0xFF, 0xC0, 0x00, 0x0B])
    data.extend(sof0_payload)

    dht_payload = bytes(
        [0x00] + [1] + [0] * 15 + [0x00] +
        [0x10] + [1] + [0] * 15 + [0x00]
    )
    data.extend([0xFF, 0xC4, 0x00, 0x26])
    data.extend(dht_payload)

    sos_payload = bytes([
        0x01,
        0x01, 0x00,
        0x00, 0x3F, 0x00,
    ])
    data.extend([0xFF, 0xDA, 0x00, 0x08])
    data.extend(sos_payload)
    data.extend([0x00])
    data.extend([0xFF, 0xD9])
    return bytes(data)


@pytest.fixture
def decodable_jpeg_path(tmp_path: Path, decodable_jpeg_bytes: bytes) -> Path:
    p = tmp_path / "traceable.jpg"
    p.write_bytes(decodable_jpeg_bytes)
    return p


@pytest.fixture
def progressive_like_jpeg_bytes(decodable_jpeg_bytes: bytes) -> bytes:
    """
    Return a tiny JPEG-like byte stream that uses SOF2 to exercise unsupported progressive handling.
    """
    data = bytearray(decodable_jpeg_bytes)
    sof_index = data.index(bytes([0xFF, 0xC0]))
    data[sof_index + 1] = 0xC2
    return bytes(data)


@pytest.fixture
def simple_entropy_ranges() -> list[EntropyRange]:
    """
    Return a simple entropy range list for unit tests.
    """
    return [EntropyRange(2, 8, 0)]


@pytest.fixture
def dsc04780_jpeg_bytes() -> bytes:
    """
    Return the repo JPEG that uses restart markers and non-default component ids.
    """
    return (ROOT / "DSC04780.jpg").read_bytes()

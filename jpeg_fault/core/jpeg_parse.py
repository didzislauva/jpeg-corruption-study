"""
JPEG parsing utilities for segment discovery and entropy range detection.

This module provides:
- Segment parsing with marker names and payload bounds.
- Entropy-coded stream range extraction (after SOS).
- Lightweight decoding of common segment payloads for reporting.
"""

from typing import Dict, List, Optional, Tuple

from .models import EntropyRange, Segment

MARKER_NAMES = {
    0xD8: "SOI",
    0xD9: "EOI",
    0xC0: "SOF0",
    0xC1: "SOF1",
    0xC2: "SOF2",
    0xC3: "SOF3",
    0xC5: "SOF5",
    0xC6: "SOF6",
    0xC7: "SOF7",
    0xC9: "SOF9",
    0xCA: "SOF10",
    0xCB: "SOF11",
    0xCD: "SOF13",
    0xCE: "SOF14",
    0xCF: "SOF15",
    0xC4: "DHT",
    0xDB: "DQT",
    0xDD: "DRI",
    0xDA: "SOS",
    0xFE: "COM",
}

for i in range(16):
    MARKER_NAMES[0xE0 + i] = f"APP{i}"

NO_LENGTH_MARKERS = {0xD8, 0xD9}


def read_u16(be: bytes) -> int:
    """
    Read a big-endian 16-bit integer from a 2-byte slice.
    """
    return (be[0] << 8) | be[1]


def marker_name(marker: int) -> str:
    """
    Convert a marker byte to a friendly name if known, else hex string.
    """
    return MARKER_NAMES.get(marker, f"0xFF{marker:02X}")


def format_bytes(data: bytes, start: int, count: int) -> str:
    """
    Format a slice of bytes into a space-separated hex string.
    """
    end = min(len(data), start + count)
    return " ".join(f"{b:02X}" for b in data[start:end])


def next_marker_offset(data: bytes, start: int) -> int:
    """
    Scan forward for the next real marker, skipping stuffed bytes and restart markers.

    Returns the offset of the 0xFF marker byte, or len(data) if none is found.
    """
    j = start
    while j + 1 < len(data):
        if data[j] == 0xFF:
            nxt = data[j + 1]
            if nxt == 0x00:
                j += 2
                continue
            if 0xD0 <= nxt <= 0xD7:
                j += 2
                continue
            return j
        j += 1
    return len(data)


def parse_segment(data: bytes, i: int) -> Tuple[Segment, int, Optional[EntropyRange]]:
    """
    Parse a single JPEG segment starting at offset `i`.

    Returns:
    - Segment object
    - next offset to continue parsing
    - optional EntropyRange if the segment is SOS
    """
    if data[i] != 0xFF:
        raise ValueError(f"Expected marker at offset {i}, found 0x{data[i]:02X}")

    while i < len(data) and data[i] == 0xFF:
        i += 1
    if i >= len(data):
        raise ValueError("Unexpected end while reading marker")

    marker = data[i]
    marker_offset = i - 1
    i += 1

    if marker in NO_LENGTH_MARKERS:
        seg = Segment(marker, marker_offset, marker_name(marker), None, None, None, 2)
        return seg, i, None

    if i + 1 >= len(data):
        raise ValueError(f"Truncated length at offset {i}")

    seg_len = read_u16(data[i:i + 2])
    if seg_len < 2:
        raise ValueError(f"Invalid segment length {seg_len} at offset {i}")

    payload_offset = i + 2
    payload_length = seg_len - 2
    total_length = 2 + 2 + payload_length
    seg = Segment(marker, marker_offset, marker_name(marker), seg_len, payload_offset, payload_length, total_length)

    if marker == 0xDA:
        entropy_start = payload_offset + payload_length
        entropy_end = next_marker_offset(data, entropy_start)
        ent = EntropyRange(entropy_start, entropy_end, 0)
        return seg, entropy_end, ent

    return seg, marker_offset + total_length, None


def parse_jpeg(data: bytes) -> Tuple[List[Segment], List[EntropyRange]]:
    """
    Parse a JPEG byte stream into segments and entropy-coded ranges.

    Returns:
    - list of Segment objects in file order
    - list of EntropyRange objects for each scan
    """
    if len(data) < 2 or data[0] != 0xFF or data[1] != 0xD8:
        raise ValueError("Not a JPEG (missing SOI)")

    segments: List[Segment] = []
    entropy_ranges: List[EntropyRange] = []

    i = 0
    scan_index = 0
    while i < len(data):
        seg, next_i, ent = parse_segment(data, i)
        if ent is not None:
            ent.scan_index = scan_index
            scan_index += 1
            entropy_ranges.append(ent)
        segments.append(seg)
        i = next_i
        if seg.marker == 0xD9:
            break

    return segments, entropy_ranges


def decode_app0(payload: bytes) -> Optional[Dict[str, str]]:
    """
    Decode APP0 payload if it matches JFIF or JFXX signatures.
    """
    if payload.startswith(b"JFIF\x00") and len(payload) >= 14:
        ver = f"{payload[5]}.{payload[6]:02d}"
        units = payload[7]
        xden = read_u16(payload[8:10])
        yden = read_u16(payload[10:12])
        return {
            "type": "JFIF",
            "version": ver,
            "units": str(units),
            "x_density": str(xden),
            "y_density": str(yden),
        }
    if payload.startswith(b"JFXX\x00"):
        return {"type": "JFXX"}
    return None


def decode_dqt(payload: bytes) -> List[Dict[str, str]]:
    """
    Decode Define Quantization Table (DQT) payload into table summaries.
    """
    tables: List[Dict[str, str]] = []
    i = 0
    while i < len(payload):
        pq_tq = payload[i]
        i += 1
        precision = 16 if (pq_tq >> 4) else 8
        table_id = pq_tq & 0x0F
        size = 128 if precision == 16 else 64
        if i + size > len(payload):
            break
        tables.append({
            "id": str(table_id),
            "precision_bits": str(precision),
            "bytes": str(size),
        })
        i += size
    return tables


def decode_dht(payload: bytes) -> List[Dict[str, str]]:
    """
    Decode Define Huffman Table (DHT) payload into table summaries.
    """
    tables: List[Dict[str, str]] = []
    i = 0
    while i + 17 <= len(payload):
        tc_th = payload[i]
        i += 1
        tc = tc_th >> 4
        th = tc_th & 0x0F
        counts = payload[i:i + 16]
        i += 16
        total = sum(counts)
        if i + total > len(payload):
            break
        tables.append({
            "class": "AC" if tc == 1 else "DC",
            "id": str(th),
            "values": str(total),
        })
        i += total
    return tables


def decode_sof0(payload: bytes) -> Optional[Dict[str, str]]:
    """
    Decode baseline Start Of Frame (SOF0) payload into image geometry info.
    """
    if len(payload) < 6:
        return None
    precision = payload[0]
    height = read_u16(payload[1:3])
    width = read_u16(payload[3:5])
    comps = payload[5]
    return {
        "precision_bits": str(precision),
        "width": str(width),
        "height": str(height),
        "components": str(comps),
    }


def decode_sos(payload: bytes) -> Optional[Dict[str, str]]:
    """
    Decode Start Of Scan (SOS) payload into component and spectral info.
    """
    if len(payload) < 6:
        return None
    ns = payload[0]
    needed = 1 + (2 * ns) + 3
    if len(payload) < needed:
        return None
    ss = payload[1 + 2 * ns]
    se = payload[2 + 2 * ns]
    ahal = payload[3 + 2 * ns]
    return {
        "components": str(ns),
        "ss": str(ss),
        "se": str(se),
        "ahal": f"0x{ahal:02X}",
    }


def decode_dri(payload: bytes) -> Optional[Dict[str, str]]:
    """
    Decode Define Restart Interval (DRI) payload into a restart interval value.
    """
    if len(payload) != 2:
        return None
    return {"restart_interval": str(read_u16(payload))}

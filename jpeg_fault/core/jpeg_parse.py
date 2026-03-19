"""
JPEG parsing utilities for segment discovery and entropy range detection.

This module provides:
- Segment parsing with marker names and payload bounds.
- Entropy-coded stream range extraction (after SOS).
- Lightweight decoding of common segment payloads for reporting.
"""

from typing import Dict, List, Optional, Tuple

from .constants.jpeg import JFIF_SIGNATURE, JFXX_SIGNATURE, JPEG_ZIGZAG_ORDER, MARKER_NAMES, NO_LENGTH_MARKERS
from .models import EntropyRange, Segment


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
    if payload.startswith(JFIF_SIGNATURE) and len(payload) >= 14:
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
    if payload.startswith(JFXX_SIGNATURE):
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


def decode_dqt_tables(payload: bytes) -> List[Dict[str, object]]:
    """
    Decode DQT payload into full quantization tables.
    """
    tables: List[Dict[str, object]] = []
    i = 0
    while i < len(payload):
        pq_tq = payload[i]
        i += 1
        precision = 16 if (pq_tq >> 4) else 8
        table_id = pq_tq & 0x0F
        size = 128 if precision == 16 else 64
        if i + size > len(payload):
            break
        if precision == 8:
            values = list(payload[i:i + 64])
            i += 64
        else:
            values = []
            for _ in range(64):
                values.append(read_u16(payload[i:i + 2]))
                i += 2
        tables.append({
            "id": table_id,
            "precision_bits": precision,
            "values": values,
        })
    return tables


def dqt_values_to_natural_grid(values: List[int]) -> List[List[int]]:
    """
    Convert 64 DQT values from JPEG zigzag serialization into an 8x8 grid.
    """
    grid = [[0 for _ in range(8)] for _ in range(8)]
    for idx, val in enumerate(values[:64]):
        pos = JPEG_ZIGZAG_ORDER[idx]
        row = pos // 8
        col = pos % 8
        grid[row][col] = val
    return grid


def dqt_natural_grid_to_values(grid: List[List[int]]) -> List[int]:
    """
    Convert an 8x8 natural-order DQT grid into JPEG zigzag serialization order.
    """
    flat = [val for row in grid for val in row][:64]
    if len(flat) < 64:
        flat.extend([0] * (64 - len(flat)))
    return [flat[pos] for pos in JPEG_ZIGZAG_ORDER]


def build_dqt_payload(tables: List[Dict[str, object]]) -> bytes:
    """
    Build a DQT payload from decoded table dictionaries.
    """
    payload = bytearray()
    for table in tables:
        table_id = int(table.get("id", 0))
        precision = int(table.get("precision_bits", 8))
        values = list(table.get("values", []))[:64]
        if len(values) != 64:
            raise ValueError("Each DQT table must contain exactly 64 values.")
        pq = 1 if precision > 8 else 0
        payload.append(((pq & 0x0F) << 4) | (table_id & 0x0F))
        if pq == 0:
            for value in values:
                if value < 0 or value > 255:
                    raise ValueError("8-bit DQT values must be 0..255.")
                payload.append(value)
            continue
        for value in values:
            if value < 0 or value > 65535:
                raise ValueError("16-bit DQT values must be 0..65535.")
            payload.extend(int(value).to_bytes(2, "big"))
    return bytes(payload)


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


def decode_dht_tables(payload: bytes) -> List[Dict[str, object]]:
    """
    Decode DHT payload into full table data including counts, symbols, and codes.
    """
    tables: List[Dict[str, object]] = []
    i = 0
    while i + 17 <= len(payload):
        tc_th = payload[i]
        i += 1
        tc = tc_th >> 4
        th = tc_th & 0x0F
        counts = list(payload[i:i + 16])
        i += 16
        total = sum(counts)
        if i + total > len(payload):
            break
        symbols = list(payload[i:i + total])
        i += total
        # Rebuild canonical Huffman codes from the JPEG count histogram.
        code = 0
        codes: List[Dict[str, int]] = []
        pos = 0
        for length, count in enumerate(counts, start=1):
            for _ in range(count):
                if pos >= len(symbols):
                    break
                codes.append({
                    "length": length,
                    "code": code,
                    "symbol": symbols[pos],
                })
                code += 1
                pos += 1
            code <<= 1
        tables.append({
            "class": "AC" if tc == 1 else "DC",
            "id": th,
            "counts": counts,
            "symbols": symbols,
            "codes": codes,
        })
    return tables


def build_dht_payload(tables: List[Dict[str, object]]) -> bytes:
    """
    Build a DHT payload from decoded table dictionaries.
    """
    payload = bytearray()
    for table in tables:
        table_class = str(table.get("class", "DC")).upper()
        tc = 1 if table_class == "AC" else 0
        th = int(table.get("id", 0))
        counts = [int(v) for v in list(table.get("counts", []))[:16]]
        if len(counts) != 16:
            raise ValueError("Each DHT table must contain exactly 16 count values.")
        symbols = [int(v) for v in list(table.get("symbols", []))]
        if sum(counts) != len(symbols):
            raise ValueError("DHT symbol count must match the sum of counts.")
        payload.append(((tc & 0x0F) << 4) | (th & 0x0F))
        for count in counts:
            if count < 0 or count > 255:
                raise ValueError("DHT count values must be 0..255.")
            payload.append(count)
        for symbol in symbols:
            if symbol < 0 or symbol > 255:
                raise ValueError("DHT symbols must be 0..255.")
            payload.append(symbol)
    return bytes(payload)


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


def decode_sof_components(payload: bytes) -> List[Dict[str, int]]:
    """
    Decode SOF component descriptors including quantization table assignment.
    """
    if len(payload) < 6:
        return []
    comps = payload[5]
    needed = 6 + (3 * comps)
    if len(payload) < needed:
        return []
    components: List[Dict[str, int]] = []
    i = 6
    for _ in range(comps):
        comp_id = payload[i]
        sampling = payload[i + 1]
        components.append({
            "id": comp_id,
            "h_sampling": sampling >> 4,
            "v_sampling": sampling & 0x0F,
            "quant_table_id": payload[i + 2],
        })
        i += 3
    return components


def build_sof0_payload(
    precision_bits: int,
    width: int,
    height: int,
    components: List[Dict[str, int]],
) -> bytes:
    """
    Build a baseline SOF0 payload from decoded frame fields.
    """
    if precision_bits < 0 or precision_bits > 255:
        raise ValueError("SOF0 precision_bits must be 0..255.")
    if width < 0 or width > 65535 or height < 0 or height > 65535:
        raise ValueError("SOF0 width/height must be 0..65535.")
    if len(components) > 255:
        raise ValueError("SOF0 component count must be 0..255.")
    payload = bytearray()
    payload.append(int(precision_bits))
    payload.extend(int(height).to_bytes(2, "big"))
    payload.extend(int(width).to_bytes(2, "big"))
    payload.append(len(components))
    for comp in components:
        comp_id = int(comp.get("id", 0))
        h_sampling = int(comp.get("h_sampling", 1))
        v_sampling = int(comp.get("v_sampling", 1))
        quant_table_id = int(comp.get("quant_table_id", 0))
        if not 0 <= comp_id <= 255:
            raise ValueError("SOF0 component id must be 0..255.")
        if not 0 <= h_sampling <= 15 or not 0 <= v_sampling <= 15:
            raise ValueError("SOF0 sampling factors must be 0..15.")
        if not 0 <= quant_table_id <= 255:
            raise ValueError("SOF0 quant_table_id must be 0..255.")
        payload.append(comp_id)
        payload.append((h_sampling << 4) | v_sampling)
        payload.append(quant_table_id)
    return bytes(payload)


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


def decode_sos_components(payload: bytes) -> List[Dict[str, int]]:
    """
    Decode SOS component selectors including DC/AC Huffman table ids.
    """
    if len(payload) < 6:
        return []
    ns = payload[0]
    needed = 1 + (2 * ns) + 3
    if len(payload) < needed:
        return []
    components: List[Dict[str, int]] = []
    i = 1
    for _ in range(ns):
        comp_id = payload[i]
        td_ta = payload[i + 1]
        components.append({
            "id": comp_id,
            "dc_table_id": td_ta >> 4,
            "ac_table_id": td_ta & 0x0F,
        })
        i += 2
    return components


def build_sos_payload(
    components: List[Dict[str, int]],
    ss: int,
    se: int,
    ah: int,
    al: int,
) -> bytes:
    """
    Build an SOS payload from component selectors and spectral/approximation fields.
    """
    if len(components) > 255:
        raise ValueError("SOS component count must be 0..255.")
    payload = bytearray()
    payload.append(len(components) & 0xFF)
    for component in components:
        comp_id = int(component.get("id", 0))
        dc_table_id = int(component.get("dc_table_id", 0))
        ac_table_id = int(component.get("ac_table_id", 0))
        if comp_id < 0 or comp_id > 255:
            raise ValueError("SOS component id must be 0..255.")
        if dc_table_id < 0 or dc_table_id > 15 or ac_table_id < 0 or ac_table_id > 15:
            raise ValueError("SOS Huffman table ids must be 0..15.")
        payload.append(comp_id & 0xFF)
        payload.append(((dc_table_id & 0x0F) << 4) | (ac_table_id & 0x0F))
    for value, name in ((ss, "Ss"), (se, "Se"), (ah, "Ah"), (al, "Al")):
        if value < 0 or value > 255:
            raise ValueError(f"SOS {name} must be 0..255.")
    if ah > 15 or al > 15:
        raise ValueError("SOS Ah and Al must be 0..15.")
    payload.append(ss & 0xFF)
    payload.append(se & 0xFF)
    payload.append(((ah & 0x0F) << 4) | (al & 0x0F))
    return bytes(payload)


def decode_dri(payload: bytes) -> Optional[Dict[str, str]]:
    """
    Decode Define Restart Interval (DRI) payload into a restart interval value.
    """
    if len(payload) != 2:
        return None
    return {"restart_interval": str(read_u16(payload))}


def build_dri_payload(restart_interval: int) -> bytes:
    """
    Build a DRI payload from a restart interval value.
    """
    if restart_interval < 0 or restart_interval > 65535:
        raise ValueError("DRI restart_interval must be 0..65535.")
    return int(restart_interval).to_bytes(2, "big")

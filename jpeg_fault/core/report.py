"""
Human-readable JPEG structure reporting with optional colorized output.

This module formats the parsed JPEG segments and entropy ranges into a
verbose report that explains segment meaning and shows hex previews.
"""

from typing import Dict, List, Tuple

from .jpeg_parse import (
    decode_app0,
    decode_dht,
    decode_dqt,
    decode_dri,
    decode_sof0,
    decode_sos,
    format_bytes,
)
from .models import EntropyRange, Segment


def segment_details(seg: Segment, data: bytes) -> List[str]:
    """
    Decode known segment payloads to produce human-readable details.
    """
    details: List[str] = []
    if seg.length_field is None:
        return details
    payload = data[seg.payload_offset:seg.payload_offset + seg.payload_length]
    if seg.name == "APP0":
        info = decode_app0(payload)
        if info:
            details.append(f"APP0: {info}")
    if seg.name == "DQT":
        tables = decode_dqt(payload)
        for t in tables:
            details.append(f"DQT: table id={t['id']} precision={t['precision_bits']} bits bytes={t['bytes']}")
    if seg.name == "DHT":
        tables = decode_dht(payload)
        for t in tables:
            details.append(f"DHT: class={t['class']} id={t['id']} values={t['values']}")
    if seg.name == "SOF0":
        info = decode_sof0(payload)
        if info:
            details.append(
                f"SOF0: {info['width']}x{info['height']} precision={info['precision_bits']} components={info['components']}"
            )
    if seg.name == "SOS":
        info = decode_sos(payload)
        if info:
            details.append(
                f"SOS: components={info['components']} Ss={info['ss']} Se={info['se']} AhAl={info['ahal']}"
            )
    if seg.name == "DRI":
        info = decode_dri(payload)
        if info:
            details.append(f"DRI: restart_interval={info['restart_interval']}")
    if seg.name == "COM":
        details.append(f"COM: {seg.payload_length} bytes")
    return details


def explain_common(seg: Segment, actual: List[str]) -> List[str]:
    """
    Provide shared explanation lines for segment structure and length.
    """
    lines: List[str] = []
    if seg.length_field is None:
        lines.append("Structure: FF marker")
        lines.append("Typical: 2 bytes total")
        return lines
    lines.append("Structure: FF marker + 2-byte length + payload")
    lines.append("Length field: includes the length bytes themselves")
    lines.append("Typical length: >= 2")
    if actual:
        for line in actual:
            lines.append(f"Actual: {line}")
    return lines


def segment_intro_lines(seg_name: str) -> List[str]:
    """
    Introductory description of a segment type, based on its name.
    """
    if seg_name == "SOI":
        return ["What it is: Start Of Image marker"]
    if seg_name == "EOI":
        return ["What it is: End Of Image marker"]
    if seg_name.startswith("APP"):
        return [
            "What it is: Application-specific metadata segment",
            "Typical: APP0=JFIF or JFXX, APP1=EXIF, others app-defined",
        ]
    mapping: Dict[str, List[str]] = {
        "DQT": [
            "What it is: Define Quantization Table",
            "Structure: one or more tables with precision and id",
            "Typical: 8-bit precision (64 bytes per table), id 0-3",
        ],
        "DHT": [
            "What it is: Define Huffman Table",
            "Structure: class(DC/AC), id, 16 code-length counts, values",
            "Typical: small number of tables, id 0-3",
        ],
        "SOS": [
            "What it is: Start Of Scan (begins entropy-coded data)",
            "Structure: components, table selectors, spectral/select info",
            "Typical: baseline uses Ss=0, Se=63, AhAl=0x00",
        ],
        "DRI": [
            "What it is: Define Restart Interval",
            "Structure: 2-byte restart interval",
            "Typical: 0 or small values, unit is MCUs",
        ],
        "COM": [
            "What it is: Comment string",
            "Structure: free-form bytes",
            "Typical: ASCII text, variable length",
        ],
    }
    if seg_name.startswith("SOF"):
        return [
            "What it is: Start Of Frame (image geometry and sampling)",
            "Structure: precision, height, width, components",
            "Typical: 8-bit precision, 1-4 components",
        ]
    return mapping.get(seg_name, ["What it is: Segment type not explicitly decoded"])


def explain_segment(seg: Segment, data: bytes) -> List[str]:
    """
    Build the full explanation for a segment, including decoded details.
    """
    actual = segment_details(seg, data)
    lines: List[str] = segment_intro_lines(seg.name)
    lines.extend(explain_common(seg, actual))
    return lines


def use_color(mode: str) -> bool:
    """
    Decide whether to use ANSI colors based on the CLI color mode.
    """
    if mode == "always":
        return True
    if mode == "never":
        return False
    import sys

    return sys.stdout.isatty()


def colorize(text: str, color: str, enabled: bool) -> str:
    """
    Apply an ANSI color code to text if colors are enabled.
    """
    if not enabled:
        return text
    code = {
        "cyan": "36",
        "green": "32",
        "yellow": "33",
        "magenta": "35",
        "gray": "90",
    }.get(color, "0")
    return f"\033[{code}m{text}\033[0m"


def classify_head_bytes(segments: List[Segment], head_len: int) -> List[str]:
    """
    Classify each byte in the file head as marker, length, payload, or other.
    """
    labels = ["other"] * head_len
    for seg in segments:
        m_start = seg.offset
        m_end = seg.offset + 2
        for i in range(max(0, m_start), min(head_len, m_end)):
            labels[i] = "marker"
        if seg.length_field is None:
            continue
        l_start = (seg.payload_offset or 0) - 2
        l_end = l_start + 2
        for i in range(max(0, l_start), min(head_len, l_end)):
            labels[i] = "length"
        p_start = seg.payload_offset or 0
        p_end = p_start + (seg.payload_length or 0)
        for i in range(max(0, p_start), min(head_len, p_end)):
            labels[i] = "payload"
    return labels


def format_head_colored(data: bytes, labels: List[str], colors: bool) -> str:
    """
    Format the file head as colored hex bytes using classification labels.
    """
    parts: List[str] = []
    for i, b in enumerate(data[: len(labels)]):
        text = f"{b:02X}"
        if labels[i] == "marker":
            parts.append(colorize(text, "yellow", colors))
        elif labels[i] == "length":
            parts.append(colorize(text, "cyan", colors))
        elif labels[i] == "payload":
            parts.append(colorize(text, "green", colors))
        else:
            parts.append(text)
    return " ".join(parts)


def segment_hex_parts(seg: Segment, data: bytes, preview: int) -> Tuple[str, str, str, bool]:
    """
    Return hex strings for marker, length, and payload preview of a segment.
    """
    marker = format_bytes(data, seg.offset, 2)
    if seg.length_field is None:
        return marker, "", "", False
    length_off = seg.payload_offset - 2 if seg.payload_offset else seg.offset + 2
    length = format_bytes(data, length_off, 2)
    payload_len = seg.payload_length or 0
    take = min(payload_len, preview)
    payload = format_bytes(data, seg.payload_offset or 0, take)
    truncated = payload_len > preview
    return marker, length, payload, truncated


def print_segment_header(seg: Segment, idx: int, colors: bool) -> None:
    """
    Print a summary line for a segment (offsets, marker, length, payload).
    """
    marker_hex = f"FF{seg.marker:02X}"
    end_off = seg.offset + seg.total_length - 1
    header = (
        f"- {idx}: {seg.name} start 0x{seg.offset:08X} end 0x{end_off:08X} marker {marker_hex}"
    )
    if seg.length_field is None:
        line = f"{header} total 2 bytes"
        print(colorize(line, "green", colors))
        return
    payload_len = seg.payload_length or 0
    length_hex = f"0x{seg.length_field:04X}"
    line = f"{header} length {length_hex} payload {payload_len} total {seg.total_length} bytes"
    print(colorize(line, "green", colors))


def print_segment_hex(seg: Segment, data: bytes, colors: bool) -> None:
    """
    Print a formatted hex preview of a segment's marker/length/payload bytes.
    """
    marker, length, payload, truncated = segment_hex_parts(seg, data, preview=16)
    if seg.length_field is None:
        label = colorize("  Hex:", "gray", colors)
        part = colorize(f"[marker] {marker}", "yellow", colors)
        print(f"{label} {part}")
        return
    payload_text = payload + (" ..." if truncated else "")
    label = colorize("  Hex:", "gray", colors)
    m = colorize(f"[marker] {marker}", "yellow", colors)
    l = colorize(f"[length] {length}", "cyan", colors)
    p = colorize(f"[payload] {payload_text}", "green", colors)
    print(f"{label} {m} {l} {p}")


def print_entropy_ranges(entropy_ranges: List[EntropyRange], colors: bool) -> None:
    """
    Print a summary of entropy-coded ranges found in the JPEG.
    """
    if entropy_ranges:
        print(colorize("Entropy-coded data ranges:", "magenta", colors))
        for r in entropy_ranges:
            print(f"- Scan {r.scan_index}: 0x{r.start:08X}..0x{r.end:08X} ({r.end - r.start} bytes)")
        return
    print("No entropy-coded data ranges found.")


def print_report(
    path: str,
    data: bytes,
    segments: List[Segment],
    entropy_ranges: List[EntropyRange],
    color_mode: str,
) -> None:
    """
    Print the full JPEG report, including segment list and entropy ranges.
    """
    colors = use_color(color_mode)
    print(colorize(f"File: {path}", "cyan", colors))
    print(f"Size: {len(data)} bytes")
    head_len = min(64, len(data))
    labels = classify_head_bytes(segments, head_len)
    head = format_head_colored(data, labels, colors)
    print(f"Head (first {head_len} bytes): {head}")
    print("")
    print(colorize("Segments (marker/length/payload):", "magenta", colors))
    for idx, seg in enumerate(segments):
        print_segment_header(seg, idx, colors)
        print_segment_hex(seg, data, colors)
        for info in explain_segment(seg, data):
            print(colorize(f"  {info}", "gray", colors))
    print("")
    print_entropy_ranges(entropy_ranges, colors)

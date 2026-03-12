#!/usr/bin/env python3
import argparse
import os
import random
import sys
from bisect import bisect_right
from glob import glob

from PIL import Image
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

@dataclass
class Segment:
    marker: int
    offset: int
    name: str
    length_field: Optional[int]
    payload_offset: Optional[int]
    payload_length: Optional[int]
    total_length: int

@dataclass
class EntropyRange:
    start: int
    end: int  # exclusive
    scan_index: int

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
    return (be[0] << 8) | be[1]


def marker_name(marker: int) -> str:
    return MARKER_NAMES.get(marker, f"0xFF{marker:02X}")


def format_bytes(data: bytes, start: int, count: int) -> str:
    end = min(len(data), start + count)
    return " ".join(f"{b:02X}" for b in data[start:end])


def next_marker_offset(data: bytes, start: int) -> int:
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

    seg_len = read_u16(data[i:i+2])
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
    if payload.startswith(b"JFIF\x00") and len(payload) >= 14:
        ver = f"{payload[5]}.{payload[6]}"
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
    tables: List[Dict[str, str]] = []
    i = 0
    while i + 17 <= len(payload):
        tc_th = payload[i]
        i += 1
        tc = tc_th >> 4
        th = tc_th & 0x0F
        counts = payload[i:i+16]
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
    if len(payload) != 2:
        return None
    return {"restart_interval": str(read_u16(payload))}


def segment_details(seg: Segment, data: bytes) -> List[str]:
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


def explain_segment(seg: Segment, data: bytes) -> List[str]:
    lines: List[str] = []
    actual = segment_details(seg, data)

    if seg.name == "SOI":
        lines.append("What it is: Start Of Image marker")
        lines.extend(explain_common(seg, actual))
        return lines
    if seg.name == "EOI":
        lines.append("What it is: End Of Image marker")
        lines.extend(explain_common(seg, actual))
        return lines

    if seg.name.startswith("APP"):
        lines.append("What it is: Application-specific metadata segment")
        lines.append("Typical: APP0=JFIF or JFXX, APP1=EXIF, others app-defined")
        lines.extend(explain_common(seg, actual))
        return lines

    if seg.name == "DQT":
        lines.append("What it is: Define Quantization Table")
        lines.append("Structure: one or more tables with precision and id")
        lines.append("Typical: 8-bit precision (64 bytes per table), id 0-3")
        lines.extend(explain_common(seg, actual))
        return lines

    if seg.name == "DHT":
        lines.append("What it is: Define Huffman Table")
        lines.append("Structure: class(DC/AC), id, 16 code-length counts, values")
        lines.append("Typical: small number of tables, id 0-3")
        lines.extend(explain_common(seg, actual))
        return lines

    if seg.name.startswith("SOF"):
        lines.append("What it is: Start Of Frame (image geometry and sampling)")
        lines.append("Structure: precision, height, width, components")
        lines.append("Typical: 8-bit precision, 1-4 components")
        lines.extend(explain_common(seg, actual))
        return lines

    if seg.name == "SOS":
        lines.append("What it is: Start Of Scan (begins entropy-coded data)")
        lines.append("Structure: components, table selectors, spectral/select info")
        lines.append("Typical: baseline uses Ss=0, Se=63, AhAl=0x00")
        lines.extend(explain_common(seg, actual))
        return lines

    if seg.name == "DRI":
        lines.append("What it is: Define Restart Interval")
        lines.append("Structure: 2-byte restart interval")
        lines.append("Typical: 0 or small values, unit is MCUs")
        lines.extend(explain_common(seg, actual))
        return lines

    if seg.name == "COM":
        lines.append("What it is: Comment string")
        lines.append("Structure: free-form bytes")
        lines.append("Typical: ASCII text, variable length")
        lines.extend(explain_common(seg, actual))
        return lines

    lines.append("What it is: Segment type not explicitly decoded")
    lines.extend(explain_common(seg, actual))
    return lines


def use_color(mode: str) -> bool:
    if mode == "always":
        return True
    if mode == "never":
        return False
    return sys.stdout.isatty()


def colorize(text: str, color: str, enabled: bool) -> str:
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


def parse_bits_list(spec: str) -> List[int]:
    if spec.lower() == "msb":
        return [7]
    if spec.lower() == "lsb":
        return [0]
    bits: List[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise ValueError(f"Invalid bit index: {part}")
        bit = int(part)
        if bit < 0 or bit > 7:
            raise ValueError(f"Bit index out of range (0-7): {bit}")
        bits.append(bit)
    return sorted(set(bits))


def parse_mutation_mode(spec: str) -> Tuple[str, Optional[List[int]]]:
    if spec in {"add1", "sub1", "flipall"}:
        return spec, None
    if spec.startswith("bitflip:"):
        bits = parse_bits_list(spec.split(":", 1)[1])
        if not bits:
            raise ValueError("bitflip requires at least one bit index")
        return "bitflip", bits
    raise ValueError("Invalid mutate mode. Use add1, sub1, flipall, or bitflip:<bits>")


def mutate_byte(orig: int, mode: str, bits: Optional[List[int]]) -> List[Tuple[int, str]]:
    if mode == "add1":
        if orig == 0xFF:
            return []
        return [(orig + 1, "add1")]
    if mode == "sub1":
        if orig == 0x00:
            return []
        return [(orig - 1, "sub1")]
    if mode == "flipall":
        return [(orig ^ 0xFF, "flipall")]
    if mode == "bitflip" and bits is not None:
        return [(orig ^ (1 << b), f"bit{b}") for b in bits]
    return []


def total_entropy_length(ranges: List[EntropyRange]) -> int:
    return sum(r.end - r.start for r in ranges)


def build_cumulative(ranges: List[EntropyRange]) -> List[int]:
    ends: List[int] = []
    total = 0
    for r in ranges:
        total += r.end - r.start
        ends.append(total)
    return ends


def index_to_offset(idx: int, ranges: List[EntropyRange], ends: List[int]) -> int:
    pos = bisect_right(ends, idx)
    prev_end = 0 if pos == 0 else ends[pos - 1]
    return ranges[pos].start + (idx - prev_end)


def select_offsets_from_ranges(
    ranges: List[EntropyRange],
    sample_n: int,
    seed: int,
) -> List[int]:
    total_len = total_entropy_length(ranges)
    if total_len == 0:
        return []
    if sample_n <= 0 or sample_n >= total_len:
        return [i for r in ranges for i in range(r.start, r.end)]
    rng = random.Random(seed)
    ends = build_cumulative(ranges)
    picks = rng.sample(range(total_len), sample_n)
    return [index_to_offset(i, ranges, ends) for i in picks]


def write_mutations(
    data: bytes,
    entropy_ranges: List[EntropyRange],
    output_dir: str,
    base_name: str,
    mode: str,
    bits: Optional[List[int]],
    sample_n: int,
    seed: int,
) -> int:
    os.makedirs(output_dir, exist_ok=True)
    total = 0
    data_arr = bytearray(data)

    offsets = select_offsets_from_ranges(entropy_ranges, sample_n, seed)
    for offset in offsets:
        orig = data[offset]
        for new, tag in mutate_byte(orig, mode, bits):
            data_arr[offset] = new
            out_name = (
                f"{base_name}_off_{offset:08X}_orig_{orig:02X}_new_{new:02X}_mut_{tag}.jpg"
            )
            out_path = os.path.join(output_dir, out_name)
            with open(out_path, "wb") as f:
                f.write(data_arr)
            total += 1
        data_arr[offset] = orig
    return total


def list_mutation_files(output_dir: str, base_name: str) -> List[str]:
    pattern = os.path.join(output_dir, f"{base_name}_off_*_mut_*.jpg")
    return sorted(glob(pattern))


def load_frames(paths: List[str]) -> List[Image.Image]:
    frames: List[Image.Image] = []
    for p in paths:
        try:
            img = Image.open(p)
            frames.append(img.convert("RGB"))
        except Exception:
            continue
    return frames


def write_gif(paths: List[str], out_path: str, fps: int, loop: int, seed: int, shuffle: bool) -> int:
    if shuffle:
        rng = random.Random(seed)
        rng.shuffle(paths)
    frames = load_frames(paths)
    if not frames:
        return 0
    duration_ms = max(1, int(1000 / max(1, fps)))
    frames[0].save(
        out_path,
        save_all=True,
        append_images=frames[1:],
        duration=duration_ms,
        loop=loop,
    )
    return len(frames)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="JPEG fault tolerance mutator and reporter")
    parser.add_argument("input", help="Input JPEG file")
    parser.add_argument("-o", "--output-dir", default="mutations", help="Output directory for mutated files")
    parser.add_argument(
        "--mutate",
        default="add1",
        help="Mutation mode: add1, sub1, flipall, bitflip:<bits> (e.g., bitflip:0,1,3 or bitflip:msb)",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=100,
        help="Monte Carlo sample size (number of byte offsets). Use 0 to disable sampling.",
    )
    parser.add_argument("--seed", type=int, default=3, help="Random seed for sampling")
    parser.add_argument("--report-only", action="store_true", help="Only print report, no mutations")
    parser.add_argument("--color", choices=["auto", "always", "never"], default="auto", help="Color output mode")
    parser.add_argument("--gif", help="If set, write a GIF from the mutated outputs to this path")
    parser.add_argument("--gif-fps", type=int, default=10, help="GIF frames per second (default 10)")
    parser.add_argument("--gif-loop", type=int, default=0, help="GIF loop count (0 = infinite)")
    parser.add_argument("--gif-shuffle", action="store_true", help="Shuffle GIF frame order (uses --seed)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    with open(args.input, "rb") as f:
        data = f.read()

    segments, entropy_ranges = parse_jpeg(data)
    print_report(args.input, data, segments, entropy_ranges, args.color)

    if args.report_only:
        return 0

    mode, bits = parse_mutation_mode(args.mutate)

    base_name = os.path.splitext(os.path.basename(args.input))[0]
    count = write_mutations(
        data,
        entropy_ranges,
        args.output_dir,
        base_name,
        mode,
        bits,
        args.sample,
        args.seed,
    )
    print("")
    print(f"Generated {count} mutated files in {args.output_dir}")
    if args.gif:
        paths = list_mutation_files(args.output_dir, base_name)
        frame_count = write_gif(paths, args.gif, args.gif_fps, args.gif_loop, args.seed, args.gif_shuffle)
        print(f"GIF: wrote {frame_count} frames to {args.gif}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

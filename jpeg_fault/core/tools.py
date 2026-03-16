"""
Utility helpers for inserting custom APPn segments into JPEG files.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from .jpeg_parse import parse_jpeg
from .models import Segment


def build_appn_segment(appn: int, payload: bytes) -> bytes:
    """
    Build a raw APPn segment (marker + length + payload).
    """
    if appn < 0 or appn > 15:
        raise ValueError("APPn index must be 0..15.")
    if len(payload) > 65533:
        raise ValueError("APPn payload must be <= 65533 bytes.")
    marker = bytes([0xFF, 0xE0 + appn])
    length_field = (len(payload) + 2).to_bytes(2, "big")
    return marker + length_field + payload


def _default_insertion_offset(segments: List[Segment]) -> int:
    """
    Insert after the last APPn segment at the top of the file.
    """
    last_app_end = 2
    for seg in segments:
        if seg.marker == 0xD8:  # SOI
            last_app_end = seg.offset + seg.total_length
            continue
        if 0xE0 <= seg.marker <= 0xEF:
            last_app_end = seg.offset + seg.total_length
            continue
        break
    return last_app_end


def insert_custom_appn(data: bytes, appn: int, payload: bytes) -> bytes:
    """
    Insert a custom APPn segment after the last existing APPn segment.
    """
    segments, _ = parse_jpeg(data)
    offset = _default_insertion_offset(segments)
    seg = build_appn_segment(appn, payload)
    return data[:offset] + seg + data[offset:]


def read_payload_hex(text: str) -> bytes:
    """
    Parse a hex string with whitespace into bytes.
    """
    cleaned = []
    for ch in text:
        if ch.isspace():
            cleaned.append(" ")
            continue
        if ch in "0123456789abcdefABCDEF":
            cleaned.append(ch)
            continue
        raise ValueError(f"Invalid hex character: {ch}")
    hex_str = "".join(cleaned)
    compact = "".join(hex_str.split())
    if len(compact) % 2 != 0:
        raise ValueError("Hex string has odd length.")
    return bytes.fromhex(hex_str)


def output_path_for(input_path: str, appn: int, out_path: str | None) -> str:
    """
    Resolve output path for an APPn-inserted file.
    """
    if out_path:
        return out_path
    p = Path(input_path)
    return str(p.with_name(f"{p.stem}_app{appn:02d}.jpg"))

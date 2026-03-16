"""
Shared data models used across parsing, reporting, and mutation logic.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Segment:
    """
    Represents a JPEG segment marker and its associated metadata.

    Fields:
    - marker: The marker byte after 0xFF (e.g., 0xD8 for SOI).
    - offset: File offset of the 0xFF marker byte.
    - name: Human-readable marker name (e.g., "SOF0", "APP0").
    - length_field: Raw 16-bit length field (includes its own 2 bytes), or None for SOI/EOI.
    - payload_offset: Start of payload bytes, or None for SOI/EOI.
    - payload_length: Payload length in bytes, or None for SOI/EOI.
    - total_length: Total segment size in bytes including marker and length field.
    """
    marker: int
    offset: int
    name: str
    length_field: Optional[int]
    payload_offset: Optional[int]
    payload_length: Optional[int]
    total_length: int


@dataclass
class EntropyRange:
    """
    Represents a contiguous entropy-coded byte range for a single scan.

    Fields:
    - start: Inclusive file offset of entropy-coded data.
    - end: Exclusive file offset of entropy-coded data.
    - scan_index: Which scan this range belongs to.
    """
    start: int
    end: int  # exclusive
    scan_index: int

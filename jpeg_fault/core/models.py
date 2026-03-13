from dataclasses import dataclass
from typing import Optional


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

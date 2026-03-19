from __future__ import annotations

"""
Core JPEG byte-level constants used by parsing and table-oriented tooling.
"""

# Marker bytes that do not carry a 16-bit segment length field.
NO_LENGTH_MARKERS = {0xD8, 0xD9}

# Friendly marker names used in reports, parsing output, and the TUI.
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

# JPEG's fixed zigzag scan order for 8x8 coefficient blocks.
JPEG_ZIGZAG_ORDER = [
    0, 1, 5, 6, 14, 15, 27, 28,
    2, 4, 7, 13, 16, 26, 29, 42,
    3, 8, 12, 17, 25, 30, 41, 43,
    9, 11, 18, 24, 31, 40, 44, 53,
    10, 19, 23, 32, 39, 45, 52, 54,
    20, 22, 33, 38, 46, 51, 55, 60,
    21, 34, 37, 47, 50, 56, 59, 61,
    35, 36, 48, 49, 57, 58, 62, 63,
]

JFIF_SIGNATURE = b"JFIF\x00"
JFXX_SIGNATURE = b"JFXX\x00"

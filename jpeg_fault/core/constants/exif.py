from __future__ import annotations

"""
EXIF/TIFF constants shared by parsing and APP1 editor code.
"""

EXIF_SIGNATURE = b"Exif\x00\x00"
TIFF_MAGIC = 0x002A

# Pointer tags used to walk nested EXIF IFDs.
EXIF_POINTER_TAGS = {
    "ExifIFD": 0x8769,
    "GPSIFD": 0x8825,
    "InteropIFD": 0xA005,
}

# EXIF/TIFF value-type widths from the EXIF spec.
EXIF_TYPE_SIZES = {
    1: 1,   # BYTE
    2: 1,   # ASCII
    3: 2,   # SHORT
    4: 4,   # LONG
    5: 8,   # RATIONAL
    7: 1,   # UNDEFINED
    9: 4,   # SLONG
    10: 8,  # SRATIONAL
}

EXIF_TYPE_NAMES = {
    1: "BYTE",
    2: "ASCII",
    3: "SHORT",
    4: "LONG",
    5: "RATIONAL",
    7: "UNDEFINED",
    9: "SLONG",
    10: "SRATIONAL",
}

EXIF_REQUIRED_IFD_KEYS = ("0th", "Exif", "GPS", "1st", "Interop")

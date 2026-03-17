from __future__ import annotations


def detect_format(path: str) -> str:
    with open(path, "rb") as f:
        head = f.read(16)

    if head.startswith(b"\xFF\xD8"):
        return "jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\x1F\x8B"):
        return "gz"
    if head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06") or head.startswith(b"PK\x07\x08"):
        return "zip"
    return "unknown"

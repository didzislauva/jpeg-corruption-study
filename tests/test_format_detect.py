from __future__ import annotations

from pathlib import Path

from jpeg_fault.core.format_detect import detect_format


def _write_bytes(tmp_path: Path, name: str, data: bytes) -> str:
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def test_detect_format_magic(tmp_path: Path) -> None:
    jpeg = _write_bytes(tmp_path, "a.jpg", b"\xFF\xD8\xFF\xE0" + b"\x00" * 8)
    png = _write_bytes(tmp_path, "a.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    gz = _write_bytes(tmp_path, "a.gz", b"\x1F\x8B" + b"\x00" * 8)
    zipf = _write_bytes(tmp_path, "a.zip", b"PK\x03\x04" + b"\x00" * 8)
    unk = _write_bytes(tmp_path, "a.bin", b"\x00" * 8)

    assert detect_format(jpeg) == "jpeg"
    assert detect_format(png) == "png"
    assert detect_format(gz) == "gz"
    assert detect_format(zipf) == "zip"
    assert detect_format(unk) == "unknown"

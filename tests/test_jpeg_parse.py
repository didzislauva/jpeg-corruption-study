"""
Tests for JPEG parsing utilities and segment decode helpers.
"""

from jpeg_fault.core import jpeg_parse as jp


def test_read_u16_and_marker_name_and_format_bytes() -> None:
    """
    Validate basic helpers: u16 decode, marker name, and hex formatting.
    """
    assert jp.read_u16(bytes([0x12, 0x34])) == 0x1234
    assert jp.marker_name(0xD8) == "SOI"
    assert jp.marker_name(0xAA).startswith("0xFF")
    assert jp.format_bytes(bytes([0xAA, 0xBB, 0xCC]), 1, 2) == "BB CC"


def test_next_marker_offset_handles_stuffed_and_restart() -> None:
    """
    Ensure marker scanning skips stuffed and restart markers.
    """
    data = bytes([0x00, 0xFF, 0x00, 0x11, 0xFF, 0xD0, 0x22, 0xFF, 0xD9])
    assert jp.next_marker_offset(data, 0) == 7


def test_parse_segment_no_length_marker_soi() -> None:
    """
    Verify SOI parsing as a no-length segment.
    """
    seg, nxt, ent = jp.parse_segment(bytes([0xFF, 0xD8, 0xFF, 0xD9]), 0)
    assert seg.name == "SOI"
    assert nxt == 2
    assert ent is None


def test_parse_segment_sos_returns_entropy_range(tiny_jpeg_bytes: bytes) -> None:
    """
    Ensure SOS parsing returns an entropy range and correct next offset.
    """
    sos_idx = tiny_jpeg_bytes.index(bytes([0xFF, 0xDA]))
    seg, nxt, ent = jp.parse_segment(tiny_jpeg_bytes, sos_idx)
    assert seg.name == "SOS"
    assert ent is not None
    assert ent.start < ent.end
    assert nxt == ent.end


def test_parse_segment_errors() -> None:
    """
    Validate error handling for malformed segment inputs.
    """
    try:
        jp.parse_segment(bytes([0x00, 0xD8]), 0)
        assert False
    except ValueError as e:
        assert "Expected marker" in str(e)

    try:
        jp.parse_segment(bytes([0xFF]), 0)
        assert False
    except ValueError as e:
        assert "Unexpected end" in str(e)

    try:
        jp.parse_segment(bytes([0xFF, 0xE0, 0x00]), 0)
        assert False
    except ValueError as e:
        assert "Truncated length" in str(e)

    try:
        jp.parse_segment(bytes([0xFF, 0xE0, 0x00, 0x01]), 0)
        assert False
    except ValueError as e:
        assert "Invalid segment length" in str(e)


def test_parse_jpeg_and_decode_helpers(tiny_jpeg_bytes: bytes) -> None:
    """
    Validate full JPEG parsing and payload decoder helpers.
    """
    segs, ents = jp.parse_jpeg(tiny_jpeg_bytes)
    assert segs[0].name == "SOI"
    assert segs[-1].name == "EOI"
    assert len(ents) == 1
    assert ents[0].scan_index == 0

    assert jp.decode_app0(bytes([0x4A, 0x46, 0x49, 0x46, 0x00, 1, 2, 1, 0, 1, 0, 1, 0, 0]))["type"] == "JFIF"
    assert jp.decode_app0(b"JFXX\x00abc")["type"] == "JFXX"
    assert jp.decode_app0(b"bad") is None

    dqt_payload = bytes([0x00] + [0] * 64)
    assert jp.decode_dqt(dqt_payload)[0]["bytes"] == "64"

    dht_payload = bytes([0x00] + [1] + [0] * 15 + [0x2A])
    dht = jp.decode_dht(dht_payload)
    assert dht[0]["class"] == "DC"
    assert dht[0]["values"] == "1"

    sof = jp.decode_sof0(bytes([8, 0, 2, 0, 3, 1]))
    assert sof["width"] == "3" and sof["height"] == "2"
    assert jp.decode_sof0(b"\x08\x00") is None

    sos = jp.decode_sos(bytes([1, 1, 0, 0, 63, 0]))
    assert sos["components"] == "1"
    assert jp.decode_sos(b"\x01") is None

    assert jp.decode_dri(bytes([0, 7]))["restart_interval"] == "7"
    assert jp.decode_dri(bytes([0, 1, 2])) is None


def test_parse_jpeg_missing_soi() -> None:
    """
    Ensure missing SOI marker raises a ValueError.
    """
    try:
        jp.parse_jpeg(bytes([0x00, 0x00]))
        assert False
    except ValueError as e:
        assert "missing SOI" in str(e)

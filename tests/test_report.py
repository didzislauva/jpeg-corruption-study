"""
Tests for report formatting and explanatory helpers.
"""

from jpeg_fault.core.jpeg_parse import parse_jpeg
from jpeg_fault.core.models import EntropyRange, Segment
from jpeg_fault.core import report as rp


def test_segment_details_and_explainers(tiny_jpeg_bytes: bytes) -> None:
    """
    Validate detail extraction and explanation helpers for segments.
    """
    segs, _ = parse_jpeg(tiny_jpeg_bytes)
    app0 = next(s for s in segs if s.name == "APP0")
    sos = next(s for s in segs if s.name == "SOS")

    details = rp.segment_details(app0, tiny_jpeg_bytes)
    assert any("APP0" in d for d in details)

    sos_details = rp.segment_details(sos, tiny_jpeg_bytes)
    assert any("SOS:" in d for d in sos_details)

    common = rp.explain_common(sos, sos_details)
    assert any("Structure" in c for c in common)

    intro = rp.segment_intro_lines("DHT")
    assert any("Huffman" in i for i in intro)

    exp = rp.explain_segment(sos, tiny_jpeg_bytes)
    assert any("Start Of Scan" in e for e in exp)


def test_color_helpers() -> None:
    """
    Validate color mode decisions and ANSI colorization helper.
    """
    assert rp.use_color("always") is True
    assert rp.use_color("never") is False
    assert rp.colorize("x", "green", False) == "x"
    assert "\x1b[" in rp.colorize("x", "green", True)


def test_classify_and_head_formatting(tiny_jpeg_bytes: bytes) -> None:
    """
    Validate head byte classification and formatting.
    """
    segs, _ = parse_jpeg(tiny_jpeg_bytes)
    labels = rp.classify_head_bytes(segs, 20)
    assert len(labels) == 20
    txt = rp.format_head_colored(tiny_jpeg_bytes, labels, False)
    assert len(txt.split()) == 20


def test_segment_hex_parts_and_prints(capsys) -> None:
    """
    Validate hex segment formatting and printing helpers.
    """
    seg = Segment(0xD8, 0, "SOI", None, None, None, 2)
    marker, length, payload, trunc = rp.segment_hex_parts(seg, bytes([0xFF, 0xD8]), 8)
    assert marker == "FF D8" and length == "" and payload == "" and trunc is False

    rp.print_segment_header(seg, 0, False)
    rp.print_segment_hex(seg, bytes([0xFF, 0xD8]), False)
    out = capsys.readouterr().out
    assert "SOI" in out and "Hex" in out


def test_entropy_ranges_and_full_report_output(capsys, tiny_jpeg_bytes: bytes) -> None:
    """
    Validate entropy range printing and full report output.
    """
    segs, ents = parse_jpeg(tiny_jpeg_bytes)
    rp.print_entropy_ranges([EntropyRange(1, 3, 0)], False)
    assert "Scan 0" in capsys.readouterr().out

    rp.print_report("tiny.jpg", tiny_jpeg_bytes, segs, ents, "never")
    out = capsys.readouterr().out
    assert "Segments" in out
    assert "Entropy-coded data ranges" in out

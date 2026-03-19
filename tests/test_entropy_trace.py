from __future__ import annotations

from jpeg_fault.core.entropy_trace import format_scan_trace_text, trace_entropy_scans
from jpeg_fault.core.jpeg_parse import parse_jpeg
from jpeg_fault.core import entropy_trace as et


def test_trace_entropy_scans_decodes_single_zero_block(decodable_jpeg_bytes: bytes) -> None:
    segments, entropy_ranges = parse_jpeg(decodable_jpeg_bytes)

    scans = trace_entropy_scans(decodable_jpeg_bytes, segments, entropy_ranges)

    assert len(scans) == 1
    scan = scans[0]
    assert scan.supported is True
    assert scan.component_names == ["Y"]
    assert len(scan.blocks) == 1

    block = scan.blocks[0]
    assert block.component_name == "Y"
    assert block.scan_bit_start == 0
    assert block.scan_bit_end == 2
    assert block.bits_used == 2
    assert block.scan_byte_start == 0
    assert block.scan_byte_end == 0
    assert block.file_byte_offsets == [entropy_ranges[0].start]
    assert block.dc.category == 0
    assert block.dc.coefficient == 0
    assert len(block.ac_steps) == 1
    assert block.ac_steps[0].is_eob is True
    assert block.zz_coeffs == [0] * 64
    assert block.natural_coeffs == [0] * 64
    assert scan.restart_segments[0].block_count == 1


def test_format_scan_trace_text_mentions_block_and_tables(decodable_jpeg_bytes: bytes) -> None:
    segments, entropy_ranges = parse_jpeg(decodable_jpeg_bytes)
    scans = trace_entropy_scans(decodable_jpeg_bytes, segments, entropy_ranges)

    text = format_scan_trace_text(scans)

    assert "Scan 0" in text
    assert "MCU 0 block 0 Y" in text
    assert "Tables: DC=0 AC=0 QT=0" in text
    assert "DC huff=0 category=0" in text
    assert "sym=0x00" in text


def test_trace_entropy_scans_marks_progressive_scan_unsupported(progressive_like_jpeg_bytes: bytes) -> None:
    segments, entropy_ranges = parse_jpeg(progressive_like_jpeg_bytes)

    scans = trace_entropy_scans(progressive_like_jpeg_bytes, segments, entropy_ranges)

    assert len(scans) == 1
    assert scans[0].supported is False
    assert scans[0].progressive is True
    assert "Progressive" in scans[0].reason or "implemented yet" in scans[0].reason


def test_mcu_block_plan_uses_component_grid_size_not_extra_sampling_division() -> None:
    components = [
        et._ScanComponent(1, "Y", 2, 2, 0, 0, 0, 80, 60),
        et._ScanComponent(2, "Cb", 1, 1, 1, 1, 1, 40, 30),
        et._ScanComponent(3, "Cr", 1, 1, 1, 1, 1, 40, 30),
    ]

    plan, mcu_count = et._mcu_block_plan(components)

    assert len(plan) == 6
    assert mcu_count == 40 * 30


def test_trace_entropy_scans_handles_restart_marker_padding_in_dsc04780(
    dsc04780_jpeg_bytes: bytes,
) -> None:
    segments, entropy_ranges = parse_jpeg(dsc04780_jpeg_bytes)

    scans = trace_entropy_scans(dsc04780_jpeg_bytes, segments, entropy_ranges)

    assert len(scans) == 1
    scan = scans[0]
    assert scan.supported is True
    assert scan.reason == ""
    assert len(scan.blocks) == 58482
    assert len(scan.restart_segments) == 171

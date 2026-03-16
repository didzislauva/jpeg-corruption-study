"""
Tests for basic dataclasses and debug logging helper.
"""

from jpeg_fault.core.debug import debug_log
from jpeg_fault.core.models import EntropyRange, Segment


def test_segment_dataclass_fields() -> None:
    """
    Validate Segment dataclass field assignment.
    """
    seg = Segment(0xDA, 10, "SOS", 8, 14, 6, 10)
    assert seg.marker == 0xDA
    assert seg.name == "SOS"
    assert seg.total_length == 10


def test_entropy_range_dataclass_fields() -> None:
    """
    Validate EntropyRange dataclass field assignment.
    """
    ent = EntropyRange(100, 200, 3)
    assert ent.start == 100
    assert ent.end == 200
    assert ent.scan_index == 3


def test_debug_log_prints_only_when_enabled(capsys) -> None:
    """
    Ensure debug_log only prints when enabled.
    """
    debug_log(False, "hidden")
    assert capsys.readouterr().err == ""

    debug_log(True, "visible")
    assert "[DEBUG] visible" in capsys.readouterr().err

import pytest

from jpeg_fault.core.models import Segment
from jpeg_fault.core.tui import JpegFaultTui


def _build_icc_profile() -> bytes:
    # Minimal ICC profile with one tag.
    header = bytearray(128)
    size = 128 + 4 + 12 + 4
    header[0:4] = size.to_bytes(4, "big")
    header[4:8] = b"TEST"
    header[8:12] = (0x04300000).to_bytes(4, "big")
    header[12:16] = b"mntr"
    header[16:20] = b"RGB "
    header[20:24] = b"XYZ "
    # date 2024-01-02 03:04:05
    header[24:26] = (2024).to_bytes(2, "big")
    header[26:28] = (1).to_bytes(2, "big")
    header[28:30] = (2).to_bytes(2, "big")
    header[30:32] = (3).to_bytes(2, "big")
    header[32:34] = (4).to_bytes(2, "big")
    header[34:36] = (5).to_bytes(2, "big")
    header[36:40] = b"acsp"

    tag_table = bytearray()
    tag_table += (1).to_bytes(4, "big")
    tag_table += b"desc" + (128 + 4 + 12).to_bytes(4, "big") + (4).to_bytes(4, "big")
    tag_data = b"DATA"
    return bytes(header) + bytes(tag_table) + tag_data


def _build_app2_payload() -> bytes:
    icc = _build_icc_profile()
    return b"ICC_PROFILE\x00" + bytes([1, 1]) + icc


def test_parse_icc_profile_ok():
    app = JpegFaultTui()
    payload = _build_app2_payload()
    out = app._parse_icc_profile(payload, 0)
    assert out["error"] is None
    assert out["seq"] == 1
    assert out["total"] == 1
    assert out["header"]["magic"] == "acsp"
    assert out["tags"][0]["sig"] == "desc"


def test_parse_icc_profile_missing_header():
    app = JpegFaultTui()
    out = app._parse_icc_profile(b"BAD", 0)
    assert out["error"]


def test_app2_tabs_created():
    app = JpegFaultTui()

    class FakeTabs:
        def __init__(self):
            self.panes = []

        def clear_panes(self):
            self.panes.clear()

        def add_pane(self, pane):
            self.panes.append(pane._title)

    left = FakeTabs()
    right = FakeTabs()

    def fake_query(selector, *args, **kwargs):
        if selector == "#app2-00000000-tabs":
            return left
        if selector == "#app2-00000000-right-tabs":
            return right
        raise AssertionError(f"unexpected selector {selector}")

    app.query_one = fake_query  # type: ignore[assignment]
    app._init_app2_tabs("app2-00000000")
    assert left.panes == ["Raw", "Hex", "Table"]
    assert right.panes == ["Header", "Tags", "Tag Table", "Edit"]

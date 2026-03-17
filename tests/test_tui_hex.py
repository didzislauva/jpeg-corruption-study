from __future__ import annotations

from jpeg_fault.core.models import Segment
from jpeg_fault.core.tui import JpegFaultTui
from tests.tui_test_helpers import FakeInput, FakeListView, FakeRichLog, FakeStatic, install_query


def test_render_full_hex_page_builds_legend() -> None:
    app = JpegFaultTui()
    app.info_data = bytes(range(32))
    app.info_segments = [
        Segment(0xD8, 0, "SOI", None, None, None, 2),
        Segment(0xD9, 30, "EOI", None, None, None, 2),
    ]
    widgets = {
        "#info-hex-legend": FakeListView(),
        "#info-hex": FakeRichLog(),
        "#hex-page-info": FakeStatic(),
        "#hex-page": FakeInput("1"),
    }
    install_query(app, widgets)

    app._render_full_hex_page()

    assert widgets["#info-hex-legend"].items
    assert app.hex_legend_offsets
    assert "Page 1/1" in widgets["#hex-page-info"].text

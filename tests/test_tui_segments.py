from __future__ import annotations

from pathlib import Path

import pytest
from textual.worker import WorkerState

from jpeg_fault.core import jpeg_parse as jp
from jpeg_fault.core.entropy_trace import trace_entropy_scans
from jpeg_fault.core.models import Segment
from jpeg_fault.core.tui import JpegFaultTui
from jpeg_fault.core.tui.entropy_trace import TraceBlockButton, TraceNavButton
from tests.tui_test_helpers import (
    FakeButton,
    FakeCheckbox,
    FakeContainer,
    FakeInput,
    FakeLog,
    FakeStatic,
    FakeTabs,
    FakeTextArea,
    install_query,
    segment_by_name,
    workspace_widgets,
)
from jpeg_fault.core.tui import segments_appn as appn_module


def _build_test_app2_payload() -> bytes:
    header = bytearray(128)
    size = 128 + 4 + 12 + 4
    header[0:4] = size.to_bytes(4, "big")
    header[4:8] = b"TEST"
    header[8:12] = (0x04300000).to_bytes(4, "big")
    header[12:16] = b"mntr"
    header[16:20] = b"RGB "
    header[20:24] = b"XYZ "
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
    return b"ICC_PROFILE\x00" + bytes([1, 1]) + bytes(header) + bytes(tag_table) + b"DATA"


def test_tui_compose_smoke() -> None:
    app = JpegFaultTui()
    assert app.defaults.output_dir == "mutations"
    assert app.current_panel == "input"


def test_render_sof0_workspace(rich_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    widgets = workspace_widgets("sof0", ["frame", "components", "tables"], "struct-edit")
    install_query(app, widgets)

    app._render_sof0_segment(rich_jpeg_bytes, jp.parse_jpeg(rich_jpeg_bytes)[0])

    assert "Frame: 8x8 precision=8 components=3" in widgets["#info-sof0-left"].text
    assert "Width: 8" in widgets["#info-sof0-frame"].text
    assert "Component 1 (Y / luma)" in widgets["#info-sof0-components"].text
    assert "Quantization table id=0" in widgets["#info-sof0-tables"].text


def test_render_sof0_segment_ignores_missing_mounted_tabs(rich_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    widgets = {"#info-sof0-left": FakeLog()}
    install_query(app, widgets)

    app._render_sof0_segment(rich_jpeg_bytes, jp.parse_jpeg(rich_jpeg_bytes)[0])

    assert widgets["#info-sof0-left"].text == ""


def test_sof0_length_change_ignores_missing_manual_length_checkbox() -> None:
    app = JpegFaultTui()
    calls: list[bool] = []
    app._mark_sof0_dirty = lambda dirty: calls.append(dirty)  # type: ignore[assignment]
    install_query(app, {})

    class DummyInput:
        id = "sof0-length"

    class DummyEvent:
        input = DummyInput()

    app._on_sof0_input_changed(DummyEvent())

    assert calls == [True]


def test_dqt_length_change_ignores_missing_manual_length_checkbox() -> None:
    app = JpegFaultTui()
    calls: list[tuple[str, bool]] = []
    app._set_dqt_dirty = lambda key, dirty: calls.append((key, dirty))  # type: ignore[assignment]
    install_query(app, {})

    class DummyInput:
        id = "dqt-0000117A-length"

    class DummyEvent:
        input = DummyInput()

    app._on_dqt_input_changed(DummyEvent())

    assert calls == [("dqt-0000117A", True)]


def test_dqt_textarea_change_ignores_missing_widgets() -> None:
    app = JpegFaultTui()
    calls: list[tuple[str, bool]] = []
    app._set_dqt_dirty = lambda key, dirty: calls.append((key, dirty))  # type: ignore[assignment]
    install_query(app, {})

    class DummyTextArea:
        id = "dqt-0000117A-grid-edit"

    class DummyEvent:
        text_area = DummyTextArea()

    app._on_dqt_textarea_changed(DummyEvent())

    assert calls == []


def test_set_dqt_editor_values_ignores_missing_editor_widgets() -> None:
    app = JpegFaultTui()
    install_query(app, {})

    app._set_dqt_editor_values("dqt-000077BC", bytes([0x00] + [0x01] * 64), 67)


def test_render_dri_workspace(rich_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    widgets = workspace_widgets("dri", ["summary", "effect"], "struct-edit")
    install_query(app, widgets)

    app._render_dri_segment(rich_jpeg_bytes, jp.parse_jpeg(rich_jpeg_bytes)[0])

    assert "Restart interval: 4 MCUs" in widgets["#info-dri-left"].text
    assert "Enabled: yes" in widgets["#info-dri-summary"].text
    assert "every 4 MCUs" in widgets["#info-dri-effect"].text


def test_render_dqt_workspace_and_usage(rich_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    app.info_data = rich_jpeg_bytes
    app.info_segments = jp.parse_jpeg(rich_jpeg_bytes)[0]
    key = "dqt-00000000"
    widgets = workspace_widgets(key, ["grid", "zigzag", "stats", "usage", "heatmap"], "grid-edit")
    install_query(app, widgets)

    app._render_dqt_segment(rich_jpeg_bytes, segment_by_name(rich_jpeg_bytes, "DQT"), key)

    assert "Natural 8x8 view" in widgets[f"#info-{key}-grid"].text
    assert "00:" in widgets[f"#info-{key}-zigzag"].text
    assert "low-band avg" in widgets[f"#info-{key}-stats"].text
    assert "Y / luma" in widgets[f"#info-{key}-usage"].text
    assert "heatmap" in widgets[f"#info-{key}-heatmap"].text.lower()


def test_render_dht_workspace_and_usage(rich_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    app.info_data = rich_jpeg_bytes
    app.info_segments = jp.parse_jpeg(rich_jpeg_bytes)[0]
    key = "dht-00000000"
    widgets = workspace_widgets(key, ["tables", "counts", "symbols", "usage", "codes"], "table-edit")
    install_query(app, widgets)

    app._render_dht_segment(rich_jpeg_bytes, segment_by_name(rich_jpeg_bytes, "DHT"), key)

    assert "Canonical Huffman table summaries" in widgets[f"#info-{key}-tables"].text
    assert "L02:" in widgets[f"#info-{key}-counts"].text
    assert "0xF0" in widgets[f"#info-{key}-symbols"].text
    assert "Scan 1: component 1" in widgets[f"#info-{key}-usage"].text
    assert "00:00" in widgets[f"#info-{key}-codes"].text


def test_app0_preview_refresh() -> None:
    app = JpegFaultTui()
    app.app0_segment_info = (0, 18, 16, 4)
    widgets = {
        "#info-app0": FakeLog(),
        "#app0-edit-error": FakeStatic(),
        "#app0-manual-length": FakeCheckbox(False),
        "#app0-length": FakeInput("0010"),
    }
    install_query(app, widgets)
    app._build_app0_payload = lambda: b"JFIF\x00\x01\x02\x01\x00\x48\x00\x48\x00\x00"  # type: ignore[assignment]

    app._refresh_app0_preview()

    assert "APP0 at 0x00000000" in widgets["#info-app0"].text
    assert "Identifier: JFIF\\0" in widgets["#info-app0"].text


def test_render_entropy_trace_workspace(decodable_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    app.info_data = decodable_jpeg_bytes
    segments, entropy_ranges = jp.parse_jpeg(decodable_jpeg_bytes)
    scan = trace_entropy_scans(decodable_jpeg_bytes, segments, entropy_ranges)[0]
    key = "etrace-scan-0"
    widgets = {
        f"#{key}-blocks": FakeContainer(),
        f"#{key}-page-info": FakeStatic(),
        f"#{key}-page": FakeInput(),
        f"#info-{key}-overview": FakeLog(),
        f"#info-{key}-bits": FakeLog(),
        f"#info-{key}-dc": FakeLog(),
        f"#info-{key}-ac": FakeLog(),
        f"#info-{key}-coefficients": FakeLog(),
        f"#info-{key}-tables": FakeLog(),
    }
    install_query(app, widgets)

    app._render_entropy_trace_scan(key, scan)

    assert len(widgets[f"#{key}-blocks"].children) == 1
    assert "MCU 0 block 0" in widgets[f"#info-{key}-overview"].text
    assert "Scan bit range: [0,2)" in widgets[f"#info-{key}-bits"].text
    assert "Bitstream:" in widgets[f"#info-{key}-bits"].text
    assert "Bytestream:" in widgets[f"#info-{key}-bits"].text
    assert "00000000" in widgets[f"#info-{key}-bits"].text
    assert "00" in widgets[f"#info-{key}-bits"].text
    assert "Predictor: 0 -> 0" in widgets[f"#info-{key}-dc"].text
    assert "EOB=True" in widgets[f"#info-{key}-ac"].text
    assert "Natural 8x8 grid" in widgets[f"#info-{key}-coefficients"].text
    assert "DC table id: 0" in widgets[f"#info-{key}-tables"].text


def test_render_sos_workspace_and_links(rich_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    app.info_data = rich_jpeg_bytes
    segs, ents = jp.parse_jpeg(rich_jpeg_bytes)
    app.info_segments = segs
    app.info_entropy_ranges = ents
    seg = segment_by_name(rich_jpeg_bytes, "SOS")
    key = f"sos-{seg.offset:08X}"
    widgets = workspace_widgets(key, ["header", "components", "flow", "links"], "struct-edit")
    install_query(app, widgets)

    app._render_sos_segment(rich_jpeg_bytes, seg, key, 0)

    assert "Components in scan (Ns): 3" in widgets[f"#info-{key}-header"].text
    assert "Component 1: id=1" in widgets[f"#info-{key}-components"].text
    assert "Scan 0:" in widgets[f"#info-{key}-flow"].text
    assert "Referenced Huffman tables:" in widgets[f"#info-{key}-links"].text


def test_sos_preview_and_save(rich_jpeg_path: Path, rich_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    segs, ents = jp.parse_jpeg(rich_jpeg_bytes)
    app.info_data = rich_jpeg_bytes
    app.info_segments = segs
    app.info_entropy_ranges = ents
    seg = segment_by_name(rich_jpeg_bytes, "SOS")
    key = f"sos-{seg.offset:08X}"
    app.sos_segment_info[key] = (seg.offset, seg.total_length, seg.length_field or 0, seg.payload_offset or 0)
    app.sos_scan_index[key] = 0
    widgets = workspace_widgets(key, ["header", "components", "flow", "links"], "struct-edit")
    widgets["#input-path"] = FakeInput(str(rich_jpeg_path))
    widgets[f"#{key}-struct-edit"].text = (
        "{'components': [{'id': 1, 'dc_table_id': 0, 'ac_table_id': 0}, "
        "{'id': 2, 'dc_table_id': 1, 'ac_table_id': 1}, "
        "{'id': 3, 'dc_table_id': 1, 'ac_table_id': 1}], "
        "'ss': 0, 'se': 63, 'ah': 0, 'al': 0}"
    )
    install_query(app, widgets)

    app._refresh_sos_preview(key)
    assert "Components in scan (Ns): 3" in widgets[f"#info-{key}-header"].text

    input_path, payload, length_field = app._sos_save_inputs(key)
    out_path = app._sos_write_file(key, input_path, payload, length_field)
    out_seg = segment_by_name(out_path.read_bytes(), "SOS")
    assert out_path.exists()
    assert out_path.read_bytes()[out_seg.payload_offset:out_seg.payload_offset + out_seg.payload_length] == payload


def test_sos_struct_editor_updates_active_highlight(rich_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    segs, ents = jp.parse_jpeg(rich_jpeg_bytes)
    app.info_data = rich_jpeg_bytes
    app.info_segments = segs
    app.info_entropy_ranges = ents
    seg = segment_by_name(rich_jpeg_bytes, "SOS")
    key = f"sos-{seg.offset:08X}"
    widgets = workspace_widgets(key, ["header", "components", "flow", "links"], "struct-edit")
    install_query(app, widgets)

    app._render_sos_segment(rich_jpeg_bytes, seg, key, 0)

    editor = widgets[f"#{key}-struct-edit"]
    lines = editor.text.splitlines()
    ss_line = next(idx for idx, line in enumerate(lines) if "'ss':" in line)
    ss_col = lines[ss_line].index("'ss':") + len("'ss': ")
    editor.cursor_location = (ss_line, ss_col)

    app._update_sos_active_highlight(key)

    assert app.sos_active_highlight[key][:2] == (11, 12)


def test_sos_struct_editor_ns_and_first_component_highlight_different_bytes(rich_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    segs, ents = jp.parse_jpeg(rich_jpeg_bytes)
    app.info_data = rich_jpeg_bytes
    app.info_segments = segs
    app.info_entropy_ranges = ents
    seg = segment_by_name(rich_jpeg_bytes, "SOS")
    key = f"sos-{seg.offset:08X}"
    widgets = workspace_widgets(key, ["header", "components", "flow", "links"], "struct-edit")
    install_query(app, widgets)

    app._render_sos_segment(rich_jpeg_bytes, seg, key, 0)

    editor = widgets[f"#{key}-struct-edit"]
    lines = editor.text.splitlines()

    ns_line = next(idx for idx, line in enumerate(lines) if "'ns':" in line)
    ns_col = lines[ns_line].index("'ns':") + len("'ns': ")
    editor.cursor_location = (ns_line, ns_col)
    app._update_sos_active_highlight(key)
    assert app.sos_active_highlight[key][:2] == (4, 5)

    comp_line = next(idx for idx, line in enumerate(lines) if "'id': 1" in line)
    comp_col = lines[comp_line].index("'id': 1") + len("'id': ")
    editor.cursor_location = (comp_line, comp_col)
    app._update_sos_active_highlight(key)
    assert app.sos_active_highlight[key][:2] == (5, 6)


def test_sos_raw_hex_preview_recovers_lenient(rich_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    segs, ents = jp.parse_jpeg(rich_jpeg_bytes)
    app.info_data = rich_jpeg_bytes
    app.info_segments = segs
    app.info_entropy_ranges = ents
    seg = segment_by_name(rich_jpeg_bytes, "SOS")
    key = f"sos-{seg.offset:08X}"
    app.sos_segment_info[key] = (seg.offset, seg.total_length, seg.length_field or 0, seg.payload_offset or 0)
    app.sos_scan_index[key] = 0
    widgets = workspace_widgets(key, ["header", "components", "flow", "links"], "struct-edit")
    widgets[f"#{key}-advanced-mode"] = FakeCheckbox(True)
    widgets[f"#{key}-raw-hex"].text = "03 01 00 02 11 03 11 00 3F 0"
    install_query(app, widgets)

    app._refresh_sos_preview(key)

    assert app.sos_preview_payload[key] == bytes.fromhex("03 01 00 02 11 03 11 00 3F")
    assert widgets[f"#{key}-error"].text.startswith("Warning:")


def test_sos_raw_hex_editor_updates_active_highlight(rich_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    segs, ents = jp.parse_jpeg(rich_jpeg_bytes)
    app.info_data = rich_jpeg_bytes
    app.info_segments = segs
    app.info_entropy_ranges = ents
    seg = segment_by_name(rich_jpeg_bytes, "SOS")
    key = f"sos-{seg.offset:08X}"
    widgets = workspace_widgets(key, ["header", "components", "flow", "links"], "struct-edit")
    widgets[f"#{key}-advanced-mode"] = FakeCheckbox(True)
    install_query(app, widgets)

    app._render_sos_segment(rich_jpeg_bytes, seg, key, 0)

    editor = widgets[f"#{key}-raw-hex"]
    editor.cursor_location = (0, 3)
    app._update_sos_active_highlight(key)

    assert app.sos_active_highlight[key][:2] == (4, 5)


def test_render_entropy_trace_workspace_for_unsupported_scan(progressive_like_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    segments, entropy_ranges = jp.parse_jpeg(progressive_like_jpeg_bytes)
    scan = trace_entropy_scans(progressive_like_jpeg_bytes, segments, entropy_ranges)[0]
    key = "etrace-scan-0"
    widgets = {
        f"#{key}-blocks": FakeContainer(),
        f"#{key}-page-info": FakeStatic(),
        f"#{key}-page": FakeInput(),
        f"#info-{key}-overview": FakeLog(),
        f"#info-{key}-bits": FakeLog(),
        f"#info-{key}-dc": FakeLog(),
        f"#info-{key}-ac": FakeLog(),
        f"#info-{key}-coefficients": FakeLog(),
        f"#info-{key}-tables": FakeLog(),
    }
    install_query(app, widgets)

    app._render_entropy_trace_scan(key, scan)

    assert widgets[f"#{key}-blocks"].children == []
    assert "Supported: no" in widgets[f"#info-{key}-overview"].text
    assert "No block-level trace available" in widgets[f"#info-{key}-bits"].text


def test_entropy_trace_button_selection_updates_selected_block() -> None:
    app = JpegFaultTui()

    class DummyScan:
        blocks = ["b0", "b1", "b2"]

    calls: list[tuple[str, str, object]] = []
    renders: list[str] = []
    app.entropy_trace_scans = {"etrace-scan-0": DummyScan()}  # type: ignore[assignment]
    app.entropy_trace_pages = {"etrace-scan-0": 0}
    app._render_entropy_trace_block_detail = lambda key, block, scan: calls.append((key, block, scan))  # type: ignore[assignment]
    app._render_entropy_trace_page = lambda key: renders.append(key)  # type: ignore[assignment]

    class DummyEvent:
        button = TraceBlockButton("x", "etrace-scan-0", 2)

    app._on_entropy_trace_block_pressed(DummyEvent())

    assert app.entropy_trace_selected["etrace-scan-0"] == 2
    assert calls[0][0] == "etrace-scan-0"
    assert calls[0][1] == "b2"
    assert renders == []


def test_entropy_trace_prev_next_buttons_change_page() -> None:
    app = JpegFaultTui()

    class DummyScan:
        blocks = [f"b{i}" for i in range(40)]

    app.entropy_trace_scans = {"etrace-scan-0": DummyScan()}  # type: ignore[assignment]
    app.entropy_trace_pages = {"etrace-scan-0": 0}
    pages: list[int] = []
    app._render_entropy_trace_page = lambda key: pages.append(app.entropy_trace_pages[key])  # type: ignore[assignment]

    class DummyEvent:
        def __init__(self, direction: str) -> None:
            self.button = TraceNavButton(direction, "etrace-scan-0", direction)

    app._on_entropy_trace_nav_pressed(DummyEvent("next"))
    app._on_entropy_trace_nav_pressed(DummyEvent("prev"))

    assert pages == [1, 0]


def test_entropy_trace_worker_success_marks_loaded() -> None:
    app = JpegFaultTui()
    app._entropy_trace_worker_serial = 5
    app.entropy_trace_pending = True
    app.entropy_trace_loaded = False
    button_calls: list[tuple[bool, str]] = []
    status_calls: list[str] = []
    app._set_entropy_trace_load_button = lambda *, disabled, label: button_calls.append((disabled, label))  # type: ignore[assignment]
    app._set_entropy_trace_status = lambda text: status_calls.append(text)  # type: ignore[assignment]

    class DummyWorker:
        name = "entropy-trace-5"
        result = 5

    class DummyEvent:
        worker = DummyWorker()
        state = WorkerState.SUCCESS

    app._on_worker_state_changed(DummyEvent())

    assert app.entropy_trace_pending is False
    assert app.entropy_trace_loaded is True
    assert button_calls == [(False, "Reload Trace")]
    assert status_calls == ["Trace loaded."]


def test_entropy_trace_chunk_does_not_rerender_after_first_visible_page() -> None:
    app = JpegFaultTui()
    app._entropy_trace_worker_serial = 7
    app.entropy_trace_scans = {}
    app.entropy_trace_pages = {}
    app.entropy_trace_selected = {}
    rendered: list[str] = []
    appended: list[str] = []
    app._append_entropy_trace_scan_tab = lambda key, scan: appended.append(key)  # type: ignore[assignment]
    app._render_entropy_trace_scan = lambda key, scan: rendered.append(f"scan:{key}:{len(scan.blocks)}")  # type: ignore[assignment]
    app._render_entropy_trace_page = lambda key: rendered.append(f"page:{key}")  # type: ignore[assignment]

    first_chunk = type(
        "Chunk",
        (),
        {
            "scan_index": 0,
            "sof_name": "SOF0",
            "progressive": False,
            "supported": True,
            "reason": "",
            "ss": 0,
            "se": 63,
            "ah": 0,
            "al": 0,
            "restart_interval": 0,
            "component_ids": [1],
            "component_names": ["Y"],
            "total_scan_bits": 16,
            "entropy_file_start": 10,
            "entropy_file_end": 12,
            "blocks": ["b0"],
            "restart_segments": [],
        },
    )()
    second_chunk = type(
        "Chunk",
        (),
        {
            "scan_index": 0,
            "sof_name": "SOF0",
            "progressive": False,
            "supported": True,
            "reason": "",
            "ss": 0,
            "se": 63,
            "ah": 0,
            "al": 0,
            "restart_interval": 0,
            "component_ids": [1],
            "component_names": ["Y"],
            "total_scan_bits": 16,
            "entropy_file_start": 10,
            "entropy_file_end": 12,
            "blocks": ["b1"],
            "restart_segments": [],
        },
    )()

    app._apply_entropy_trace_chunk(7, first_chunk)
    app._apply_entropy_trace_chunk(7, second_chunk)

    assert appended == ["etrace-scan-0"]
    assert rendered == ["scan:etrace-scan-0:1"]


def test_entropy_trace_load_button_starts_worker() -> None:
    app = JpegFaultTui()
    app.info_data = b"data"
    app.info_segments = ["segments"]
    app.info_entropy_ranges = ["ranges"]
    app.entropy_trace_pending = False
    app._info_rebuild_serial = 7
    calls: list[tuple[str, object]] = []
    app._reset_entropy_trace_tabs = lambda scans: calls.append(("reset", scans)) or []  # type: ignore[assignment]
    app._set_entropy_trace_status = lambda text: calls.append(("status", text))  # type: ignore[assignment]
    app._set_entropy_trace_load_button = lambda *, disabled, label: calls.append(("button", (disabled, label)))  # type: ignore[assignment]
    app._start_entropy_trace_worker = lambda data, segments, entropy_ranges, serial: calls.append(("start", (data, segments, entropy_ranges, serial)))  # type: ignore[assignment]

    class DummyEvent:
        pass

    app._on_entropy_trace_load_pressed(DummyEvent())

    assert app.entropy_trace_pending is True
    assert app.entropy_trace_loaded is False
    assert calls == [
        ("reset", None),
        ("status", "Loading entropy trace..."),
        ("button", (True, "Loading Trace...")),
        ("start", (b"data", ["segments"], ["ranges"], 7)),
    ]


def test_sof0_preview_and_save(tmp_path: Path, rich_jpeg_path: Path, rich_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    seg = segment_by_name(rich_jpeg_bytes, "SOF0")
    app.sof0_segment_info = (seg.offset, seg.total_length, seg.length_field or 0, seg.payload_offset or 0)
    widgets = workspace_widgets("sof0", ["frame", "components", "tables"], "struct-edit")
    widgets["#input-path"] = FakeInput(str(rich_jpeg_path))
    widgets["#sof0-struct-edit"].text = (
        "{'precision_bits': 8, 'width': 16, 'height': 8, "
        "'components': [{'id': 1, 'h_sampling': 2, 'v_sampling': 2, 'quant_table_id': 0}, "
        "{'id': 2, 'h_sampling': 1, 'v_sampling': 1, 'quant_table_id': 0}, "
        "{'id': 3, 'h_sampling': 1, 'v_sampling': 1, 'quant_table_id': 0}]}"
    )
    install_query(app, widgets)

    app._refresh_sof0_preview()
    assert "Width: 16" in widgets["#info-sof0-frame"].text

    input_path, payload, length_field = app._sof0_save_inputs()
    out_path = app._sof0_write_file(input_path, payload, length_field)
    out_seg = segment_by_name(out_path.read_bytes(), "SOF0")
    assert out_path.exists()
    assert out_path != rich_jpeg_path
    assert out_path.read_bytes()[out_seg.payload_offset:out_seg.payload_offset + out_seg.payload_length] == payload


def test_sof0_struct_cursor_maps_width_to_highlight() -> None:
    app = JpegFaultTui()
    editor = FakeTextArea(
        "{'precision_bits': 8, 'width': 16, 'height': 8, 'component_count': 1, "
        "'components': [{'id': 1, 'h_sampling': 2, 'v_sampling': 2, 'quant_table_id': 0}]}"
    )
    editor.cursor_location = (0, editor.text.index(": 16") + 2)

    highlight = app._sof0_highlight_from_editor(editor)

    assert highlight == (7, 9, "bold black on grey70", "Active field: image width")


def test_sof0_struct_cursor_on_key_does_not_highlight() -> None:
    app = JpegFaultTui()
    editor = FakeTextArea(
        "{'precision_bits': 8, 'width': 16, 'height': 8, 'component_count': 1, "
        "'components': [{'id': 1, 'h_sampling': 2, 'v_sampling': 2, 'quant_table_id': 0}]}"
    )
    editor.cursor_location = (0, editor.text.index("'width'") + 2)

    highlight = app._sof0_highlight_from_editor(editor)

    assert highlight is None


def test_sof0_struct_cursor_maps_component_fields_to_component_bytes() -> None:
    app = JpegFaultTui()
    editor = FakeTextArea(
        "{'precision_bits': 8,\n"
        " 'width': 16,\n"
        " 'height': 8,\n"
        " 'component_count': 2,\n"
        " 'components': [{'id': 1, 'h_sampling': 2, 'v_sampling': 2, 'quant_table_id': 0},\n"
        "                {'id': 2, 'h_sampling': 1, 'v_sampling': 1, 'quant_table_id': 0}]}"
    )
    editor.cursor_location = (5, editor.text.splitlines()[5].index(": 1, 'v_sampling'") + 2)

    highlight = app._sof0_highlight_from_editor(editor)

    assert highlight == (14, 15, "bold black on grey70", "Active field: component 2 sampling byte")


def test_sof0_struct_component_count_and_first_component_id_highlight_different_bytes() -> None:
    app = JpegFaultTui()
    editor = FakeTextArea(
        "{'precision_bits': 8,\n"
        " 'width': 16,\n"
        " 'height': 8,\n"
        " 'component_count': 2,\n"
        " 'components': [{'id': 1, 'h_sampling': 2, 'v_sampling': 2, 'quant_table_id': 0},\n"
        "                {'id': 2, 'h_sampling': 1, 'v_sampling': 1, 'quant_table_id': 0}]}"
    )

    count_line = editor.text.splitlines()[3]
    editor.cursor_location = (3, count_line.index(": 2") + 2)
    assert app._sof0_highlight_from_editor(editor) == (
        9,
        10,
        "bold black on grey70",
        "Active field: component count",
    )

    comp_line = editor.text.splitlines()[4]
    editor.cursor_location = (4, comp_line.index("'id': 1") + len("'id': "))
    assert app._sof0_highlight_from_editor(editor) == (
        10,
        11,
        "bold black on grey70",
        "Active field: component 1 id",
    )


def test_sof0_preview_shows_active_highlight_legend(rich_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    seg = segment_by_name(rich_jpeg_bytes, "SOF0")
    app.sof0_segment_info = (seg.offset, seg.total_length, seg.length_field or 0, seg.payload_offset or 0)
    widgets = workspace_widgets("sof0", ["frame", "components", "tables"], "struct-edit")
    widgets["#sof0-struct-edit"].text = (
        "{'precision_bits': 8, 'width': 16, 'height': 8, 'component_count': 3, "
        "'components': [{'id': 1, 'h_sampling': 2, 'v_sampling': 2, 'quant_table_id': 0}, "
        "{'id': 2, 'h_sampling': 1, 'v_sampling': 1, 'quant_table_id': 0}, "
        "{'id': 3, 'h_sampling': 1, 'v_sampling': 1, 'quant_table_id': 0}]}"
    )
    widgets["#sof0-struct-edit"].cursor_location = (0, widgets["#sof0-struct-edit"].text.index("'width'") + 2)
    install_query(app, widgets)

    app._refresh_sof0_preview()

    assert "SOF0 at 0x" in widgets["#info-sof0-left"].text


def test_dri_preview_and_save(rich_jpeg_path: Path, rich_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    seg = segment_by_name(rich_jpeg_bytes, "DRI")
    app.dri_segment_info = (seg.offset, seg.total_length, seg.length_field or 0, seg.payload_offset or 0)
    widgets = workspace_widgets("dri", ["summary", "effect"], "struct-edit")
    widgets["#input-path"] = FakeInput(str(rich_jpeg_path))
    widgets["#dri-struct-edit"].text = "{'restart_interval': 9}"
    install_query(app, widgets)

    app._refresh_dri_preview()
    assert "9 MCUs" in widgets["#info-dri-summary"].text

    input_path, payload, length_field = app._dri_save_inputs()
    out_path = app._dri_write_file(input_path, payload, length_field)
    out_seg = segment_by_name(out_path.read_bytes(), "DRI")
    assert out_path.read_bytes()[out_seg.payload_offset:out_seg.payload_offset + out_seg.payload_length] == payload


def test_dqt_preview_save_and_mode_switch_sync(rich_jpeg_path: Path, rich_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    seg = segment_by_name(rich_jpeg_bytes, "DQT")
    key = "dqt-00000000"
    app.dqt_segment_info[key] = (seg.offset, seg.total_length, seg.length_field or 0, seg.payload_offset or 0)
    widgets = workspace_widgets(key, ["grid", "zigzag", "stats", "usage", "heatmap"], "grid-edit")
    widgets["#input-path"] = FakeInput(str(rich_jpeg_path))
    widgets[f"#{key}-grid-edit"].text = (
        "[{'id': 0, 'precision_bits': 8, 'grid': [[1,1,1,1,1,1,1,1],"
        "[1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1],"
        "[1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1]]}]"
    )
    install_query(app, widgets)

    app._refresh_dqt_preview(key)
    assert "mean=1.00" in widgets[f"#info-{key}-stats"].text
    widgets[f"#{key}-advanced-mode"].value = True
    app._sync_dqt_editor_for_mode(key)
    assert "01 01 01" in widgets[f"#{key}-raw-hex"].text

    widgets[f"#{key}-raw-hex"].text = app._bytes_to_hex(bytes([0x00] + [0x02] * 64))
    widgets[f"#{key}-advanced-mode"].value = False
    app._sync_dqt_editor_for_mode(key)
    assert "'precision_bits': 8" in widgets[f"#{key}-grid-edit"].text

    input_path, payload, length_field = app._dqt_save_inputs(key)
    out_path = app._dqt_write_file(key, input_path, payload, length_field)
    out_seg = segment_by_name(out_path.read_bytes(), "DQT")
    assert out_path.read_bytes()[out_seg.payload_offset:out_seg.payload_offset + out_seg.payload_length] == payload


def test_dqt_struct_cursor_maps_value_to_coefficient_byte(rich_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    seg = segment_by_name(rich_jpeg_bytes, "DQT")
    key = "dqt-00000000"
    payload = rich_jpeg_bytes[seg.payload_offset:seg.payload_offset + seg.payload_length]
    editor = FakeTextArea(
        "[{'id': 0,\n"
        "  'precision_bits': 8,\n"
        "  'grid': [[1, 2, 9, 17, 10, 3, 4, 11],\n"
        "           [18, 25, 33, 26, 19, 12, 5, 6]]}]"
    )
    editor.cursor_location = (2, editor.text.splitlines()[2].index("1, 2") )

    highlight = app._dqt_highlight_from_editor(editor, payload)

    assert highlight == (5, 6, "bold black on grey70", "DQT value")


def test_dqt_struct_cursor_on_key_does_not_highlight(rich_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    seg = segment_by_name(rich_jpeg_bytes, "DQT")
    payload = rich_jpeg_bytes[seg.payload_offset:seg.payload_offset + seg.payload_length]
    editor = FakeTextArea("[{'id': 0, 'precision_bits': 8, 'grid': [[1, 2, 9, 17, 10, 3, 4, 11]]}]")
    editor.cursor_location = (0, editor.text.index("'precision_bits'") + 2)

    highlight = app._dqt_highlight_from_editor(editor, payload)

    assert highlight is None


def test_dht_preview_save_and_mode_switch_sync(rich_jpeg_path: Path, rich_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    seg = segment_by_name(rich_jpeg_bytes, "DHT")
    key = "dht-00000000"
    app.dht_segment_info[key] = (seg.offset, seg.total_length, seg.length_field or 0, seg.payload_offset or 0)
    widgets = workspace_widgets(key, ["tables", "counts", "symbols", "usage", "codes"], "table-edit")
    widgets["#input-path"] = FakeInput(str(rich_jpeg_path))
    widgets[f"#{key}-table-edit"].text = (
        "[{'class': 'DC', 'id': 0, 'counts': [0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], 'symbols': [42]}]"
    )
    install_query(app, widgets)

    app._refresh_dht_preview(key)
    assert "Table 1: class=DC id=0" in widgets[f"#info-{key}-tables"].text
    widgets[f"#{key}-advanced-mode"].value = True
    app._sync_dht_editor_for_mode(key)
    assert "00 00 01" in widgets[f"#{key}-raw-hex"].text

    widgets[f"#{key}-raw-hex"].text = app._bytes_to_hex(bytes([0x00] + [0, 1] + [0] * 14 + [0x2A]))
    widgets[f"#{key}-advanced-mode"].value = False
    app._sync_dht_editor_for_mode(key)
    assert "'class': 'DC'" in widgets[f"#{key}-table-edit"].text

    input_path, payload, length_field = app._dht_save_inputs(key)
    out_path = app._dht_write_file(key, input_path, payload, length_field)
    out_seg = segment_by_name(out_path.read_bytes(), "DHT")
    assert out_path.read_bytes()[out_seg.payload_offset:out_seg.payload_offset + out_seg.payload_length] == payload


def test_dht_struct_cursor_maps_count_and_symbol_values_to_bytes(rich_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    seg = segment_by_name(rich_jpeg_bytes, "DHT")
    payload = rich_jpeg_bytes[seg.payload_offset:seg.payload_offset + seg.payload_length]
    editor = FakeTextArea(
        "[{'class': 'DC',\n"
        "  'id': 0,\n"
        "  'counts': [0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],\n"
        "  'symbols': [0]}]"
    )
    editor.cursor_location = (2, editor.text.splitlines()[2].index(", 1,") + 2)
    count_highlight = app._dht_highlight_from_editor(editor, payload)
    editor.cursor_location = (3, editor.text.splitlines()[3].index("[0") + 1)
    symbol_highlight = app._dht_highlight_from_editor(editor, payload)

    assert count_highlight == (6, 7, "bold black on grey70", "DHT count")
    assert symbol_highlight == (21, 22, "bold black on grey70", "DHT symbol")


def test_dht_struct_cursor_on_key_does_not_highlight(rich_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    seg = segment_by_name(rich_jpeg_bytes, "DHT")
    payload = rich_jpeg_bytes[seg.payload_offset:seg.payload_offset + seg.payload_length]
    editor = FakeTextArea("[{'class': 'DC', 'id': 0, 'counts': [0, 1], 'symbols': [0]}]")
    editor.cursor_location = (0, editor.text.index("'counts'") + 2)

    highlight = app._dht_highlight_from_editor(editor, payload)

    assert highlight is None


def test_dht_selection_changed_updates_active_highlight(rich_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    seg = segment_by_name(rich_jpeg_bytes, "DHT")
    key = "dht-00000000"
    payload = rich_jpeg_bytes[seg.payload_offset:seg.payload_offset + seg.payload_length]
    app.dht_segment_info[key] = (seg.offset, seg.total_length, seg.length_field or 0, seg.payload_offset or 0)
    app.dht_preview_payload[key] = payload
    widgets = workspace_widgets(key, ["tables", "counts", "symbols", "usage", "codes"], "table-edit")
    widgets[f"#{key}-table-edit"].text = (
        "[{'class': 'DC',\n"
        "  'id': 0,\n"
        "  'counts': [0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],\n"
        "  'symbols': [0]}]"
    )
    widgets[f"#{key}-table-edit"].cursor_location = (
        2,
        widgets[f"#{key}-table-edit"].text.splitlines()[2].index(", 1,") + 2,
    )
    widgets[f"#{key}-table-edit"].id = f"{key}-table-edit"
    install_query(app, widgets)

    class DummySelectionEvent:
        def __init__(self, text_area) -> None:
            self.text_area = text_area

    app._on_dqt_selection_changed(DummySelectionEvent(widgets[f"#{key}-table-edit"]))

    assert app.dht_active_highlight[key] == (6, 7, "bold black on grey70", "DHT count")


def test_dht_raw_hex_edit_updates_preview(rich_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    seg = segment_by_name(rich_jpeg_bytes, "DHT")
    key = "dht-00000000"
    app.dht_segment_info[key] = (seg.offset, seg.total_length, seg.length_field or 0, seg.payload_offset or 0)
    widgets = workspace_widgets(key, ["tables", "counts", "symbols", "usage", "codes"], "table-edit")
    widgets[f"#{key}-advanced-mode"].value = True
    raw_payload = bytes([0x00] + [0, 1] + [0] * 14 + [0x2A])
    widgets[f"#{key}-raw-hex"].text = app._bytes_to_hex(raw_payload)
    install_query(app, widgets)

    class DummyTextArea:
        def __init__(self, widget_id: str) -> None:
            self.id = widget_id

    class DummyEvent:
        def __init__(self, widget_id: str) -> None:
            self.text_area = DummyTextArea(widget_id)

    app._on_dht_textarea_changed(DummyEvent(f"{key}-raw-hex"))

    assert app.dht_preview_payload[key] == raw_payload


def test_dht_lenient_preview_shows_warning_for_odd_length_raw_hex() -> None:
    app = JpegFaultTui()
    key = "dht-00000000"
    app.dht_segment_info[key] = (0, 0, 0, 0)
    widgets = workspace_widgets(key, ["tables", "counts", "symbols", "usage", "codes"], "table-edit")
    widgets[f"#{key}-advanced-mode"].value = True
    widgets[f"#{key}-raw-hex"].text = "00 00 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 2"
    install_query(app, widgets)

    app._refresh_dht_preview(key)

    assert widgets[f"#{key}-error"].text.startswith("Warning:")
    assert app.dht_preview_payload[key] == bytes([0x00] + [0, 1] + [0] * 14)


def test_app1_save_uses_shared_segment_write_and_log(
    monkeypatch: pytest.MonkeyPatch, rich_jpeg_path: Path, rich_jpeg_bytes: bytes
) -> None:
    class StubPiexif:
        @staticmethod
        def dump(_data):
            return b"II*\x00\x08\x00\x00\x00\x00\x00\x00\x00"

    monkeypatch.setattr(appn_module, "piexif", StubPiexif)
    app = JpegFaultTui()
    seg = segment_by_name(rich_jpeg_bytes, "APP0")
    key = "app1-00000000"
    app.app1_segment_info[key] = (seg.offset, seg.total_length, seg.length_field or 0, seg.payload_offset or 0)
    widgets = {
        "#input-path": FakeInput(str(rich_jpeg_path)),
        f"#{key}-dict-editor": FakeTextArea("{'0th': {}, 'Exif': {}, 'GPS': {}, '1st': {}, 'Interop': {}, 'thumbnail': b''}"),
        f"#{key}-error": FakeStatic(),
        f"#{key}-save": FakeButton(False),
        f"#info-{key}-raw": FakeLog(),
    }
    install_query(app, widgets)

    class DummyButton:
        id = f"{key}-save"

    class DummyEvent:
        button = DummyButton()

    app._on_app1_save(DummyEvent())

    saved_path = Path(widgets[f"#info-{key}-raw"].text.split(": ", 1)[1])
    saved_bytes = saved_path.read_bytes()
    out_seg = segment_by_name(saved_bytes, "APP0")
    assert saved_path.exists()
    assert saved_path.name.endswith("_app1_edit.jpg")
    assert saved_bytes[out_seg.payload_offset:out_seg.payload_offset + out_seg.payload_length].startswith(b"Exif\x00\x00")
    assert widgets[f"#{key}-save"].disabled is True


def test_app2_save_uses_shared_segment_write_and_log(
    rich_jpeg_path: Path, rich_jpeg_bytes: bytes
) -> None:
    app = JpegFaultTui()
    seg = segment_by_name(rich_jpeg_bytes, "APP0")
    key = "app2-00000000"
    app.app2_segment_info[key] = (seg.offset, seg.total_length, seg.length_field or 0, seg.payload_offset or 0)
    app.app2_original_payload[key] = _build_test_app2_payload()
    widgets = {
        "#input-path": FakeInput(str(rich_jpeg_path)),
        f"#{key}-desc-input": FakeInput("Updated profile"),
        f"#{key}-cprt-input": FakeInput(""),
        f"#{key}-dmnd-input": FakeInput(""),
        f"#{key}-dmdd-input": FakeInput(""),
        f"#{key}-wtpt-input": FakeInput(""),
        f"#{key}-bkpt-input": FakeInput(""),
        f"#{key}-rxyz-input": FakeInput(""),
        f"#{key}-gxyz-input": FakeInput(""),
        f"#{key}-bxyz-input": FakeInput(""),
        f"#{key}-rtrc-input": FakeInput(""),
        f"#{key}-gtrc-input": FakeInput(""),
        f"#{key}-btrc-input": FakeInput(""),
        f"#{key}-error": FakeStatic(),
        f"#{key}-save": FakeButton(False),
        f"#info-{key}-raw": FakeLog(),
    }
    install_query(app, widgets)

    class DummyButton:
        id = f"{key}-save"

    class DummyEvent:
        button = DummyButton()

    app._on_app2_save(DummyEvent())

    saved_path = Path(widgets[f"#info-{key}-raw"].text.split(": ", 1)[1])
    saved_bytes = saved_path.read_bytes()
    out_seg = segment_by_name(saved_bytes, "APP0")
    assert saved_path.exists()
    assert saved_path.name.endswith("_app2_edit.jpg")
    assert saved_bytes[out_seg.payload_offset:out_seg.payload_offset + out_seg.payload_length].startswith(b"ICC_PROFILE\x00")
    assert widgets[f"#{key}-save"].disabled is True


@pytest.mark.parametrize(
    ("builder", "text", "message"),
    [
        ("_build_sof0_payload", "{'precision_bits': 8, 'width': 1, 'height': 1, 'components': ['bad']}", "component 1"),
        ("_build_dri_payload", "{'restart_interval': 70000}", "0..65535"),
        ("_build_dqt_payload", "[{'id': 0, 'precision_bits': 8, 'grid': [[1]]}]", "8x8"),
        (
            "_build_dht_payload",
            "[{'class': 'DC', 'id': 0, 'counts': [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], 'symbols': [1]}]",
            "symbol count",
        ),
    ],
)
def test_editor_validation_errors(builder: str, text: str, message: str) -> None:
    app = JpegFaultTui()
    widgets = {
        "#sof0-advanced-mode": FakeCheckbox(False),
        "#sof0-struct-edit": FakeTextArea(text),
        "#dri-advanced-mode": FakeCheckbox(False),
        "#dri-struct-edit": FakeTextArea(text),
        "#dqt-00000000-advanced-mode": FakeCheckbox(False),
        "#dqt-00000000-grid-edit": FakeTextArea(text),
        "#dht-00000000-advanced-mode": FakeCheckbox(False),
        "#dht-00000000-table-edit": FakeTextArea(text),
    }
    install_query(app, widgets)
    with pytest.raises(ValueError, match=message):
        getattr(app, builder)("dqt-00000000" if "dqt" in builder else "dht-00000000") if "dqt" in builder or "dht" in builder else getattr(app, builder)()


def test_manual_length_warnings() -> None:
    app = JpegFaultTui()
    widgets = {
        "#info-sof0-left": FakeLog(),
        "#sof0-manual-length": FakeCheckbox(True),
        "#info-dri-left": FakeLog(),
        "#dri-manual-length": FakeCheckbox(True),
        "#info-dqt-00000000-left": FakeLog(),
        "#dqt-00000000-manual-length": FakeCheckbox(True),
        "#info-dht-00000000-left": FakeLog(),
        "#dht-00000000-manual-length": FakeCheckbox(True),
    }
    install_query(app, widgets)

    app._sof0_save_log(Path("a.jpg"), b"\x00" * 15, 99)
    app._dri_save_log(Path("b.jpg"), b"\x00" * 2, 99)
    app._dqt_save_log("dqt-00000000", Path("c.jpg"), b"\x00" * 65, 99)
    app._dht_save_log("dht-00000000", Path("d.jpg"), b"\x00" * 18, 99)

    assert "Warning" in widgets["#info-sof0-left"].text
    assert "Warning" in widgets["#info-dri-left"].text
    assert "Warning" in widgets["#info-dqt-00000000-left"].text
    assert "Warning" in widgets["#info-dht-00000000-left"].text


def test_segment_absence_states() -> None:
    app = JpegFaultTui()
    widgets = workspace_widgets("sof0", ["frame", "components", "tables"], "struct-edit")
    widgets.update(workspace_widgets("dri", ["summary", "effect"], "struct-edit"))
    widgets["#dht-tabs"] = FakeTabs()
    widgets["#info-dht-empty"] = FakeLog()
    widgets["#dqt-tabs"] = FakeTabs()
    widgets["#info-dqt-empty"] = FakeLog()
    install_query(app, widgets)

    app._render_sof0_segment(bytes([0xFF, 0xD8, 0xFF, 0xD9]), [])
    app._render_dri_segment(bytes([0xFF, 0xD8, 0xFF, 0xD9]), [])
    app._reset_dht_tabs([])
    app._reset_dqt_tabs([])

    assert "No SOF0 segment found." in widgets["#info-sof0-left"].text
    assert "No DRI segment found." in widgets["#info-dri-left"].text
    assert "No DHT segments found." in widgets["#info-dht-empty"].text
    assert "No DQT segments found." in widgets["#info-dqt-empty"].text


def test_reset_sof_tabs_handles_no_segments() -> None:
    app = JpegFaultTui()
    widgets = {"#sof-tabs": FakeTabs(), "#info-sof-empty": FakeLog()}
    install_query(app, widgets)

    targets = app._reset_sof_tabs([])

    assert targets == []
    assert widgets["#sof-tabs"].panes == ["SOFn"]
    assert "No SOF segments found." in widgets["#info-sof-empty"].text


def test_segments_list_includes_unused_sections(rich_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    segs, ents = jp.parse_jpeg(rich_jpeg_bytes)
    log = FakeLog()

    app._write_segments(log, segs, ents, rich_jpeg_bytes)

    assert "Unused sections:" in log.text
    assert "APP1" in log.text
    assert "SOF1" in log.text


def test_multi_segment_tabs_created() -> None:
    app = JpegFaultTui()
    widgets = {"#sof-tabs": FakeTabs(), "#dqt-tabs": FakeTabs(), "#dht-tabs": FakeTabs()}
    widgets["#sof0-tabs"] = FakeTabs()
    widgets["#sof-00000064-tabs"] = FakeTabs()
    widgets["#dqt-0000000A-tabs"] = FakeTabs()
    widgets["#dqt-00000064-tabs"] = FakeTabs()
    widgets["#dht-00000014-tabs"] = FakeTabs()
    widgets["#dht-00000050-tabs"] = FakeTabs()
    install_query(app, widgets)
    sof_segments = [Segment(0xC0, 10, "SOF0", 17, 14, 15, 19), Segment(0xC2, 100, "SOF2", 17, 104, 15, 19)]
    dqt_segments = [Segment(0xDB, 10, "DQT", 67, 14, 65, 69), Segment(0xDB, 100, "DQT", 67, 104, 65, 69)]
    dht_segments = [Segment(0xC4, 20, "DHT", 20, 24, 18, 22), Segment(0xC4, 80, "DHT", 20, 84, 18, 22)]

    sof_targets = app._reset_sof_tabs(sof_segments)
    dqt_targets = app._reset_dqt_tabs(dqt_segments)
    dht_targets = app._reset_dht_tabs(dht_segments)

    assert len(sof_targets) == 2
    assert len(dqt_targets) == 2
    assert len(dht_targets) == 2
    assert widgets["#sof-tabs"].panes == ["SOF0 #1", "SOF2 #2"]
    assert widgets["#dqt-tabs"].panes == ["DQT #1", "DQT #2"]
    assert widgets["#dht-tabs"].panes == ["DHT #1", "DHT #2"]

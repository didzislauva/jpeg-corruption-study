from __future__ import annotations

from pathlib import Path

import pytest

from jpeg_fault.core import jpeg_parse as jp
from jpeg_fault.core.models import Segment
from jpeg_fault.core.tui import JpegFaultTui


class FakeLog:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def clear(self) -> None:
        self.messages.clear()

    def write(self, value) -> None:
        self.messages.append(str(value))

    @property
    def text(self) -> str:
        return "\n".join(self.messages)


class FakeTextArea:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.display = True


class FakeInput:
    def __init__(self, value: str = "") -> None:
        self.value = value
        self.disabled = False


class FakeCheckbox:
    def __init__(self, value: bool = False) -> None:
        self.value = value


class FakeButton:
    def __init__(self, disabled: bool = False) -> None:
        self.disabled = disabled


class FakeStatic:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.display = True

    def update(self, value: str) -> None:
        self.text = value


class FakeTabs:
    def __init__(self) -> None:
        self.panes: list[str] = []
        self.shown = None

    def clear_panes(self) -> None:
        self.panes.clear()

    def add_pane(self, pane) -> None:
        self.panes.append(pane._title)

    def show_tab(self, pane_id) -> None:
        self.shown = pane_id


def _install_query(app: JpegFaultTui, widgets: dict[str, object]) -> None:
    def fake_query(selector: str, *args, **kwargs):
        if selector not in widgets:
            raise AssertionError(f"unexpected selector {selector}")
        return widgets[selector]

    app.query_one = fake_query  # type: ignore[assignment]


def _segment_by_name(data: bytes, name: str) -> Segment:
    segments, _ = jp.parse_jpeg(data)
    return next(seg for seg in segments if seg.name == name)


def _workspace_widgets(prefix: str, tabs: list[str], edit_id: str, keyed: bool = False) -> dict[str, object]:
    widgets: dict[str, object] = {f"#info-{prefix}-left": FakeLog()}
    for tab in tabs:
        widgets[f"#info-{prefix}-{tab}"] = FakeLog()
    widgets[f"#{prefix}-raw-hex"] = FakeTextArea()
    widgets[f"#{prefix}-{edit_id}"] = FakeTextArea()
    widgets[f"#{prefix}-length"] = FakeInput()
    widgets[f"#{prefix}-advanced-mode"] = FakeCheckbox(False)
    widgets[f"#{prefix}-manual-length"] = FakeCheckbox(False)
    widgets[f"#{prefix}-save"] = FakeButton(True)
    widgets[f"#{prefix}-error"] = FakeStatic()
    widgets[f"#{prefix}-edit-error"] = FakeStatic()
    widgets[f"#{prefix}-simple-title"] = FakeStatic()
    widgets[f"#{prefix}-adv-title"] = FakeStatic()
    return widgets


def test_tui_compose_smoke() -> None:
    app = JpegFaultTui()
    assert app.defaults.output_dir == "mutations"
    assert app.current_panel == "input"


def test_render_sof0_workspace(rich_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    widgets = _workspace_widgets("sof0", ["frame", "components", "tables"], "struct-edit")
    _install_query(app, widgets)

    app._render_sof0_segment(rich_jpeg_bytes, jp.parse_jpeg(rich_jpeg_bytes)[0])

    assert "Frame: 8x8 precision=8 components=3" in widgets["#info-sof0-left"].text
    assert "Width: 8" in widgets["#info-sof0-frame"].text
    assert "Component 1 (Y / luma)" in widgets["#info-sof0-components"].text
    assert "Quantization table id=0" in widgets["#info-sof0-tables"].text


def test_render_dri_workspace(rich_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    widgets = _workspace_widgets("dri", ["summary", "effect"], "struct-edit")
    _install_query(app, widgets)

    app._render_dri_segment(rich_jpeg_bytes, jp.parse_jpeg(rich_jpeg_bytes)[0])

    assert "Restart interval: 4 MCUs" in widgets["#info-dri-left"].text
    assert "Enabled: yes" in widgets["#info-dri-summary"].text
    assert "every 4 MCUs" in widgets["#info-dri-effect"].text


def test_render_dqt_workspace_and_usage(rich_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    app.info_data = rich_jpeg_bytes
    app.info_segments = jp.parse_jpeg(rich_jpeg_bytes)[0]
    key = "dqt-00000000"
    widgets = _workspace_widgets(key, ["grid", "zigzag", "stats", "usage", "heatmap"], "grid-edit", keyed=True)
    _install_query(app, widgets)

    app._render_dqt_segment(rich_jpeg_bytes, _segment_by_name(rich_jpeg_bytes, "DQT"), key)

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
    widgets = _workspace_widgets(key, ["tables", "counts", "symbols", "usage", "codes"], "table-edit", keyed=True)
    _install_query(app, widgets)

    app._render_dht_segment(rich_jpeg_bytes, _segment_by_name(rich_jpeg_bytes, "DHT"), key)

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
    _install_query(app, widgets)
    app._build_app0_payload = lambda: b"JFIF\x00\x01\x02\x01\x00\x48\x00\x48\x00\x00"  # type: ignore[assignment]

    app._refresh_app0_preview()

    assert "APP0 at 0x00000000" in widgets["#info-app0"].text
    assert "Identifier: JFIF\\0" in widgets["#info-app0"].text


def test_sof0_preview_and_save(tmp_path: Path, rich_jpeg_path: Path, rich_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    seg = _segment_by_name(rich_jpeg_bytes, "SOF0")
    app.sof0_segment_info = (seg.offset, seg.total_length, seg.length_field or 0, seg.payload_offset or 0)
    widgets = _workspace_widgets("sof0", ["frame", "components", "tables"], "struct-edit")
    widgets["#input-path"] = FakeInput(str(rich_jpeg_path))
    widgets["#sof0-struct-edit"].text = (
        "{'precision_bits': 8, 'width': 16, 'height': 8, "
        "'components': [{'id': 1, 'h_sampling': 2, 'v_sampling': 2, 'quant_table_id': 0}, "
        "{'id': 2, 'h_sampling': 1, 'v_sampling': 1, 'quant_table_id': 0}, "
        "{'id': 3, 'h_sampling': 1, 'v_sampling': 1, 'quant_table_id': 0}]}"
    )
    _install_query(app, widgets)

    app._refresh_sof0_preview()
    assert "Width: 16" in widgets["#info-sof0-frame"].text

    input_path, payload, length_field = app._sof0_save_inputs()
    out_path = app._sof0_write_file(input_path, payload, length_field)
    out_seg = _segment_by_name(out_path.read_bytes(), "SOF0")
    assert out_path.exists()
    assert out_path != rich_jpeg_path
    assert out_path.read_bytes()[out_seg.payload_offset:out_seg.payload_offset + out_seg.payload_length] == payload


def test_dri_preview_and_save(rich_jpeg_path: Path, rich_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    seg = _segment_by_name(rich_jpeg_bytes, "DRI")
    app.dri_segment_info = (seg.offset, seg.total_length, seg.length_field or 0, seg.payload_offset or 0)
    widgets = _workspace_widgets("dri", ["summary", "effect"], "struct-edit")
    widgets["#input-path"] = FakeInput(str(rich_jpeg_path))
    widgets["#dri-struct-edit"].text = "{'restart_interval': 9}"
    _install_query(app, widgets)

    app._refresh_dri_preview()
    assert "9 MCUs" in widgets["#info-dri-summary"].text

    input_path, payload, length_field = app._dri_save_inputs()
    out_path = app._dri_write_file(input_path, payload, length_field)
    out_seg = _segment_by_name(out_path.read_bytes(), "DRI")
    assert out_path.read_bytes()[out_seg.payload_offset:out_seg.payload_offset + out_seg.payload_length] == payload


def test_dqt_preview_save_and_mode_switch_sync(rich_jpeg_path: Path, rich_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    seg = _segment_by_name(rich_jpeg_bytes, "DQT")
    key = "dqt-00000000"
    app.dqt_segment_info[key] = (seg.offset, seg.total_length, seg.length_field or 0, seg.payload_offset or 0)
    widgets = _workspace_widgets(key, ["grid", "zigzag", "stats", "usage", "heatmap"], "grid-edit", keyed=True)
    widgets["#input-path"] = FakeInput(str(rich_jpeg_path))
    widgets[f"#{key}-grid-edit"].text = (
        "[{'id': 0, 'precision_bits': 8, 'grid': [[1,1,1,1,1,1,1,1],"
        "[1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1],"
        "[1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1]]}]"
    )
    _install_query(app, widgets)

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
    out_seg = _segment_by_name(out_path.read_bytes(), "DQT")
    assert out_path.read_bytes()[out_seg.payload_offset:out_seg.payload_offset + out_seg.payload_length] == payload


def test_dht_preview_save_and_mode_switch_sync(rich_jpeg_path: Path, rich_jpeg_bytes: bytes) -> None:
    app = JpegFaultTui()
    seg = _segment_by_name(rich_jpeg_bytes, "DHT")
    key = "dht-00000000"
    app.dht_segment_info[key] = (seg.offset, seg.total_length, seg.length_field or 0, seg.payload_offset or 0)
    widgets = _workspace_widgets(key, ["tables", "counts", "symbols", "usage", "codes"], "table-edit", keyed=True)
    widgets["#input-path"] = FakeInput(str(rich_jpeg_path))
    widgets[f"#{key}-table-edit"].text = (
        "[{'class': 'DC', 'id': 0, 'counts': [0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], 'symbols': [42]}]"
    )
    _install_query(app, widgets)

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
    out_seg = _segment_by_name(out_path.read_bytes(), "DHT")
    assert out_path.read_bytes()[out_seg.payload_offset:out_seg.payload_offset + out_seg.payload_length] == payload


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
    _install_query(app, widgets)
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
    _install_query(app, widgets)

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
    widgets = _workspace_widgets("sof0", ["frame", "components", "tables"], "struct-edit")
    widgets.update(_workspace_widgets("dri", ["summary", "effect"], "struct-edit"))
    widgets["#dht-tabs"] = FakeTabs()
    widgets["#info-dht-empty"] = FakeLog()
    widgets["#dqt-tabs"] = FakeTabs()
    widgets["#info-dqt-empty"] = FakeLog()
    _install_query(app, widgets)

    app._render_sof0_segment(bytes([0xFF, 0xD8, 0xFF, 0xD9]), [])
    app._render_dri_segment(bytes([0xFF, 0xD8, 0xFF, 0xD9]), [])
    app._reset_dht_tabs([])
    app._reset_dqt_tabs([])

    assert "No SOF0 segment found." in widgets["#info-sof0-left"].text
    assert "No DRI segment found." in widgets["#info-dri-left"].text
    assert "No DHT segments found." in widgets["#info-dht-empty"].text
    assert "No DQT segments found." in widgets["#info-dqt-empty"].text


def test_multi_segment_tabs_created() -> None:
    app = JpegFaultTui()
    widgets = {"#dqt-tabs": FakeTabs(), "#dht-tabs": FakeTabs()}
    widgets["#dqt-0000000A-tabs"] = FakeTabs()
    widgets["#dqt-00000064-tabs"] = FakeTabs()
    widgets["#dht-00000014-tabs"] = FakeTabs()
    widgets["#dht-00000050-tabs"] = FakeTabs()
    _install_query(app, widgets)
    dqt_segments = [Segment(0xDB, 10, "DQT", 67, 14, 65, 69), Segment(0xDB, 100, "DQT", 67, 104, 65, 69)]
    dht_segments = [Segment(0xC4, 20, "DHT", 20, 24, 18, 22), Segment(0xC4, 80, "DHT", 20, 84, 18, 22)]

    dqt_targets = app._reset_dqt_tabs(dqt_segments)
    dht_targets = app._reset_dht_tabs(dht_segments)

    assert len(dqt_targets) == 2
    assert len(dht_targets) == 2
    assert widgets["#dqt-tabs"].panes == ["DQT #1", "DQT #2"]
    assert widgets["#dht-tabs"].panes == ["DHT #1", "DHT #2"]

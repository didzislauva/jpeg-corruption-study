import pytest

from jpeg_fault.core.models import Segment
from jpeg_fault.core.tui import JpegFaultTui
from tests.tui_test_helpers import FakeInput, install_query


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


def test_app2_input_changed_refreshes_for_xyz_and_trc_fields() -> None:
    app = JpegFaultTui()
    calls: list[str] = []
    app._refresh_app2_preview = lambda key: calls.append(key)  # type: ignore[assignment]

    class DummyInput:
        id = "app2-00000000-gxyz-input"

    class DummyEvent:
        input = DummyInput()

    app._on_app2_input_changed(DummyEvent())

    assert calls == ["app2-00000000"]


def test_app2_collect_updates_builds_text_xyz_and_gamma_updates() -> None:
    app = JpegFaultTui()
    key = "app2-00000000"
    widgets = {
        f"#{key}-desc-input": FakeInput("Display P3"),
        f"#{key}-cprt-input": FakeInput("Copyright"),
        f"#{key}-dmnd-input": FakeInput("OpenAI"),
        f"#{key}-dmdd-input": FakeInput("Model X"),
        f"#{key}-wtpt-input": FakeInput("0.9642,1.0,0.8249"),
        f"#{key}-bkpt-input": FakeInput("0.0,0.0,0.0"),
        f"#{key}-rxyz-input": FakeInput("0.4361,0.2225,0.0139"),
        f"#{key}-gxyz-input": FakeInput("0.3851,0.7169,0.0971"),
        f"#{key}-bxyz-input": FakeInput("0.1431,0.0606,0.7141"),
        f"#{key}-rtrc-input": FakeInput("2.2"),
        f"#{key}-gtrc-input": FakeInput("2.2"),
        f"#{key}-btrc-input": FakeInput("2.2"),
    }
    install_query(app, widgets)
    app.app2_tag_types[key] = {"desc": "desc", "cprt": "text"}

    updates = app._app2_collect_updates(key)

    assert set(updates) == {
        "desc",
        "cprt",
        "dmnd",
        "dmdd",
        "wtpt",
        "bkpt",
        "rXYZ",
        "gXYZ",
        "bXYZ",
        "rTRC",
        "gTRC",
        "bTRC",
    }


def test_set_input_path_value_loads_once_when_programmatic_selection(tmp_path) -> None:
    app = JpegFaultTui()
    input_path = tmp_path / "sample.jpg"
    input_path.write_bytes(b"\xff\xd8\xff\xd9")
    widgets = {"#input-path": FakeInput("")}
    install_query(app, widgets)
    calls: list[str] = []
    app._load_selected_input_path = lambda path: calls.append(path)  # type: ignore[assignment]

    app._set_input_path_value(str(input_path))

    assert widgets["#input-path"].value == str(input_path)
    assert calls == [str(input_path)]


def test_input_path_changed_is_ignored_while_programmatic_update_is_suppressed() -> None:
    app = JpegFaultTui()
    calls: list[str] = []
    app._load_selected_input_path = lambda path: calls.append(path)  # type: ignore[assignment]
    app._suppress_input_path_changed = True

    class DummyInput:
        value = "/tmp/example.jpg"

    class DummyEvent:
        input = DummyInput()

    app._on_input_path_changed(DummyEvent())

    assert calls == []


def test_app1_ifd_textarea_change_ignores_missing_widgets() -> None:
    app = JpegFaultTui()
    calls: list[tuple[str, bool]] = []
    app._set_app1_dirty = lambda key, dirty: calls.append((key, dirty))  # type: ignore[assignment]
    install_query(app, {})

    class DummyTextArea:
        id = "app1-00000014-ifd0-editor"

    class DummyEvent:
        text_area = DummyTextArea()

    app._on_app1_textarea_changed(DummyEvent())

    assert calls == []


def test_set_app1_dirty_ignores_missing_save_button() -> None:
    app = JpegFaultTui()
    install_query(app, {})

    app._set_app1_dirty("app1-00000014", True)

    assert app.app1_dirty["app1-00000014"] is True

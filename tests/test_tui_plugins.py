from __future__ import annotations

from pathlib import Path

from jpeg_fault.core.analysis_registry import clear_registry_for_tests, register
from jpeg_fault.core.analysis_types import AnalysisContext, AnalysisResult, AnalysisPlugin
from jpeg_fault.core.tui import JpegFaultTui
from jpeg_fault.core.tui_plugin_registry import clear_tui_plugins_for_tests, register_tui_plugin
from jpeg_fault.core.tui_plugin_types import TuiPluginSpec
from textual.widgets import ListItem
from tests.tui_test_helpers import FakeCheckbox, FakeInput, FakeStatic, install_query


class FakeMenu:
    def __init__(self) -> None:
        self.item_ids: list[str] = []

    def append(self, item) -> None:
        self.item_ids.append(item.id)


class FakePanel:
    def __init__(self) -> None:
        self.children: list[object] = []

    def mount(self, widget) -> None:
        self.children.append(widget)


class FakeTabs:
    def __init__(self, id: str | None = None) -> None:
        self.id = id
        self.panes: list[str] = []

    def add_pane(self, pane) -> None:
        self.panes.append(pane._title)


class FakeTabPane:
    def __init__(self, title: str, content) -> None:
        self._title = title
        self.content = content


def test_init_plugin_panels_adds_menu_and_tabs(monkeypatch) -> None:
    clear_tui_plugins_for_tests()
    register_tui_plugin(
        TuiPluginSpec(
            id="entropy_wave",
            label="Entropy Wave Chart",
            panel_id="graphic-output",
            panel_label="Graphic Output",
            tab_label="Entropy Wave",
            build_tab=lambda _app: object(),
        )
    )

    app = JpegFaultTui()
    menu = FakeMenu()
    panel = FakePanel()

    def fake_query(selector: str, *args, **kwargs):
        if selector == "#menu":
            return menu
        if selector == "#panel":
            return panel
        raise AssertionError(f"unexpected selector {selector}")

    app.query_one = fake_query  # type: ignore[assignment]
    app.call_after_refresh = lambda fn, *a, **k: fn(*a, **k)  # type: ignore[assignment]

    import jpeg_fault.core.tui_app as tui_app

    monkeypatch.setattr(tui_app, "TabbedContent", FakeTabs)
    monkeypatch.setattr(tui_app, "TabPane", FakeTabPane)

    app._init_plugin_panels()

    assert "menu-plugin-graphic-output" in menu.item_ids
    assert "graphic-output" in app.plugin_panels
    tabs = app.plugin_panel_tabs["graphic-output"]
    assert "Entropy Wave" in tabs.panes


def test_append_list_view_item_supports_append_and_add_item() -> None:
    app = JpegFaultTui()

    class AppendOnlyMenu:
        def __init__(self) -> None:
            self.item_ids: list[str] = []

        def append(self, item) -> None:
            self.item_ids.append(item.id)

    class AddOnlyMenu:
        def __init__(self) -> None:
            self.item_ids: list[str] = []

        def add_item(self, item) -> None:
            self.item_ids.append(item.id)

    append_menu = AppendOnlyMenu()
    add_menu = AddOnlyMenu()

    app._append_list_view_item(append_menu, ListItem(id="x"))
    app._append_list_view_item(add_menu, ListItem(id="y"))

    assert append_menu.item_ids == ["x"]
    assert add_menu.item_ids == ["y"]


def test_menu_selected_shows_plugin_panel() -> None:
    app = JpegFaultTui()

    class FakePanelWidget:
        def __init__(self) -> None:
            self.display = False

    widgets = {
        "#panel-input": FakePanelWidget(),
        "#panel-info": FakePanelWidget(),
        "#panel-tools": FakePanelWidget(),
        "#panel-mutation": FakePanelWidget(),
        "#panel-strategy": FakePanelWidget(),
        "#panel-outputs": FakePanelWidget(),
        "#panel-plugins": FakePanelWidget(),
        "#panel-run": FakePanelWidget(),
    }

    def fake_query(selector: str, *args, **kwargs):
        if selector not in widgets:
            raise AssertionError(f"unexpected selector {selector}")
        return widgets[selector]

    app.query_one = fake_query  # type: ignore[assignment]
    app.plugin_panels["graphic-output"] = FakePanelWidget()
    app.plugin_panels["other"] = FakePanelWidget()

    class Event:
        item = type("Item", (), {"id": "menu-plugin-graphic-output"})()

    app._on_menu_selected(Event())

    assert app.current_panel == "plugin-graphic-output"
    assert app.plugin_panels["graphic-output"].display is True
    assert app.plugin_panels["other"].display is False
    assert widgets["#panel-input"].display is False


def test_run_plugin_uses_params(tmp_path: Path) -> None:
    clear_registry_for_tests()

    calls: dict[str, object] = {}

    class DummyPlugin(AnalysisPlugin):
        id = "dummy"
        label = "Dummy"
        supported_formats = {"jpeg"}
        requires_mutations = False

        def run(self, input_path: str, context: AnalysisContext) -> AnalysisResult:
            calls["input_path"] = input_path
            calls["params"] = context.params
            return AnalysisResult(self.id, [str(context.params.get("out_path"))])

    register(DummyPlugin())

    app = JpegFaultTui()
    input_path = tmp_path / "in.jpg"
    input_path.write_bytes(b"\xFF\xD8\xFF\xD9")

    status = FakeStatic()
    widgets = {
        "#input-path": FakeInput(str(input_path)),
        "#output-dir": FakeInput(str(tmp_path)),
        "#debug": FakeCheckbox(False),
        "#plugin-dummy-out": FakeInput(str(tmp_path / "custom.png")),
        "#plugin-dummy-status": status,
    }
    install_query(app, widgets)

    app.call_from_thread = lambda fn, *a, **k: fn(*a, **k)  # type: ignore[assignment]
    app.run_worker = lambda fn, **kwargs: fn()  # type: ignore[assignment]

    app._run_plugin("dummy")

    assert calls["input_path"] == str(input_path)
    assert calls["params"] == {"out_path": str(tmp_path / "custom.png")}
    assert "Done" in status.text

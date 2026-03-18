from __future__ import annotations

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


class FakeRichLog(FakeLog):
    def scroll_to(self, *_args, **_kwargs) -> None:
        return


class FakeTextArea:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.display = True
        self.cursor_location = (0, 0)


class FakeInput:
    def __init__(self, value: str = "") -> None:
        self.value = value
        self.disabled = False


class FakeCheckbox:
    def __init__(self, value: bool = False) -> None:
        self.value = value


class FakeSelect:
    def __init__(self, value=None) -> None:
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


class FakeListView:
    def __init__(self) -> None:
        self.items: list[object] = []

    def clear(self) -> None:
        self.items.clear()

    def append(self, item) -> None:
        self.items.append(item)


def install_query(app: JpegFaultTui, widgets: dict[str, object]) -> None:
    def fake_query(selector: str, *args, **kwargs):
        if selector not in widgets:
            raise AssertionError(f"unexpected selector {selector}")
        return widgets[selector]

    app.query_one = fake_query  # type: ignore[assignment]


def segment_by_name(data: bytes, name: str) -> Segment:
    segments, _ = jp.parse_jpeg(data)
    return next(seg for seg in segments if seg.name == name)


def workspace_widgets(prefix: str, tabs: list[str], edit_id: str) -> dict[str, object]:
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

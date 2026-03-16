"""
Textual-based fullscreen TUI for the JPEG fault tolerance tool.

The TUI is designed for interactive use and mirrors the CLI options, allowing
users to select input files, mutation strategies, outputs, and then execute the
run via the core API layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple
import ast

try:
    import piexif
except ImportError:  # pragma: no cover - optional dependency
    piexif = None

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widgets import (
    Button,
    Checkbox,
    DirectoryTree,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Select,
    Static,
    RichLog,
    TabbedContent,
    TabPane,
    TextArea,
)
from textual.worker import Worker, WorkerState
from rich.text import Text

from . import api
from .jpeg_parse import decode_app0, parse_jpeg
from .mutate import total_entropy_length
from .report import explain_segment
from .tools import insert_custom_appn, output_path_for, read_payload_hex


@dataclass
class TuiDefaults:
    """
    Default values for the TUI inputs, aligned with CLI defaults.
    """

    input_path: str = ""
    output_dir: str = "mutations"
    mutate: str = "add1"
    sample: int = 100
    seed: int = 3
    mutation_apply: str = "independent"
    repeats: int = 1
    step: int = 1
    overflow_wrap: bool = False
    report_only: bool = False
    color: str = "auto"
    gif: str = ""
    gif_fps: int = 10
    gif_loop: int = 0
    gif_shuffle: bool = False
    ssim_chart: str = ""
    metrics: str = "ssim"
    metrics_chart_prefix: str = ""
    jobs: str = ""
    wave_chart: str = ""
    sliding_wave_chart: str = ""
    wave_window: int = 256
    dc_heatmap: str = ""
    ac_energy_heatmap: str = ""
    debug: bool = False


class JpegOnlyDirTree(DirectoryTree):
    """
    DirectoryTree that shows directories only (no files).
    """

    def filter_paths(self, paths):
        return [p for p in paths if Path(p).is_dir()]


class JpegFaultTui(App):
    """
    Fullscreen TUI that collects options and runs the JPEG fault tolerance pipeline.
    """

    CSS = """
    Screen { layout: vertical; }
    #body { height: 1fr; }
    #menu { width: 24; border: solid $primary; }
    #panel { width: 1fr; border: solid $primary; }
    .panel-title { margin: 1 0; }
    .field { margin: 0 0 1 0; }
    .row { height: auto; }
    #log { height: 1fr; border: solid $secondary; }
    #app0-info { width: 1fr; border: solid $secondary; }
    #app0-edit { width: 1fr; border: solid $secondary; }
    #app0-col-left { width: 1fr; }
    #app0-col-right { width: 1fr; }
    #app0-raw-hex { height: 10; }
    #app0-thumb-hex { height: 5; }
    .appn-info { width: 1fr; border: solid $secondary; }
    """

    BINDINGS = [("q", "quit", "Quit")]

    current_panel = reactive("input")
    current_dir = reactive(".")
    app0_original_payload: Optional[bytes] = None
    app0_segment_info: Optional[Tuple[int, int, int, int]] = None
    app0_dirty = reactive(False)
    app1_segment_info: dict[str, Tuple[int, int, int, int]] = {}
    app1_original_payload: dict[str, bytes] = {}
    app1_preview_payload: dict[str, bytes] = {}
    app1_dirty: dict[str, bool] = {}
    app1_exif_dict: dict[str, dict] = {}
    _app1_syncing = False
    info_data: Optional[bytes] = None
    info_segments: Optional[list] = None
    hex_page = reactive(0)
    hex_legend_offsets: dict[str, int] = {}
    hex_legend_counter = reactive(0)

    def __init__(self, defaults: Optional[TuiDefaults] = None) -> None:
        super().__init__()
        self.defaults = defaults or TuiDefaults()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            with ListView(id="menu"):
                yield ListItem(Label("Input & Output"), id="menu-input")
                yield ListItem(Label("Info"), id="menu-info")
                yield ListItem(Label("Tools"), id="menu-tools")
                yield ListItem(Label("Mutation"), id="menu-mutation")
                yield ListItem(Label("Strategy"), id="menu-strategy")
                yield ListItem(Label("Outputs"), id="menu-outputs")
                yield ListItem(Label("Run"), id="menu-run")
            with Container(id="panel"):
                yield self._build_input_panel()
                yield self._build_info_panel()
                yield self._build_tools_panel()
                yield self._build_mutation_panel()
                yield self._build_strategy_panel()
                yield self._build_outputs_panel()
                yield self._build_run_panel()
        yield Footer()

    def on_mount(self) -> None:
        """
        Select the first menu item on startup to show the initial panel.
        """
        menu = self.query_one("#menu", ListView)
        menu.index = 0
        self._show_panel("input")
        self._set_current_dir(Path("."))
        self.call_later(self._init_info_tabs)
        self.call_later(self._apply_app0_mode_visibility)

    def _build_input_panel(self) -> VerticalScroll:
        panel = VerticalScroll(
            Label("Input & Output", classes="panel-title"),
            Static(
                "Browse folders on the left; JPEG files are listed below. "
                "Selecting a JPEG sets the input path.",
                classes="field",
                id="input-info",
            ),
            Label("Current directory", classes="field"),
            Static(".", id="current-dir"),
            JpegOnlyDirTree(".", id="file-tree"),
            Label("JPEG files", classes="field"),
            ListView(id="jpg-list"),
            Label("Input JPEG path", classes="field"),
            Input(value=self.defaults.input_path, id="input-path"),
            Label("Output directory", classes="field"),
            Input(value=self.defaults.output_dir, id="output-dir"),
            Label("Color mode (auto|always|never)", classes="field"),
            Input(value=self.defaults.color, id="color-mode"),
            id="panel-input",
        )
        panel.display = True
        return panel

    def _build_mutation_panel(self) -> VerticalScroll:
        panel = VerticalScroll(
            Label("Mutation", classes="panel-title"),
            Static("Select how bytes are mutated and sampled.", classes="field"),
            Label("Mutation mode", classes="field"),
            Input(value=self.defaults.mutate, id="mutate-mode"),
            Label("Sample (0 = all/maximum)", classes="field"),
            Input(value=str(self.defaults.sample), id="sample"),
            Label("Seed", classes="field"),
            Input(value=str(self.defaults.seed), id="seed"),
            Checkbox("Overflow wrap (add1/sub1)", value=self.defaults.overflow_wrap, id="overflow-wrap"),
            Checkbox("Report only", value=self.defaults.report_only, id="report-only"),
            Checkbox("Debug logging", value=self.defaults.debug, id="debug"),
            id="panel-mutation",
        )
        panel.display = False
        return panel

    def _build_tools_panel(self) -> VerticalScroll:
        panel = VerticalScroll(
            Label("Tools", classes="panel-title"),
            Static("Utility helpers for manipulating JPEG files.", classes="field"),
            TabbedContent(id="tools-tabs"),
            id="panel-tools",
        )
        panel.display = False
        return panel
    def _build_info_panel(self) -> VerticalScroll:
        panel = VerticalScroll(
            Label("Info", classes="panel-title"),
            Static(
                "Load and inspect JPEG structure details for the current input path.",
                classes="field",
            ),
            Button("Load Info", id="load-info", variant="primary"),
            Static("", id="info-error"),
            TabbedContent(id="info-tabs"),
            id="panel-info",
        )
        panel.display = False
        return panel

    def _build_strategy_panel(self) -> VerticalScroll:
        panel = VerticalScroll(
            Label("Strategy", classes="panel-title"),
            Static("Choose how mutations are applied across outputs.", classes="field"),
            Label("Mutation application strategy", classes="field"),
            Select(
                [
                    ("independent", "independent"),
                    ("cumulative", "cumulative"),
                    ("sequential", "sequential"),
                ],
                value=self.defaults.mutation_apply,
                id="mutation-apply",
            ),
            Label("Repeats (cumulative/sequential)", classes="field"),
            Input(value=str(self.defaults.repeats), id="repeats"),
            Label("Step (cumulative/sequential)", classes="field"),
            Input(value=str(self.defaults.step), id="step"),
            id="panel-strategy",
        )
        panel.display = False
        return panel

    def _build_outputs_panel(self) -> VerticalScroll:
        panel = VerticalScroll(
            Label("Outputs", classes="panel-title"),
            Static("Set optional outputs. Leave fields blank to skip.", classes="field"),
            Label("GIF output path", classes="field"),
            Input(value=self.defaults.gif, id="gif"),
            Label("GIF FPS", classes="field"),
            Input(value=str(self.defaults.gif_fps), id="gif-fps"),
            Label("GIF loop (0 = infinite)", classes="field"),
            Input(value=str(self.defaults.gif_loop), id="gif-loop"),
            Checkbox("Shuffle GIF frames", value=self.defaults.gif_shuffle, id="gif-shuffle"),
            Label("SSIM chart output path", classes="field"),
            Input(value=self.defaults.ssim_chart, id="ssim-chart"),
            Label("Metrics (comma-separated)", classes="field"),
            Input(value=self.defaults.metrics, id="metrics"),
            Label("Metrics chart prefix", classes="field"),
            Input(value=self.defaults.metrics_chart_prefix, id="metrics-prefix"),
            Label("Jobs (blank = auto)", classes="field"),
            Input(value=self.defaults.jobs, id="jobs"),
            Label("Wave chart output path", classes="field"),
            Input(value=self.defaults.wave_chart, id="wave-chart"),
            Label("Sliding wave chart output path", classes="field"),
            Input(value=self.defaults.sliding_wave_chart, id="sliding-wave-chart"),
            Label("Wave window", classes="field"),
            Input(value=str(self.defaults.wave_window), id="wave-window"),
            Label("DC heatmap output path", classes="field"),
            Input(value=self.defaults.dc_heatmap, id="dc-heatmap"),
            Label("AC energy heatmap output path", classes="field"),
            Input(value=self.defaults.ac_energy_heatmap, id="ac-heatmap"),
            id="panel-outputs",
        )
        panel.display = False
        return panel

    def _build_run_panel(self) -> VerticalScroll:
        panel = VerticalScroll(
            Label("Run", classes="panel-title"),
            Static("Press Run to execute using the current options.", classes="field"),
            Static("", id="run-error"),
            Button("Run", id="run-btn", variant="success"),
            RichLog(id="log", highlight=True),
            id="panel-run",
        )
        panel.display = False
        return panel

    @on(DirectoryTree.FileSelected)
    def _on_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        """
        Update the input path when a file is selected in the tree.
        """
        info = self.query_one("#input-info", Static)
        suffix = event.path.suffix.lower()
        if suffix not in {".jpg", ".jpeg"}:
            info.update("Selected file is not a .jpg/.jpeg; ignoring selection.")
            return
        info.update("JPEG selected from file tree.")
        input_widget = self.query_one("#input-path", Input)
        input_widget.value = str(event.path)

    @on(DirectoryTree.DirectorySelected)
    def _on_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        """
        Refresh the JPEG list when a directory is selected.
        """
        self._set_current_dir(Path(event.path))

    @on(ListView.Selected, "#jpg-list")
    def _on_jpg_selected(self, event: ListView.Selected) -> None:
        """
        Update the input path when a JPEG is selected from the list.
        """
        item = event.item
        if item is None:
            return
        filename = getattr(item, "filename", None)
        if not filename:
            return
        input_widget = self.query_one("#input-path", Input)
        input_widget.value = str(Path(self.current_dir) / filename)
        self._mark_app0_dirty(False)

    @on(ListView.Selected)
    def _on_menu_selected(self, event: ListView.Selected) -> None:
        item_id = event.item.id or ""
        if item_id == "menu-input":
            self._show_panel("input")
        elif item_id == "menu-info":
            self._show_panel("info")
        elif item_id == "menu-tools":
            self._show_panel("tools")
        elif item_id == "menu-mutation":
            self._show_panel("mutation")
        elif item_id == "menu-strategy":
            self._show_panel("strategy")
        elif item_id == "menu-outputs":
            self._show_panel("outputs")
        elif item_id == "menu-run":
            self._show_panel("run")

    def _show_panel(self, name: str) -> None:
        self.current_panel = name
        self.query_one("#panel-input").display = name == "input"
        self.query_one("#panel-info").display = name == "info"
        self.query_one("#panel-tools").display = name == "tools"
        self.query_one("#panel-mutation").display = name == "mutation"
        self.query_one("#panel-strategy").display = name == "strategy"
        self.query_one("#panel-outputs").display = name == "outputs"
        self.query_one("#panel-run").display = name == "run"

    def _init_info_tabs(self) -> None:
        """
        Initialize the Info tab panes after the widget tree is mounted.
        """
        self._add_info_tabs()
        self._add_appn_tab()
        self._init_tools_tabs()

    def _add_info_tabs(self) -> None:
        tabs = self.query_one("#info-tabs", TabbedContent)
        tabs.add_pane(TabPane("General", RichLog(id="info-general", highlight=True)))
        tabs.add_pane(TabPane("Segments", RichLog(id="info-segments", highlight=True)))
        tabs.add_pane(TabPane("Details", RichLog(id="info-details", highlight=True)))
        tabs.add_pane(TabPane("Entropy", RichLog(id="info-entropy", highlight=True)))
        tabs.add_pane(TabPane("Hex", self._build_full_hex_pane()))

    def _add_appn_tab(self) -> None:
        tabs = self.query_one("#info-tabs", TabbedContent)
        tabs.add_pane(TabPane("APPn", self._build_appn_pane()))
        self._reset_appn_tabs([])

    def _build_appn_pane(self) -> Vertical:
        return Vertical(
            Static("APPn segments (APP0, APP1, ...)", classes="field"),
            TabbedContent(id="appn-tabs"),
            id="appn-panel",
        )

    def _build_appn_readonly_pane(self, title: str, log_id: str) -> VerticalScroll:
        return VerticalScroll(
            Static(f"{title} info (hex)", classes="field"),
            RichLog(id=log_id, highlight=True, classes="appn-info"),
        )

    def _build_app1_pane(self, key: str, title: str) -> Horizontal:
        return Horizontal(
            VerticalScroll(
                Static(f"{title} info (decoded + hex)", classes="field"),
                TabbedContent(id=f"{key}-tabs"),
                id=f"{key}-info",
            ),
            VerticalScroll(
                Static("Edit EXIF as Python literal (piexif dict).", classes="field"),
                Button("Save edited file", id=f"{key}-save", variant="success", disabled=True),
                Static("", id=f"{key}-error"),
                TabbedContent(id=f"{key}-edit-tabs"),
                id=f"{key}-edit",
            ),
            id=f"{key}-panel",
        )

    def _build_app0_pane(self) -> Horizontal:
        return Horizontal(
            VerticalScroll(
                Static("APP0 info (decoded + hex)", classes="field"),
                RichLog(id="info-app0", highlight=True),
                id="app0-info",
            ),
            VerticalScroll(
                Static("Edit APP0 payload in simple or advanced mode.", classes="field"),
                Checkbox("Advanced mode (raw hex)", value=False, id="app0-advanced-mode"),
                Checkbox("Manual length (dangerous)", value=False, id="app0-manual-length"),
                Input(value="", id="app0-length", placeholder="Length (hex, e.g. 0010)"),
                Button("Save edited file", id="app0-save", variant="success", disabled=True),
                Static("", id="app0-edit-error"),
                Static("Simple mode", classes="field", id="app0-simple-title"),
                self._build_app0_simple_editor(),
                Static("Advanced mode", classes="field", id="app0-adv-title"),
                TextArea("", id="app0-raw-hex", soft_wrap=True, show_line_numbers=True),
                id="app0-edit",
            ),
            id="app0-panel",
        )

    def _build_full_hex_pane(self) -> Vertical:
        return Vertical(
            Horizontal(
                Button("Prev", id="hex-prev"),
                Button("Next", id="hex-next"),
                Label("Page", classes="field"),
                Input(value="1", id="hex-page"),
                Label("Jump", classes="field"),
                Input(value="", id="hex-jump", placeholder="Page #"),
                Button("Go", id="hex-go"),
                Static("", id="hex-page-info"),
                classes="row",
            ),
            Horizontal(
                RichLog(id="info-hex", highlight=True),
                ListView(id="info-hex-legend"),
                classes="row",
            ),
            id="hex-panel",
        )

    def _build_app0_simple_editor(self) -> Vertical:
        return Vertical(
            Horizontal(
                self._build_app0_left_column(),
                self._build_app0_right_column(),
                classes="row",
            ),
            Label("Thumbnail hex (3 * X * Y bytes)", classes="field"),
            TextArea("", id="app0-thumb-hex", soft_wrap=True, show_line_numbers=False),
            id="app0-simple",
        )

    def _build_app0_left_column(self) -> Vertical:
        return Vertical(
            Label("Identifier", classes="field"),
            Select(
                [
                    ("JFIF\\0", "JFIF\\0"),
                    ("JFXX\\0", "JFXX\\0"),
                ],
                value="JFIF\\0",
                id="app0-ident",
            ),
            Label("Version", classes="field"),
            Select(
                [
                    ("1.00", "1.00"),
                    ("1.01", "1.01"),
                    ("1.02", "1.02"),
                ],
                value="1.01",
                id="app0-version",
            ),
            Label("Units", classes="field"),
            Select(
                [
                    ("0 (none)", "0"),
                    ("1 (dpi)", "1"),
                    ("2 (dpcm)", "2"),
                ],
                value="0",
                id="app0-units",
            ),
            Label("X density", classes="field"),
            Input(value="1", id="app0-xden"),
            Label("X thumbnail", classes="field"),
            Input(value="0", id="app0-xthumb"),
            id="app0-col-left",
        )

    def _build_app0_right_column(self) -> Vertical:
        return Vertical(
            Label("Y density", classes="field"),
            Input(value="1", id="app0-yden"),
            Label("Y thumbnail", classes="field"),
            Input(value="0", id="app0-ythumb"),
            id="app0-col-right",
        )

    def _init_tools_tabs(self) -> None:
        """
        Initialize the Tools tab panes after the widget tree is mounted.
        """
        tools = self.query_one("#tools-tabs", TabbedContent)
        tools.add_pane(
            TabPane(
                "APPn Writer",
                VerticalScroll(
                    Label("Input JPEG path", classes="field"),
                    Input(value=self.defaults.input_path, id="tool-appn-input"),
                    Label("APPn index (0..15)", classes="field"),
                    Input(value="15", id="tool-appn-index"),
                    Label("Identifier (optional ASCII prefix)", classes="field"),
                    Input(value="", id="tool-appn-ident"),
                    Label("Payload hex (whitespace ok)", classes="field"),
                    TextArea("", id="tool-appn-hex", soft_wrap=True),
                    Label("Payload file (optional)", classes="field"),
                    Input(value="", id="tool-appn-file"),
                    Label("Output path (optional)", classes="field"),
                    Input(value="", id="tool-appn-output"),
                    Button("Insert APPn", id="tool-appn-insert", variant="success"),
                    Static("", id="tool-appn-error"),
                    RichLog(id="tool-appn-log", highlight=True),
                    id="tool-appn-pane",
                ),
            )
        )

    def _set_current_dir(self, path: Path) -> None:
        """
        Update current directory label and refresh the JPEG list.
        """
        self.current_dir = str(path)
        self.query_one("#current-dir", Static).update(self.current_dir)
        self._refresh_jpg_list()

    def _refresh_jpg_list(self) -> None:
        """
        Rebuild the JPEG list for the current directory.
        """
        list_view = self.query_one("#jpg-list", ListView)
        list_view.clear()
        try:
            entries = sorted(Path(self.current_dir).iterdir(), key=lambda p: p.name.lower())
        except Exception:
            entries = []
        items = []
        for p in entries:
            if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg"}:
                item = ListItem(Label(p.name))
                item.filename = p.name
                items.append(item)
        if items:
            list_view.extend(items)

    def _get_int(self, value: str, label: str) -> int:
        try:
            return int(value)
        except ValueError:
            raise ValueError(f"{label} must be an integer.")

    def _get_optional_int(self, value: str, label: str) -> Optional[int]:
        v = value.strip()
        if v == "":
            return None
        try:
            return int(v)
        except ValueError:
            raise ValueError(f"{label} must be an integer or blank.")

    def _build_options(self) -> api.RunOptions:
        input_path = self.query_one("#input-path", Input).value.strip()
        if not input_path:
            raise ValueError("Input path is required.")

        output_dir = self.query_one("#output-dir", Input).value.strip() or "mutations"
        color = self.query_one("#color-mode", Input).value.strip() or "auto"

        mutate = self.query_one("#mutate-mode", Input).value.strip()
        sample = self._get_int(self.query_one("#sample", Input).value, "Sample")
        seed = self._get_int(self.query_one("#seed", Input).value, "Seed")
        overflow_wrap = self.query_one("#overflow-wrap", Checkbox).value
        report_only = self.query_one("#report-only", Checkbox).value
        debug = self.query_one("#debug", Checkbox).value

        mutation_apply = self.query_one("#mutation-apply", Select).value
        repeats = self._get_int(self.query_one("#repeats", Input).value, "Repeats")
        step = self._get_int(self.query_one("#step", Input).value, "Step")

        gif = self.query_one("#gif", Input).value.strip()
        gif_fps = self._get_int(self.query_one("#gif-fps", Input).value, "GIF FPS")
        gif_loop = self._get_int(self.query_one("#gif-loop", Input).value, "GIF loop")
        gif_shuffle = self.query_one("#gif-shuffle", Checkbox).value
        ssim_chart = self.query_one("#ssim-chart", Input).value.strip()
        metrics = self.query_one("#metrics", Input).value.strip() or "ssim"
        metrics_prefix = self.query_one("#metrics-prefix", Input).value.strip()
        jobs = self._get_optional_int(self.query_one("#jobs", Input).value, "Jobs")
        wave_chart = self.query_one("#wave-chart", Input).value.strip()
        sliding_wave_chart = self.query_one("#sliding-wave-chart", Input).value.strip()
        wave_window = self._get_int(self.query_one("#wave-window", Input).value, "Wave window")
        dc_heatmap = self.query_one("#dc-heatmap", Input).value.strip()
        ac_heatmap = self.query_one("#ac-heatmap", Input).value.strip()

        return api.RunOptions(
            input_path=input_path,
            output_dir=output_dir,
            mutate=str(mutate),
            sample=sample,
            seed=seed,
            mutation_apply=str(mutation_apply),
            repeats=repeats,
            step=step,
            overflow_wrap=overflow_wrap,
            report_only=report_only,
            color=color,
            gif=gif or None,
            gif_fps=gif_fps,
            gif_loop=gif_loop,
            gif_shuffle=gif_shuffle,
            ssim_chart=ssim_chart or None,
            metrics=metrics,
            metrics_chart_prefix=metrics_prefix or None,
            jobs=jobs,
            wave_chart=wave_chart or None,
            sliding_wave_chart=sliding_wave_chart or None,
            wave_window=wave_window,
            dc_heatmap=dc_heatmap or None,
            ac_energy_heatmap=ac_heatmap or None,
            debug=debug,
        )

    def _apply_app0_mode_visibility(self) -> None:
        """
        Show/hide APP0 simple or advanced editors based on the mode checkbox.
        """
        adv = self.query_one("#app0-advanced-mode", Checkbox).value
        self.query_one("#app0-simple", Vertical).display = not adv
        self.query_one("#app0-simple-title", Static).display = not adv
        self.query_one("#app0-adv-title", Static).display = adv
        self.query_one("#app0-raw-hex", TextArea).display = adv

        manual = self.query_one("#app0-manual-length", Checkbox).value
        self.query_one("#app0-length", Input).disabled = not manual

    @on(Checkbox.Changed, "#app0-advanced-mode")
    def _on_app0_mode_changed(self) -> None:
        self._apply_app0_mode_visibility()
        self._update_app0_length_field()
        self._refresh_app0_preview()
        self._mark_app0_dirty(True)

    @on(Checkbox.Changed, "#app0-manual-length")
    def _on_app0_manual_length_changed(self) -> None:
        self._apply_app0_mode_visibility()
        if not self.query_one("#app0-manual-length", Checkbox).value:
            self._update_app0_length_field()
        self._refresh_app0_preview()
        self._mark_app0_dirty(True)

    @on(Input.Changed)
    def _on_app0_input_changed(self, event: Input.Changed) -> None:
        if not event.input.id or not event.input.id.startswith("app0-"):
            return
        if event.input.id == "app0-length":
            self._mark_app0_dirty(True)
            return
        self._update_app0_length_field()
        self._refresh_app0_preview()
        self._mark_app0_dirty(True)

    @on(TextArea.Changed)
    def _on_app0_textarea_changed(self, event: TextArea.Changed) -> None:
        if not event.text_area.id or not event.text_area.id.startswith("app0-"):
            return
        self._update_app0_length_field()
        self._refresh_app0_preview()
        self._mark_app0_dirty(True)

    @on(Select.Changed)
    def _on_app0_select_changed(self, event: Select.Changed) -> None:
        if not event.select.id or not event.select.id.startswith("app0-"):
            return
        self._update_app0_length_field()
        self._refresh_app0_preview()
        self._mark_app0_dirty(True)

    @on(TextArea.Changed)
    def _on_app1_textarea_changed(self, event: TextArea.Changed) -> None:
        key = self._app1_key_from_id(event.text_area.id, "-header-hex")
        if key:
            self._on_app1_header_hex_changed(key)
            self._set_app1_dirty(key, True)
            return
        key = self._app1_key_from_id(event.text_area.id, "-ifd0-editor")
        if key:
            self._sync_ifd_editor_to_dict(key, "0th")
            self._set_app1_dirty(key, True)
            return
        key = self._app1_key_from_id(event.text_area.id, "-ifd1-editor")
        if key:
            self._sync_ifd_editor_to_dict(key, "1st")
            self._set_app1_dirty(key, True)
            return
        key = self._app1_key_from_id(event.text_area.id, "-dict-editor")
        if not key:
            return
        self._set_app1_dirty(key, True)

    @on(Button.Pressed)
    def _on_app1_save(self, event: Button.Pressed) -> None:
        key = self._app1_key_from_id(event.button.id, "-save")
        if not key:
            return
        err = self.query_one(f"#{key}-error", Static)
        err.update("")
        try:
            input_path, payload = self._app1_save_inputs(key)
        except Exception as e:
            err.update(f"Error: {e}")
            return
        out_path = self._app1_write_file(input_path, key, payload)
        log = self.query_one(f"#info-{key}", RichLog)
        log.write(f"Saved edited file: {out_path}")
        self._set_app1_dirty(key, False)

    @on(Button.Pressed, "#hex-prev")
    def _on_hex_prev(self) -> None:
        if self.info_data is None:
            return
        if self.hex_page > 0:
            self.hex_page -= 1
            self._render_full_hex_page()

    @on(Button.Pressed, "#hex-next")
    def _on_hex_next(self) -> None:
        if self.info_data is None:
            return
        total = self._hex_total_pages()
        if self.hex_page + 1 < total:
            self.hex_page += 1
            self._render_full_hex_page()

    @on(Input.Changed, "#hex-page")
    def _on_hex_page_changed(self, event: Input.Changed) -> None:
        if self.info_data is None:
            return
        text = event.input.value.strip()
        if not text:
            return
        try:
            page = int(text) - 1
        except ValueError:
            return
        total = self._hex_total_pages()
        if 0 <= page < total:
            self.hex_page = page
            self._render_full_hex_page()

    @on(ListView.Selected, "#info-hex-legend")
    def _on_hex_legend_selected(self, event: ListView.Selected) -> None:
        if self.info_data is None:
            return
        item_id = event.item.id if event.item else None
        if not item_id or item_id not in self.hex_legend_offsets:
            return
        offset = self.hex_legend_offsets[item_id]
        page = offset // 512
        total = self._hex_total_pages()
        if 0 <= page < total:
            self.hex_page = page
            self._render_full_hex_page()

    @on(Button.Pressed, "#hex-go")
    def _on_hex_go(self) -> None:
        if self.info_data is None:
            return
        text = self.query_one("#hex-jump", Input).value.strip()
        if not text:
            return
        try:
            page = int(text) - 1
        except ValueError:
            return
        total = self._hex_total_pages()
        if 0 <= page < total:
            self.hex_page = page
            self._render_full_hex_page()

    @on(Button.Pressed, "#load-info")
    def _on_load_info(self) -> None:
        """
        Parse the current input JPEG and populate the info tabs.
        """
        err = self.query_one("#info-error", Static)
        err.update("")
        try:
            input_path, data, segments, entropy_ranges = self._load_info_data()
        except Exception as e:
            err.update(f"Error: {e}")
            return
        self.info_data = data
        self.info_segments = segments
        self.hex_page = 0

        general, segments_log, details_log, entropy_log = self._info_logs()
        self._clear_info_logs(general, segments_log, details_log, entropy_log)
        appn_targets = self._reset_appn_tabs(segments)
        self._write_general(general, input_path, data, segments, entropy_ranges)
        self._write_segments(segments_log, segments, entropy_ranges, data)
        self._write_details(details_log, segments, data)
        self._write_entropy(entropy_log, entropy_ranges)
        self._render_app0_segment(data, segments)
        self._render_appn_segments(data, appn_targets)
        self._render_full_hex_page()
        self._mark_app0_dirty(False)

    def _load_info_data(self) -> Tuple[str, bytes, list, list]:
        input_path = self.query_one("#input-path", Input).value.strip()
        if not input_path:
            raise ValueError("input path is required to load info.")
        data = Path(input_path).read_bytes()
        segments, entropy_ranges = parse_jpeg(data)
        return input_path, data, segments, entropy_ranges

    def _info_logs(self):
        return (
            self.query_one("#info-general", RichLog),
            self.query_one("#info-segments", RichLog),
            self.query_one("#info-details", RichLog),
            self.query_one("#info-entropy", RichLog),
        )

    def _clear_info_logs(self, *logs: RichLog) -> None:
        for log in logs:
            log.clear()

    def _write_general(self, log: RichLog, input_path: str, data: bytes, segments, entropy_ranges) -> None:
        log.write(f"File: {input_path}")
        log.write(f"Size: {len(data)} bytes")
        log.write(f"Segments: {len(segments)}")
        log.write(f"Scans: {len(entropy_ranges)}")
        log.write(f"Entropy bytes: {total_entropy_length(entropy_ranges)}")

    def _write_segments(self, log: RichLog, segments, entropy_ranges, data: bytes) -> None:
        health = self._segment_health(segments, entropy_ranges, data)
        for idx, seg in enumerate(segments):
            end_off = seg.offset + seg.total_length - 1
            marker_hex = f"FF{seg.marker:02X}"
            status, issues = health.get(idx, ("OK", []))
            issue_text = f" issues={'; '.join(issues)}" if issues else ""
            if seg.length_field is None:
                log.write(
                    (
                        f"{idx:03d} {seg.name} start=0x{seg.offset:08X} end=0x{end_off:08X} "
                        f"marker={marker_hex} total=2 health={status}{issue_text}"
                    )
                )
            else:
                log.write(
                    (
                        f"{idx:03d} {seg.name} start=0x{seg.offset:08X} end=0x{end_off:08X} "
                        f"marker={marker_hex} length=0x{seg.length_field:04X} "
                        f"payload={seg.payload_length} total={seg.total_length} health={status}{issue_text}"
                    )
                )

    def _write_details(self, log: RichLog, segments, data: bytes) -> None:
        for idx, seg in enumerate(segments):
            log.write(f"{idx:03d} {seg.name}")
            for line in explain_segment(seg, data):
                log.write(f"  {line}")

    def _write_entropy(self, log: RichLog, entropy_ranges) -> None:
        if entropy_ranges:
            for r in entropy_ranges:
                log.write(
                    f"Scan {r.scan_index}: 0x{r.start:08X}..0x{r.end:08X} ({r.end - r.start} bytes)"
                )
        else:
            log.write("No entropy-coded data ranges found.")

    def _reset_appn_tabs(self, segments) -> list[Tuple[str, object]]:
        """
        Rebuild APPn sub-tabs based on current segments and return log targets.
        """
        appn_tabs = self.query_one("#appn-tabs", TabbedContent)
        appn_tabs.clear_panes()
        appn_tabs.add_pane(TabPane("APP0", self._build_app0_pane()))
        self._apply_app0_mode_visibility()

        self.app1_segment_info = {}
        self.app1_original_payload = {}
        self.app1_dirty = {}
        counts: dict[str, int] = {}
        targets: list[Tuple[str, object]] = []
        for seg in segments:
            if not seg.name.startswith("APP"):
                continue
            counts[seg.name] = counts.get(seg.name, 0) + 1
            if seg.name == "APP0" and counts[seg.name] == 1:
                continue
            label = seg.name if counts[seg.name] == 1 else f"{seg.name} #{counts[seg.name]}"
            if seg.name == "APP1":
                key = f"app1-{seg.offset:08X}"
                appn_tabs.add_pane(TabPane(label, self._build_app1_pane(key, label)))
                self._init_app1_tabs(key)
                targets.append((key, seg))
            else:
                log_id = f"info-appn-{seg.offset}"
                appn_tabs.add_pane(TabPane(label, self._build_appn_readonly_pane(label, log_id)))
                targets.append((log_id, seg))
        return targets

    def _render_appn_segments(self, data: bytes, targets: list[Tuple[str, object]]) -> None:
        for key, seg in targets:
            if key.startswith("app1-"):
                self._render_app1_segment(data, seg, key)
                continue
            log = self.query_one(f"#{key}", RichLog)
            log.clear()
            self._render_appn_segment(data, seg, log)

    def _render_appn_segment(self, data: bytes, seg, log: RichLog) -> None:
        if seg.payload_offset is None or seg.payload_length is None:
            log.write(f"{seg.name} has no payload.")
            return
        log.write(
            f"{seg.name} at 0x{seg.offset:08X} length=0x{seg.length_field or 0:04X} payload={seg.payload_length}"
        )
        marker_start = seg.offset
        marker_end = seg.offset + 2
        length_start = seg.payload_offset - 2
        length_end = seg.payload_offset
        payload_start = seg.payload_offset
        payload_end = seg.payload_offset + seg.payload_length
        ranges = [
            (marker_start, marker_end, "bold yellow"),
            (length_start, length_end, "bold cyan"),
            (payload_start, payload_end, "green"),
        ]
        dump = self._hex_dump(data, seg.offset, seg.total_length, ranges)
        for line in dump:
            log.write(line)

    def _init_app1_tabs(self, key: str) -> None:
        tabs = self.query_one(f"#{key}-tabs", TabbedContent)
        tabs.clear_panes()
        tabs.add_pane(TabPane("Raw", RichLog(id=f"info-{key}-raw", highlight=True)))
        tabs.add_pane(TabPane("Hex", RichLog(id=f"info-{key}-hex", highlight=True)))
        tabs.add_pane(TabPane("Table", RichLog(id=f"info-{key}-table", highlight=True)))
        edit_tabs = self.query_one(f"#{key}-edit-tabs", TabbedContent)
        edit_tabs.clear_panes()
        edit_tabs.add_pane(
            TabPane(
                "Header",
                VerticalScroll(
                    Static("APP1 + TIFF header (hex)", classes="field"),
                    TextArea("", id=f"{key}-header-hex", soft_wrap=True, show_line_numbers=False),
                    Static("Decoded header", classes="field"),
                    RichLog(id=f"{key}-header", highlight=True),
                ),
            )
        )
        edit_tabs.add_pane(
            TabPane("IFD0", TextArea("", id=f"{key}-ifd0-editor", soft_wrap=True, show_line_numbers=True))
        )
        edit_tabs.add_pane(
            TabPane("IFD1", TextArea("", id=f"{key}-ifd1-editor", soft_wrap=True, show_line_numbers=True))
        )
        edit_tabs.add_pane(
            TabPane("Dict", TextArea("", id=f"{key}-dict-editor", soft_wrap=True, show_line_numbers=True))
        )

    def _render_app1_segment(self, data: bytes, seg, key: str) -> None:
        log_hex = self.query_one(f"#info-{key}-hex", RichLog)
        log_raw = self.query_one(f"#info-{key}-raw", RichLog)
        log_table = self.query_one(f"#info-{key}-table", RichLog)
        err = self.query_one(f"#{key}-error", Static)
        header = self.query_one(f"#{key}-header", RichLog)
        header_hex = self.query_one(f"#{key}-header-hex", TextArea)
        ifd0_editor = self.query_one(f"#{key}-ifd0-editor", TextArea)
        ifd1_editor = self.query_one(f"#{key}-ifd1-editor", TextArea)
        dict_editor = self.query_one(f"#{key}-dict-editor", TextArea)
        log_hex.clear()
        log_raw.clear()
        log_table.clear()
        header.clear()
        err.update("")
        header_hex.text = ""
        ifd0_editor.text = ""
        ifd1_editor.text = ""
        dict_editor.text = ""
        if seg.payload_offset is None or seg.payload_length is None:
            log_hex.write("APP1 has no payload.")
            self._set_app1_dirty(key, False)
            return
        self.app1_segment_info[key] = (seg.offset, seg.total_length, seg.length_field or 0, seg.payload_offset)
        payload = data[seg.payload_offset:seg.payload_offset + seg.payload_length]
        self.app1_original_payload[key] = payload
        self.app1_preview_payload[key] = payload
        header_hex.text = self._bytes_to_hex(payload[:14])
        if not payload.startswith(b"Exif\x00\x00"):
            log_hex.write("APP1 payload is not EXIF (missing Exif\\0\\0 header).")
            log_table.write("APP1 payload is not EXIF.")
            self._render_app1_hex(log_hex, data, seg, [])
            self._render_app1_raw_hex(log_raw, data, seg, self._app1_basic_ranges(seg))
            self._set_app1_dirty(key, False)
            return
        exif = self._parse_exif(payload, seg.payload_offset)
        if exif.get("error"):
            log_hex.write(f"EXIF decode error: {exif['error']}")
            log_table.write(f"EXIF decode error: {exif['error']}")
            self._render_app1_hex(log_hex, data, seg, [])
            self._render_app1_raw_hex(log_raw, data, seg, self._app1_basic_ranges(seg))
            self._set_app1_dirty(key, False)
            return
        self._write_app1_header(header, exif, seg)
        self._write_app1_exif_table(log_table, exif)
        ranges = self._app1_hex_ranges(seg, exif)
        preview_data = self._app1_preview_data(data, seg, self.app1_preview_payload[key])
        self._render_app1_hex_sections(log_hex, preview_data, seg, exif, ranges)
        self._render_app1_raw_hex(log_raw, preview_data, seg, ranges, exif)
        if piexif is None:
            log_hex.write("piexif is not installed; editor disabled.")
            header.write("piexif is not installed; editors disabled.")
        else:
            try:
                exif_dict = piexif.load(payload[6:])
                self.app1_exif_dict[key] = exif_dict
                dict_editor.text = self._exif_dict_literal(exif_dict)
                ifd0_editor.text = self._format_ifd_editor(exif_dict.get("0th", {}))
                ifd1_editor.text = self._format_ifd_editor(exif_dict.get("1st", {}))
            except Exception as e:
                err.update(f"Error: {e}")
        self._set_app1_dirty(key, False)

    def _render_app1_hex(self, log: RichLog, data: bytes, seg, ranges) -> None:
        marker_start = seg.offset
        marker_end = seg.offset + 2
        length_start = seg.payload_offset - 2
        length_end = seg.payload_offset
        payload_start = seg.payload_offset
        payload_end = seg.payload_offset + seg.payload_length
        base_ranges = [
            (marker_start, marker_end, "bold yellow"),
            (length_start, length_end, "bold cyan"),
            (payload_start, payload_end, "green"),
        ]
        for line in self._hex_dump(data, seg.offset, seg.total_length, ranges + base_ranges):
            log.write(line)

    def _render_app1_raw_hex(
        self, log: RichLog, data: bytes, seg, ranges: list[Tuple[int, int, str]], exif: Optional[dict] = None
    ) -> None:
        self._write_header_legend(log)
        if exif:
            self._write_ifd0_legend(log)
        for line in self._hex_dump(data, seg.offset, seg.total_length, ranges):
            log.write(line)
        log.scroll_to(0, animate=False)

    def _render_app1_hex_sections(self, log: RichLog, data: bytes, seg, exif: dict, ranges) -> None:
        payload_start = seg.payload_offset
        payload_end = seg.payload_offset + seg.payload_length
        self._write_header_legend(log)
        self._write_hex_section(
            log, "Marker + Length + Exif/TIFF header", data, seg.offset, payload_start + 14, ranges, seg
        )
        ifd0 = next((i for i in exif["ifds"] if i["name"] == "IFD0"), None)
        if ifd0:
            self._write_ifd0_legend(log)
            self._write_ifd_sections(log, data, ifd0, ranges, seg)
        exif_ifd = next((i for i in exif["ifds"] if i["name"] == "ExifIFD"), None)
        if exif_ifd:
            self._write_ifd0_legend(log)
            self._write_ifd_sections(log, data, exif_ifd, ranges, seg)
        gps_ifd = next((i for i in exif["ifds"] if i["name"] == "GPSIFD"), None)
        if gps_ifd:
            self._write_ifd0_legend(log)
            self._write_ifd_sections(log, data, gps_ifd, ranges, seg)
        ifd1 = next((i for i in exif["ifds"] if i["name"] == "IFD1"), None)
        if ifd1:
            self._write_ifd0_legend(log)
            self._write_ifd_sections(log, data, ifd1, ranges, seg)
        remaining = [(payload_start + 14, payload_end)]
        for ifd in [ifd0, exif_ifd, gps_ifd, ifd1]:
            if not ifd:
                continue
            self._subtract_section(remaining, ifd["offset"], ifd["offset"] + 2 + ifd["count"] * 12 + 4)
            for entry in ifd["entries"]:
                if entry["value_len"] <= 4:
                    continue
                self._subtract_section(remaining, entry["value_offset"], entry["value_offset"] + entry["value_len"])
        for start, end in remaining:
            if end > start:
                self._write_hex_section(log, "Other EXIF bytes", data, start, end, ranges, seg)

    def _write_ifd_sections(self, log: RichLog, data: bytes, ifd: dict, ranges, seg) -> None:
        table_start = ifd["offset"]
        table_end = table_start + 2 + ifd["count"] * 12 + 4
        if ifd["name"] == "IFD0":
            self._write_ifd0_entry_sections(log, data, ifd, ranges, seg)
        else:
            self._write_hex_section(log, f"{ifd['name']} table", data, table_start, table_end, ranges, seg)
        for entry in ifd["entries"]:
            if entry["value_len"] <= 4:
                continue
            start = entry["value_offset"]
            end = start + entry["value_len"]
            self._write_hex_section(log, f"{ifd['name']} value @0x{start:08X}", data, start, end, ranges, seg)

    def _write_ifd0_entry_sections(self, log: RichLog, data: bytes, ifd: dict, ranges, seg) -> None:
        table_start = ifd["offset"]
        log.write(f"{ifd['name']} table (split fields)")
        self._write_hex_section(log, "IFD0 entry count", data, table_start, table_start + 2, ranges, seg)
        for idx, entry in enumerate(ifd["entries"]):
            e = entry["entry_offset"]
            tag_name = ""
            if piexif is not None:
                tag_info = piexif.TAGS.get("0th", {}).get(entry["tag"], {})
                tag_name = tag_info.get("name", "")
            tag_label = f" ({tag_name})" if tag_name else ""
            log.write(f"IFD0 entry {idx} tag=0x{entry['tag']:04X}{tag_label}")
            self._write_hex_section(log, "  entry bytes", data, e, e + 12, ranges, seg)
            self._write_ifd_entry_explanation(log, entry, ifd)
        end = table_start + 2 + ifd["count"] * 12
        self._write_hex_section(log, "IFD0 next IFD offset", data, end, end + 4, ranges, seg)
        self._write_next_ifd_explanation(log, ifd)

    def _write_ifd_entry_explanation(self, log: RichLog, entry: dict, ifd: dict) -> None:
        if entry["value_len"] <= 4:
            return
        rel = entry["value_offset"] - ifd["tiff_base"]
        log.write(
            f"    value offset (TIFF-rel)=0x{rel:08X} abs=0x{entry['value_offset']:08X} "
            f"len={entry['value_len']} bytes"
        )

    def _write_next_ifd_explanation(self, log: RichLog, ifd: dict) -> None:
        if not ifd.get("next_offset"):
            log.write("    next IFD offset = 0x00000000 (no IFD1)")
            return
        abs_off = ifd["tiff_base"] + ifd["next_offset"]
        log.write(
            f"    next IFD offset (TIFF-rel)=0x{ifd['next_offset']:08X} abs=0x{abs_off:08X}"
        )

    def _write_hex_section(
        self, log: RichLog, title: str, data: bytes, start: int, end: int, ranges, seg
    ) -> None:
        start = max(seg.offset, start)
        end = min(seg.offset + seg.total_length, end)
        if end <= start:
            return
        log.write(f"{title} (0x{start:08X}..0x{end - 1:08X})")
        for line in self._hex_dump(data, start, end - start, ranges):
            log.write(line)

    def _write_header_legend(self, log: RichLog) -> None:
        log.write("Legend (Header):")
        log.write(Text("  Marker", style="bold yellow"))
        log.write(Text("  Length", style="bold cyan"))
        log.write(Text("  Exif header", style="magenta"))
        log.write(Text("  TIFF header", style="bright_blue"))

    def _write_ifd0_legend(self, log: RichLog) -> None:
        log.write("Legend (IFD table):")
        log.write(Text("  Entry count", style="bright_white"))
        log.write(Text("  Tag", style="bright_green"))
        log.write(Text("  Type", style="bright_blue"))
        log.write(Text("  Count", style="bright_cyan"))
        log.write(Text("  Value/Offset", style="bright_yellow"))
        log.write(Text("  Next IFD offset", style="bright_red"))

    def _subtract_section(self, sections: list[Tuple[int, int]], start: int, end: int) -> None:
        if end <= start:
            return
        out: list[Tuple[int, int]] = []
        for s, e in sections:
            if end <= s or start >= e:
                out.append((s, e))
                continue
            if start > s:
                out.append((s, start))
            if end < e:
                out.append((end, e))
        sections[:] = out

    def _write_app1_exif_table(self, log: RichLog, exif: dict) -> None:
        log.write(f"Byte order: {exif['endian']}")
        log.write(f"TIFF header @0x{exif['tiff_base']:08X}")
        for ifd in exif["ifds"]:
            log.write(f"{ifd['name']} @0x{ifd['offset']:08X} entries={ifd['count']}")
            for entry in ifd["entries"]:
                log.write(
                    f"  tag=0x{entry['tag']:04X} type={entry['type_name']} count={entry['count']} "
                    f"val_len={entry['value_len']} val_off=0x{entry['value_offset']:08X} "
                    f"val={entry['preview']}"
                )

    def _format_exif_value(self, value) -> str:
        if isinstance(value, bytes):
            if len(value) <= 64:
                try:
                    text = value.decode("utf-8")
                    return f"{text!r}"
                except Exception:
                    return "0x" + value.hex()
            return f"bytes[{len(value)}]"
        if isinstance(value, tuple):
            return repr(value)
        return str(value)

    def _exif_dict_literal(self, exif_dict) -> str:
        return repr(exif_dict)

    def _set_app1_dirty(self, key: str, dirty: bool) -> None:
        self.app1_dirty[key] = dirty
        self.query_one(f"#{key}-save", Button).disabled = not dirty

    def _write_app1_header(self, log: RichLog, exif: dict, seg) -> None:
        log.write(
            f"APP1 EXIF at 0x{seg.offset:08X} length=0x{seg.length_field or 0:04X} payload={seg.payload_length}"
        )
        log.write(f"Endian: {'II' if exif['endian'] == '<' else 'MM'}")
        log.write(f"TIFF base: 0x{exif['tiff_base']:08X}")
        ifd0 = next((i for i in exif["ifds"] if i["name"] == "IFD0"), None)
        if ifd0:
            log.write(f"IFD0 offset: 0x{ifd0['offset']:08X}")
        ifd1 = next((i for i in exif["ifds"] if i["name"] == "IFD1"), None)
        if ifd1:
            log.write(f"IFD1 offset: 0x{ifd1['offset']:08X}")

    def _format_ifd_editor(self, ifd_dict: dict) -> str:
        lines = []
        for tag in sorted(ifd_dict.keys()):
            lines.append(f"0x{tag:04X} = {ifd_dict[tag]!r}")
        return "\n".join(lines)

    def _parse_ifd_editor(self, text: str) -> dict:
        out: dict[int, object] = {}
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ValueError(f"Invalid line (missing '='): {line}")
            left, right = line.split("=", 1)
            left = left.strip()
            right = right.strip()
            try:
                tag = int(left, 16) if left.lower().startswith("0x") else int(left)
            except ValueError as e:
                raise ValueError(f"Invalid tag '{left}': {e}")
            try:
                value = ast.literal_eval(right)
            except Exception:
                value = right
            out[tag] = value
        return out

    def _sync_ifd_editor_to_dict(self, key: str, ifd_name: str) -> None:
        if self._app1_syncing:
            return
        err = self.query_one(f"#{key}-error", Static)
        editor = self.query_one(f"#{key}-{'ifd0' if ifd_name == '0th' else 'ifd1'}-editor", TextArea)
        try:
            ifd_dict = self._parse_ifd_editor(editor.text)
        except Exception as e:
            err.update(f"Error: {e}")
            return
        err.update("")
        base = self.app1_exif_dict.get(key, {})
        base[ifd_name] = ifd_dict
        for k in ["0th", "Exif", "GPS", "1st", "Interop"]:
            base.setdefault(k, {})
        base.setdefault("thumbnail", b"")
        self.app1_exif_dict[key] = base
        self._app1_syncing = True
        try:
            self.query_one(f"#{key}-dict-editor", TextArea).text = self._exif_dict_literal(base)
        finally:
            self._app1_syncing = False

    def _parse_exif(self, payload: bytes, payload_offset: int) -> dict:
        if not payload.startswith(b"Exif\x00\x00"):
            return {"error": "missing Exif header"}
        tiff = payload[6:]
        tiff_base = payload_offset + 6
        if len(tiff) < 8:
            return {"error": "truncated TIFF header"}
        endian = self._exif_endian(tiff[:2])
        if endian is None:
            return {"error": "invalid TIFF byte order"}
        magic = self._exif_u16(tiff[2:4], endian)
        if magic != 0x002A:
            return {"error": f"bad TIFF magic 0x{magic:04X}"}
        ifd0_off = self._exif_u32(tiff[4:8], endian)
        ifds = self._collect_exif_ifds(tiff, tiff_base, endian, ifd0_off)
        return {"endian": endian, "tiff_base": tiff_base, "ifds": ifds, "error": None}

    def _exif_endian(self, data: bytes) -> Optional[str]:
        if data == b"II":
            return "<"
        if data == b"MM":
            return ">"
        return None

    def _exif_u16(self, data: bytes, endian: str) -> int:
        return int.from_bytes(data, "little" if endian == "<" else "big")

    def _exif_u32(self, data: bytes, endian: str) -> int:
        return int.from_bytes(data, "little" if endian == "<" else "big")

    def _collect_exif_ifds(self, tiff: bytes, tiff_base: int, endian: str, ifd0_off: int) -> list[dict]:
        ifds: list[dict] = []
        seen: set[int] = set()
        ifd0 = self._parse_ifd("IFD0", tiff, tiff_base, endian, ifd0_off, seen)
        if ifd0:
            ifds.append(ifd0)
            self._append_pointer_ifd(ifds, ifd0, "ExifIFD", 0x8769, tiff, tiff_base, endian, seen)
            self._append_pointer_ifd(ifds, ifd0, "GPSIFD", 0x8825, tiff, tiff_base, endian, seen)
        if ifd0 and ifd0["next_offset"]:
            ifd1 = self._parse_ifd("IFD1", tiff, tiff_base, endian, ifd0["next_offset"], seen)
            if ifd1:
                ifds.append(ifd1)
        interop = next((i for i in ifds if i["name"] == "ExifIFD"), None)
        if interop:
            self._append_pointer_ifd(ifds, interop, "InteropIFD", 0xA005, tiff, tiff_base, endian, seen)
        return ifds

    def _append_pointer_ifd(
        self, ifds: list[dict], parent: dict, name: str, tag_id: int, tiff, tiff_base, endian, seen
    ) -> None:
        entry = next((e for e in parent["entries"] if e["tag"] == tag_id), None)
        if not entry:
            return
        ifd = self._parse_ifd(name, tiff, tiff_base, endian, entry["value_offset"], seen)
        if ifd:
            ifds.append(ifd)

    def _parse_ifd(
        self, name: str, tiff: bytes, tiff_base: int, endian: str, offset: int, seen: set[int]
    ) -> Optional[dict]:
        if offset == 0 or offset in seen:
            return None
        if offset + 2 > len(tiff):
            return None
        seen.add(offset)
        count = self._exif_u16(tiff[offset:offset + 2], endian)
        entries = []
        entries_start = offset + 2
        entries_end = entries_start + count * 12
        if entries_end + 4 > len(tiff):
            return None
        for i in range(count):
            e_off = entries_start + i * 12
            entry = self._parse_ifd_entry(tiff, tiff_base, endian, e_off)
            if entry:
                entries.append(entry)
        next_offset = self._exif_u32(tiff[entries_end:entries_end + 4], endian)
        return {
            "name": name,
            "offset": tiff_base + offset,
            "tiff_base": tiff_base,
            "count": count,
            "entries": entries,
            "next_offset": next_offset,
        }

    def _parse_ifd_entry(self, tiff: bytes, tiff_base: int, endian: str, e_off: int) -> Optional[dict]:
        if e_off + 12 > len(tiff):
            return None
        tag = self._exif_u16(tiff[e_off:e_off + 2], endian)
        typ = self._exif_u16(tiff[e_off + 2:e_off + 4], endian)
        count = self._exif_u32(tiff[e_off + 4:e_off + 8], endian)
        value_or_off = self._exif_u32(tiff[e_off + 8:e_off + 12], endian)
        size = self._exif_type_size(typ)
        value_len = count * size if size else 0
        if value_len <= 4:
            value_offset = tiff_base + e_off + 8
        else:
            value_offset = tiff_base + value_or_off
        preview = self._exif_value_preview(tiff, tiff_base, value_offset, value_len, typ, endian)
        return {
            "tag": tag,
            "type": typ,
            "type_name": self._exif_type_name(typ),
            "count": count,
            "value_len": value_len,
            "value_offset": value_offset,
            "preview": preview,
            "entry_offset": tiff_base + e_off,
        }

    def _exif_type_size(self, typ: int) -> int:
        return {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}.get(typ, 0)

    def _exif_type_name(self, typ: int) -> str:
        return {
            1: "BYTE",
            2: "ASCII",
            3: "SHORT",
            4: "LONG",
            5: "RATIONAL",
            7: "UNDEFINED",
            9: "SLONG",
            10: "SRATIONAL",
        }.get(typ, f"TYPE{typ}")

    def _exif_value_preview(
        self, tiff: bytes, tiff_base: int, value_offset: int, value_len: int, typ: int, endian: str
    ) -> str:
        if value_len == 0:
            return ""
        rel = value_offset - tiff_base
        if rel < 0 or rel + value_len > len(tiff):
            return "out-of-bounds"
        raw = tiff[rel:rel + value_len]
        if typ == 2:
            return raw.split(b"\x00", 1)[0].decode(errors="replace")
        if value_len <= 16:
            return "0x" + raw.hex()
        return f"bytes[{value_len}]"

    def _app1_hex_ranges(self, seg, exif: dict) -> list[Tuple[int, int, str]]:
        ranges: list[Tuple[int, int, str]] = []
        payload_start = seg.payload_offset
        ranges.append((seg.offset, seg.offset + 2, "bold yellow"))
        ranges.append((seg.payload_offset - 2, seg.payload_offset, "bold cyan"))
        ranges.append((payload_start, payload_start + 6, "magenta"))
        ranges.append((payload_start + 6, payload_start + 14, "bright_blue"))
        ifd0 = next((i for i in exif["ifds"] if i["name"] == "IFD0"), None)
        if ifd0:
            self._add_ifd0_table_ranges(ranges, ifd0)
        styles = ["green", "bright_cyan", "bright_yellow", "red", "bright_magenta"]
        for idx, ifd in enumerate(exif["ifds"]):
            style = styles[idx % len(styles)]
            ifd_rel = ifd["offset"] - exif["tiff_base"]
            ifd_abs = exif["tiff_base"] + ifd_rel
            count = ifd["count"]
            table_len = 2 + count * 12 + 4
            ranges.append((ifd_abs, ifd_abs + table_len, style))
            for entry in ifd["entries"]:
                if entry["value_len"] <= 4:
                    continue
                start = entry["value_offset"]
                end = start + entry["value_len"]
                ranges.append((start, end, style))
        return ranges

    def _app1_basic_ranges(self, seg) -> list[Tuple[int, int, str]]:
        payload_start = seg.payload_offset
        return [
            (seg.offset, seg.offset + 2, "bold yellow"),
            (seg.payload_offset - 2, seg.payload_offset, "bold cyan"),
            (payload_start, payload_start + 6, "magenta"),
            (payload_start + 6, payload_start + 14, "bright_blue"),
        ]

    def _add_ifd0_table_ranges(self, ranges: list[Tuple[int, int, str]], ifd: dict) -> None:
        table_start = ifd["offset"]
        ranges.append((table_start, table_start + 2, "bright_white"))
        for entry in ifd["entries"]:
            e = entry["entry_offset"]
            ranges.append((e, e + 2, "bright_green"))
            ranges.append((e + 2, e + 4, "bright_blue"))
            ranges.append((e + 4, e + 8, "bright_cyan"))
            ranges.append((e + 8, e + 12, "bright_yellow"))
        end = table_start + 2 + ifd["count"] * 12
        ranges.append((end, end + 4, "bright_red"))

    def _segment_health(self, segments, entropy_ranges, data: bytes):
        """
        Compute health status and issues for each segment.
        """
        health = {}
        data_len = len(data)
        sos_indices = [i for i, s in enumerate(segments) if s.name == "SOS"]
        sos_ranges = {i: r for i, r in zip(sos_indices, entropy_ranges)}

        for i, seg in enumerate(segments):
            issues: list[str] = []
            self._check_basic_bounds(seg, data_len, issues)
            self._check_length_fields(seg, data_len, issues)
            self._check_soi_eoi(seg, data_len, issues)
            self._check_gaps(segments, i, issues)
            self._check_sos(seg, i, sos_ranges, data_len, issues)

            status = self._health_status(issues)
            health[i] = (status, issues)
        return health

    def _check_basic_bounds(self, seg, data_len: int, issues: list[str]) -> None:
        if seg.offset < 0 or seg.offset >= data_len:
            issues.append("offset out of bounds")
        if seg.offset + seg.total_length > data_len:
            issues.append("segment exceeds file length")

    def _check_length_fields(self, seg, data_len: int, issues: list[str]) -> None:
        if seg.length_field is None:
            if seg.total_length != 2:
                issues.append("no-length marker total_length != 2")
            return
        if seg.length_field < 2:
            issues.append("length_field < 2")
        expected_total = seg.length_field + 2
        if expected_total != seg.total_length:
            issues.append("total_length mismatch length_field")
        if seg.payload_offset is None or seg.payload_length is None:
            issues.append("missing payload offsets")
        elif seg.payload_offset + seg.payload_length > data_len:
            issues.append("payload exceeds file length")

    def _check_soi_eoi(self, seg, data_len: int, issues: list[str]) -> None:
        if seg.name == "SOI":
            if seg.offset != 0:
                issues.append("SOI not at offset 0")
            if seg.total_length != 2:
                issues.append("SOI length != 2")
        if seg.name == "EOI":
            if seg.offset + 2 != data_len:
                issues.append("EOI not at end of file")

    def _check_gaps(self, segments, i: int, issues: list[str]) -> None:
        if i + 1 >= len(segments):
            return
        next_seg = segments[i + 1]
        gap = next_seg.offset - (segments[i].offset + segments[i].total_length)
        if gap > 0:
            issues.append(f"gap before next marker ({gap} bytes)")
        if gap < 0:
            issues.append("segment overlap with next marker")

    def _check_sos(self, seg, i: int, sos_ranges, data_len: int, issues: list[str]) -> None:
        if seg.name != "SOS":
            return
        r = sos_ranges.get(i)
        if r is None:
            issues.append("missing entropy range")
            return
        if seg.payload_offset is not None and seg.payload_length is not None:
            expected_start = seg.payload_offset + seg.payload_length
            if r.start != expected_start:
                issues.append("entropy start mismatch")
        if r.end <= r.start:
            issues.append("entropy range empty")
        if r.end > data_len:
            issues.append("entropy end exceeds file length")

    def _health_status(self, issues: list[str]) -> str:
        if not issues:
            return "OK"
        fail_keys = ["out of bounds", "exceeds", "overlap", "missing"]
        text = "; ".join(issues)
        return "FAIL" if any(k in text for k in fail_keys) else "WARN"

    def _render_app0_segment(self, data: bytes, segments) -> None:
        """
        Render a dedicated APP0 view with decoded fields and hex dump.
        """
        app0_log = self.query_one("#info-app0", RichLog)
        app0_log.clear()
        app0 = next((s for s in segments if s.name == "APP0"), None)
        if app0 is None or app0.payload_offset is None or app0.payload_length is None:
            self._clear_app0_editor()
            app0_log.write("No APP0 segment found.")
            return
        self.app0_segment_info = (app0.offset, app0.total_length, app0.length_field or 0, app0.payload_offset)

        payload = data[app0.payload_offset:app0.payload_offset + app0.payload_length]
        self.app0_original_payload = payload
        self._set_app0_editor_values(payload, app0.length_field or 0)
        decoded = decode_app0(payload)
        self._app0_log_header(app0_log, app0.offset, app0.length_field, app0.payload_length, decoded)

        # Highlight regions with distinct green shades for JFIF fields.
        marker_start = app0.offset
        marker_end = app0.offset + 2
        length_start = app0.payload_offset - 2
        length_end = app0.payload_offset
        payload_start = app0.payload_offset
        payload_end = app0.payload_offset + app0.payload_length

        ranges = self._app0_ranges(
            marker_start, marker_end, length_start, length_end, payload_start, payload, payload_end, app0_log
        )

        dump = self._hex_dump(data, app0.offset, app0.total_length, ranges)
        for line in dump:
            app0_log.write(line)

    def _app0_log_header(self, app0_log: RichLog, offset: int, length_field: int, payload_len: int, decoded) -> None:
        app0_log.write(f"APP0 at 0x{offset:08X} length=0x{length_field:04X} payload={payload_len}")
        if not decoded:
            app0_log.write("Decoded: None (payload not recognized as JFIF/JFXX)")
            return
        self._write_decoded_lines(app0_log, decoded)

    def _clear_app0_editor(self) -> None:
        self.app0_original_payload = None
        self.app0_segment_info = None
        self.query_one("#app0-raw-hex", TextArea).text = ""
        self.query_one("#app0-thumb-hex", TextArea).text = ""
        self.query_one("#app0-length", Input).value = ""
        self.query_one("#app0-ident", Select).value = "JFIF\\0"
        self.query_one("#app0-version", Select).value = "1.01"
        self.query_one("#app0-units", Select).value = "0"
        self.query_one("#app0-xden", Input).value = "1"
        self.query_one("#app0-yden", Input).value = "1"
        self.query_one("#app0-xthumb", Input).value = "0"
        self.query_one("#app0-ythumb", Input).value = "0"
        self._mark_app0_dirty(False)

    def _app0_ranges(
        self,
        marker_start: int,
        marker_end: int,
        length_start: int,
        length_end: int,
        payload_start: int,
        payload: bytes,
        payload_end: int,
        app0_log: RichLog,
    ):
        ranges = [
            (marker_start, marker_end, "bold yellow"),
            (length_start, length_end, "bold cyan"),
        ]
        if len(payload) < 14:
            return ranges
        app0_log.write("Legend:")
        for label, style in [
            ("Identifier (JFIF\\0)", "green"),
            ("Version", "bright_blue"),
            ("Units", "magenta"),
            ("X density", "bright_cyan"),
            ("Y density", "bright_cyan"),
            ("X thumbnail", "bright_yellow"),
            ("Y thumbnail", "bright_yellow"),
            ("Thumbnail data", "red"),
        ]:
            app0_log.write(Text("  " + label, style=style))
        ranges.extend(
            [
                (payload_start, payload_start + 5, "green"),
                (payload_start + 5, payload_start + 7, "bright_blue"),
                (payload_start + 7, payload_start + 8, "magenta"),
                (payload_start + 8, payload_start + 10, "bright_cyan"),
                (payload_start + 10, payload_start + 12, "bright_cyan"),
                (payload_start + 12, payload_start + 13, "bright_yellow"),
                (payload_start + 13, payload_start + 14, "bright_yellow"),
            ]
        )
        thumb_w = payload[12]
        thumb_h = payload[13]
        thumb_bytes = 3 * thumb_w * thumb_h
        thumb_start = payload_start + 14
        thumb_end = min(payload_end, thumb_start + thumb_bytes)
        if thumb_bytes > 0:
            ranges.append((thumb_start, thumb_end, "red"))
        return ranges

    def _set_app0_editor_values(self, payload: bytes, length_field: int) -> None:
        """
        Populate APP0 editor inputs from the current payload.
        """
        # Raw hex view
        self.query_one("#app0-raw-hex", TextArea).text = self._bytes_to_hex(payload)

        # Simple fields (JFIF header if present)
        if len(payload) >= 14:
            ident = payload[:5].decode(errors="ignore")
            if ident == "JFIF\x00":
                self.query_one("#app0-ident", Select).value = "JFIF\\0"
            elif ident == "JFXX\x00":
                self.query_one("#app0-ident", Select).value = "JFXX\\0"
            ver_major = payload[5]
            ver_minor = payload[6]
            units = payload[7]
            xden = int.from_bytes(payload[8:10], "big")
            yden = int.from_bytes(payload[10:12], "big")
            xthumb = payload[12]
            ythumb = payload[13]
            thumb_len = 3 * xthumb * ythumb
            thumb_bytes = payload[14:14 + thumb_len]
            self.query_one("#app0-version", Select).value = f"{ver_major}.{ver_minor:02d}"
            self.query_one("#app0-units", Select).value = str(units)
            self.query_one("#app0-xden", Input).value = str(xden)
            self.query_one("#app0-yden", Input).value = str(yden)
            self.query_one("#app0-xthumb", Input).value = str(xthumb)
            self.query_one("#app0-ythumb", Input).value = str(ythumb)
            self.query_one("#app0-thumb-hex", TextArea).text = self._bytes_to_hex(thumb_bytes)

        self.query_one("#app0-length", Input).value = f"{length_field:04X}"
        self._apply_app0_mode_visibility()

    def _update_app0_length_field(self) -> None:
        """
        Update the length field if manual length is not enabled.
        """
        manual = self.query_one("#app0-manual-length", Checkbox).value
        if manual:
            return
        try:
            payload = self._build_app0_payload()
        except Exception:
            return
        length_field = len(payload) + 2
        self.query_one("#app0-length", Input).value = f"{length_field:04X}"

    def _mark_app0_dirty(self, dirty: bool) -> None:
        """
        Update dirty state and save button enabled status.
        """
        self.app0_dirty = dirty
        self.query_one("#app0-save", Button).disabled = not dirty

    def _bytes_to_hex(self, data: bytes) -> str:
        """
        Format bytes as spaced hex with line breaks every 16 bytes.
        """
        parts = [f"{b:02X}" for b in data]
        lines = [" ".join(parts[i:i + 16]) for i in range(0, len(parts), 16)]
        return "\n".join(lines)

    def _parse_hex(self, text: str) -> bytes:
        """
        Parse a hex string with whitespace into bytes.
        """
        cleaned = []
        for ch in text:
            if ch.isspace():
                cleaned.append(" ")
                continue
            if ch in "0123456789abcdefABCDEF":
                cleaned.append(ch)
                continue
            raise ValueError(f"Invalid hex character: {ch}")
        hex_str = "".join(cleaned)
        compact = "".join(hex_str.split())
        if len(compact) % 2 != 0:
            raise ValueError("Hex string has odd length.")
        return bytes.fromhex(hex_str)

    def _build_app0_payload(self) -> bytes:
        """
        Build APP0 payload from the current editor mode.
        """
        adv = self.query_one("#app0-advanced-mode", Checkbox).value
        if adv:
            return self._parse_hex(self.query_one("#app0-raw-hex", TextArea).text)

        # Simple mode fields
        def _byte(value: str, label: str) -> int:
            v = int(value)
            if v < 0 or v > 255:
                raise ValueError(f"{label} must be 0-255.")
            return v

        def _u16(value: str, label: str) -> int:
            v = int(value)
            if v < 0 or v > 65535:
                raise ValueError(f"{label} must be 0-65535.")
            return v

        ident = self.query_one("#app0-ident", Select).value
        version = self.query_one("#app0-version", Select).value
        if "." not in str(version):
            raise ValueError("Version must be in major.minor format.")
        ver_major_s, ver_minor_s = str(version).split(".", 1)
        ver_major = _byte(ver_major_s, "Version major")
        ver_minor = _byte(ver_minor_s, "Version minor")
        units = _byte(str(self.query_one("#app0-units", Select).value), "Units")
        xden = _u16(self.query_one("#app0-xden", Input).value, "X density")
        yden = _u16(self.query_one("#app0-yden", Input).value, "Y density")
        xthumb = _byte(self.query_one("#app0-xthumb", Input).value, "X thumbnail")
        ythumb = _byte(self.query_one("#app0-ythumb", Input).value, "Y thumbnail")

        thumb_hex = self.query_one("#app0-thumb-hex", TextArea).text.strip()
        thumb_bytes = b""
        if thumb_hex:
            thumb_bytes = self._parse_hex(thumb_hex)

        expected = 3 * xthumb * ythumb
        if expected != len(thumb_bytes):
            raise ValueError(f"Thumbnail data length must be {expected} bytes.")

        payload = bytearray()
        if ident == "JFXX\\0":
            payload.extend(b"JFXX\x00")
        else:
            payload.extend(b"JFIF\x00")
        payload.append(ver_major)
        payload.append(ver_minor)
        payload.append(units)
        payload.extend(xden.to_bytes(2, "big"))
        payload.extend(yden.to_bytes(2, "big"))
        payload.append(xthumb)
        payload.append(ythumb)
        payload.extend(thumb_bytes)
        return bytes(payload)

    @on(Button.Pressed, "#app0-save")
    def _on_app0_save(self) -> None:
        """
        Save the edited APP0 payload to a new file.
        """
        err = self.query_one("#app0-edit-error", Static)
        err.update("")
        try:
            input_path, payload, length_field = self._app0_save_inputs()
        except Exception as e:
            err.update(f"Error: {e}")
            return
        out_path = self._app0_write_file(input_path, payload, length_field)
        self._app0_save_log(out_path, payload, length_field)
        self._mark_app0_dirty(False)

    def _app0_save_inputs(self) -> Tuple[str, bytes, int]:
        input_path = self.query_one("#input-path", Input).value.strip()
        if not input_path:
            raise ValueError("input path is required.")
        if not self.app0_segment_info:
            raise ValueError("APP0 not loaded. Click Load Info first.")
        payload = self._build_app0_payload()
        length_field = self._app0_length_from_ui(payload)
        return input_path, payload, length_field

    def _app0_length_from_ui(self, payload: bytes) -> int:
        if not self.query_one("#app0-manual-length", Checkbox).value:
            return len(payload) + 2
        length_text = self.query_one("#app0-length", Input).value.strip()
        if not length_text:
            raise ValueError("length is required in manual mode.")
        try:
            length_field = int(length_text, 16)
        except ValueError:
            raise ValueError("length must be hex (e.g., 0010).")
        if length_field < 2:
            raise ValueError("length must be >= 2.")
        return length_field

    def _app0_write_file(self, input_path: str, payload: bytes, length_field: int) -> Path:
        offset, total_len, _, _ = self.app0_segment_info
        data = Path(input_path).read_bytes()
        marker = data[offset:offset + 2]
        new_seg = marker + length_field.to_bytes(2, "big") + payload
        new_data = data[:offset] + new_seg + data[offset + total_len:]
        out_path = Path(input_path).with_name(Path(input_path).stem + "_app0_edit.jpg")
        idx = 1
        while out_path.exists():
            out_path = Path(input_path).with_name(Path(input_path).stem + f"_app0_edit_{idx}.jpg")
            idx += 1
        out_path.write_bytes(new_data)
        return out_path

    def _app0_save_log(self, out_path: Path, payload: bytes, length_field: int) -> None:
        log = self.query_one("#info-app0", RichLog)
        log.write(f"Saved edited file: {out_path}")
        if self.query_one("#app0-manual-length", Checkbox).value:
            expected = len(payload) + 2
            if length_field != expected:
                log.write(f"Warning: manual length {length_field} does not match payload ({expected}).")

    def _app1_key_from_id(self, widget_id: Optional[str], suffix: str) -> Optional[str]:
        if not widget_id or not widget_id.startswith("app1-") or not widget_id.endswith(suffix):
            return None
        return widget_id[: -len(suffix)]

    def _app1_save_inputs(self, key: str) -> Tuple[str, bytes]:
        input_path = self.query_one("#input-path", Input).value.strip()
        if not input_path:
            raise ValueError("input path is required.")
        if key not in self.app1_segment_info:
            raise ValueError("APP1 not loaded. Click Load Info first.")
        if piexif is None:
            raise ValueError("piexif is not installed.")
        text = self.query_one(f"#{key}-dict-editor", TextArea).text.strip()
        if not text:
            raise ValueError("EXIF editor is empty.")
        exif_dict = self._app1_parse_exif_dict(text)
        exif_bytes = piexif.dump(exif_dict)
        payload = b"Exif\x00\x00" + exif_bytes
        if len(payload) + 2 > 0xFFFF:
            raise ValueError("EXIF payload too large for APP1.")
        return input_path, payload

    def _app1_parse_exif_dict(self, text: str) -> dict:
        try:
            data = ast.literal_eval(text)
        except Exception as e:
            raise ValueError(f"Invalid EXIF dict: {e}")
        if not isinstance(data, dict):
            raise ValueError("EXIF editor must be a dict.")
        for key in ["0th", "Exif", "GPS", "1st", "Interop"]:
            if key not in data:
                data[key] = {}
            if not isinstance(data[key], dict):
                raise ValueError(f"EXIF {key} must be a dict.")
        if "thumbnail" not in data or data["thumbnail"] is None:
            data["thumbnail"] = b""
        if not isinstance(data["thumbnail"], (bytes, bytearray)):
            raise ValueError("EXIF thumbnail must be bytes.")
        return data

    def _app1_write_file(self, input_path: str, key: str, payload: bytes) -> Path:
        offset, total_len, _, _ = self.app1_segment_info[key]
        data = Path(input_path).read_bytes()
        marker = data[offset:offset + 2]
        length_field = len(payload) + 2
        new_seg = marker + length_field.to_bytes(2, "big") + payload
        new_data = data[:offset] + new_seg + data[offset + total_len:]
        out_path = Path(input_path).with_name(Path(input_path).stem + "_app1_edit.jpg")
        idx = 1
        while out_path.exists():
            out_path = Path(input_path).with_name(Path(input_path).stem + f"_app1_edit_{idx}.jpg")
            idx += 1
        out_path.write_bytes(new_data)
        return out_path

    def _app1_preview_data(self, data: bytes, seg, payload: bytes) -> bytes:
        return data[:seg.payload_offset] + payload + data[seg.payload_offset + seg.payload_length:]

    def _app1_seg_from_info(self, seg_info: Tuple[int, int, int, int], payload: bytes):
        offset, total_len, length_field, payload_offset = seg_info
        seg = type("Seg", (), {})()
        seg.offset = offset
        seg.total_length = total_len
        seg.length_field = length_field
        seg.payload_offset = payload_offset
        seg.payload_length = len(payload)
        return seg

    def _hex_total_pages(self) -> int:
        if not self.info_data:
            return 0
        return max(1, (len(self.info_data) + 511) // 512)

    def _hex_segment_ranges(self) -> list[Tuple[int, int, str]]:
        if not self.info_segments:
            return []
        palette = [
            "bright_blue",
            "bright_cyan",
            "bright_green",
            "bright_magenta",
            "bright_red",
            "bright_yellow",
            "cyan",
            "green",
            "magenta",
            "yellow",
            "blue",
            "red",
            "white",
            "bright_white",
            "bold green",
            "bold cyan",
            "bold magenta",
            "bold red",
            "bold yellow",
            "bold blue",
        ]
        ranges: list[Tuple[int, int, str]] = []
        for idx, seg in enumerate(self.info_segments):
            start = seg.offset
            end = seg.offset + seg.total_length
            ranges.append((start, end, palette[idx % len(palette)]))
        return ranges

    def _render_full_hex_page(self) -> None:
        if self.info_data is None:
            return
        legend = self.query_one("#info-hex-legend", ListView)
        log = self.query_one("#info-hex", RichLog)
        legend.clear()
        log.clear()
        page = max(0, self.hex_page)
        total = self._hex_total_pages()
        page = min(page, total - 1)
        self.hex_page = page
        start = page * 512
        end = min(start + 512, len(self.info_data))
        info = self.query_one("#hex-page-info", Static)
        info.update(f"Page {page + 1}/{total}  0x{start:08X}..0x{end - 1:08X}")
        self.query_one("#hex-page", Input).value = str(page + 1)
        ranges = self._hex_segment_ranges()
        self._write_hex_legend(legend, ranges)
        for line in self._hex_dump(self.info_data, start, end - start, ranges):
            log.write(line)
        log.scroll_to(0, animate=False)

    def _write_hex_legend(self, legend: ListView, ranges: list[Tuple[int, int, str]]) -> None:
        if not self.info_segments:
            return
        self.hex_legend_counter += 1
        self.hex_legend_offsets = {}
        for idx, ((start, end, style), seg) in enumerate(zip(ranges, self.info_segments)):
            item_id = f"hex-seg-{self.hex_legend_counter}-{idx}"
            label = f"{seg.name} 0x{start:08X}..0x{end - 1:08X} ({end - start} bytes)"
            legend.append(ListItem(Label(Text(label, style=style)), id=item_id))
            self.hex_legend_offsets[item_id] = start

    def _on_app1_header_hex_changed(self, key: str) -> None:
        if key not in self.app1_segment_info:
            return
        err = self.query_one(f"#{key}-error", Static)
        header_hex = self.query_one(f"#{key}-header-hex", TextArea).text
        try:
            header = self._parse_hex(header_hex)
        except Exception as e:
            err.update(f"Error: {e}")
            return
        if len(header) != 14:
            err.update("Error: header must be exactly 14 bytes (Exif + TIFF header).")
            return
        err.update("")
        original = self.app1_original_payload.get(key, b"")
        if len(original) < 14:
            return
        preview = header + original[14:]
        self.app1_preview_payload[key] = preview
        self._refresh_app1_hex_preview(key)

    def _refresh_app1_hex_preview(self, key: str) -> None:
        log_hex = self.query_one(f"#info-{key}-hex", RichLog)
        log_raw = self.query_one(f"#info-{key}-raw", RichLog)
        header = self.query_one(f"#{key}-header", RichLog)
        log_hex.clear()
        log_raw.clear()
        header.clear()
        seg_info = self.app1_segment_info.get(key)
        if not seg_info or self.info_data is None:
            return
        offset, total_len, length_field, payload_offset = seg_info
        seg = self._app1_seg_from_info(seg_info, self.app1_preview_payload.get(key, b""))
        payload = self.app1_preview_payload.get(key, b"")
        data = self._app1_preview_data(self.info_data, seg, payload)
        if not payload.startswith(b"Exif\x00\x00"):
            log_hex.write("APP1 payload is not EXIF (missing Exif\\0\\0 header).")
            self._render_app1_hex(log_hex, data, seg, self._app1_basic_ranges(seg))
            self._render_app1_raw_hex(log_raw, data, seg, self._app1_basic_ranges(seg))
            return
        exif = self._parse_exif(payload, payload_offset)
        if exif.get("error"):
            log_hex.write(f"EXIF decode error: {exif['error']}")
            self._render_app1_hex(log_hex, data, seg, self._app1_basic_ranges(seg))
            self._render_app1_raw_hex(log_raw, data, seg, self._app1_basic_ranges(seg))
            return
        self._write_app1_header(header, exif, seg)
        ranges = self._app1_hex_ranges(seg, exif)
        self._render_app1_hex_sections(log_hex, data, seg, exif, ranges)
        self._render_app1_raw_hex(log_raw, data, seg, ranges, exif)

    def _refresh_app0_preview(self) -> None:
        """
        Re-render APP0 decoded and hex views based on current editor state.
        """
        if not self.app0_segment_info:
            return
        offset, total_len, _, payload_offset = self.app0_segment_info
        app0_log = self.query_one("#info-app0", RichLog)
        err = self.query_one("#app0-edit-error", Static)
        try:
            payload = self._build_app0_payload()
        except Exception as e:
            err.update(f"Error: {e}")
            return
        err.update("")
        length_field = self._preview_length_from_ui(payload, err)
        if length_field is None:
            return
        app0_log.clear()
        self._write_app0_preview_header(app0_log, offset, length_field, payload)
        ranges = self._preview_ranges(payload)
        segment_bytes = self._preview_segment_bytes(payload, length_field)
        for line in self._hex_dump(segment_bytes, 0, len(segment_bytes), ranges):
            app0_log.write(line)

    def _preview_length_from_ui(self, payload: bytes, err: Static) -> Optional[int]:
        length_field = len(payload) + 2
        if not self.query_one("#app0-manual-length", Checkbox).value:
            return length_field
        length_text = self.query_one("#app0-length", Input).value.strip()
        if not length_text:
            return length_field
        try:
            return int(length_text, 16)
        except ValueError:
            err.update("Error: length must be hex (e.g., 0010).")
            return None

    def _write_app0_preview_header(self, app0_log: RichLog, offset: int, length_field: int, payload: bytes) -> None:
        app0_log.write("Legend:")
        for label, style in [
            ("Identifier (JFIF\\0)", "green"),
            ("Version", "bright_blue"),
            ("Units", "magenta"),
            ("X density", "bright_cyan"),
            ("Y density", "bright_cyan"),
            ("X thumbnail", "bright_yellow"),
            ("Y thumbnail", "bright_yellow"),
            ("Thumbnail data", "red"),
        ]:
            app0_log.write(Text("  " + label, style=style))
        decoded = decode_app0(payload)
        app0_log.write(f"APP0 at 0x{offset:08X} length=0x{length_field:04X} payload={len(payload)}")
        if decoded:
            self._write_decoded_lines(app0_log, decoded)
        else:
            app0_log.write("Decoded: None (payload not recognized as JFIF/JFXX)")

    def _write_decoded_lines(self, app0_log: RichLog, decoded) -> None:
        app0_log.write("Decoded:")
        if "type" in decoded:
            ident = decoded["type"]
            if ident in {"JFIF", "JFXX"}:
                ident = ident + "\\0"
            app0_log.write(Text(f"  Identifier: {ident}", style="green"))
        if "version" in decoded:
            app0_log.write(Text(f"  Version: {decoded['version']}", style="bright_blue"))
        if "units" in decoded:
            units_map = {"0": "none", "1": "dpi", "2": "dpcm"}
            units_label = units_map.get(decoded["units"], "unknown")
            app0_log.write(Text(f"  Units: {decoded['units']} ({units_label})", style="magenta"))
        if "x_density" in decoded:
            app0_log.write(Text(f"  X density: {decoded['x_density']}", style="bright_cyan"))
        if "y_density" in decoded:
            app0_log.write(Text(f"  Y density: {decoded['y_density']}", style="bright_cyan"))

    def _preview_ranges(self, payload: bytes):
        # Synthetic segment layout: [marker][length][payload]
        marker_start, marker_end = 0, 2
        length_start, length_end = 2, 4
        payload_start = 4
        payload_end = payload_start + len(payload)
        ranges = [
            (marker_start, marker_end, "bold yellow"),
            (length_start, length_end, "bold cyan"),
        ]
        if len(payload) < 14:
            return ranges
        ranges.extend(
            [
                (payload_start, payload_start + 5, "green"),
                (payload_start + 5, payload_start + 7, "bright_blue"),
                (payload_start + 7, payload_start + 8, "magenta"),
                (payload_start + 8, payload_start + 10, "bright_cyan"),
                (payload_start + 10, payload_start + 12, "bright_cyan"),
                (payload_start + 12, payload_start + 13, "bright_yellow"),
                (payload_start + 13, payload_start + 14, "bright_yellow"),
            ]
        )
        thumb_w = payload[12]
        thumb_h = payload[13]
        thumb_bytes = 3 * thumb_w * thumb_h
        thumb_start = payload_start + 14
        thumb_end = min(payload_end, thumb_start + thumb_bytes)
        if thumb_bytes > 0:
            ranges.append((thumb_start, thumb_end, "red"))
        return ranges

    def _preview_segment_bytes(self, payload: bytes, length_field: int) -> bytes:
        header = bytearray()
        header.extend(b"\xFF\xE0")
        header.extend(length_field.to_bytes(2, "big"))
        return bytes(header) + payload

    @on(Button.Pressed, "#tool-appn-insert")
    def _on_tool_appn_insert(self) -> None:
        """
        Insert a custom APPn segment into the selected JPEG.
        """
        err = self.query_one("#tool-appn-error", Static)
        log = self.query_one("#tool-appn-log", RichLog)
        err.update("")
        log.clear()

        input_path = self.query_one("#tool-appn-input", Input).value.strip()
        if not input_path:
            err.update("Error: input path is required.")
            return
        try:
            appn = int(self.query_one("#tool-appn-index", Input).value.strip())
        except ValueError:
            err.update("Error: APPn index must be an integer.")
            return
        ident = self.query_one("#tool-appn-ident", Input).value
        payload_hex = self.query_one("#tool-appn-hex", TextArea).text.strip()
        payload_file = self.query_one("#tool-appn-file", Input).value.strip()
        output_path = self.query_one("#tool-appn-output", Input).value.strip()

        if bool(payload_hex) == bool(payload_file):
            err.update("Error: provide exactly one of payload hex or payload file.")
            return
        try:
            data = Path(input_path).read_bytes()
            if payload_hex:
                payload = read_payload_hex(payload_hex)
            else:
                payload = Path(payload_file).read_bytes()
            if ident:
                payload = ident.encode("ascii", errors="strict") + payload
            out_data = insert_custom_appn(data, appn, payload)
            out_path = output_path_for(input_path, appn, output_path or None)
            Path(out_path).write_bytes(out_data)
            log.write(f"Wrote {out_path} (APP{appn:02d}, payload={len(payload)} bytes)")
        except Exception as e:
            err.update(f"Error: {e}")

    def _hex_dump(self, data: bytes, start: int, length: int, ranges) -> list[Text]:
        """
        Build a colored hex dump with offsets and ASCII column.
        """
        end = min(len(data), start + length)
        lines: list[Text] = []
        for off in range(start, end, 16):
            chunk = data[off:min(off + 16, end)]
            line = Text(f"{off:08X}  ", style="white")
            ascii_text = Text()
            for i, b in enumerate(chunk):
                pos = off + i
                style = self._style_for_pos(pos, ranges)
                line.append(f"{b:02X} ", style=style)
                ascii_char = chr(b) if 32 <= b <= 126 else "."
                ascii_text.append(ascii_char, style=style)
            pad = "   " * (16 - len(chunk))
            line.append(pad, style="white")
            line.append(" |", style="white")
            line.append(ascii_text)
            line.append("|", style="white")
            lines.append(line)
        return lines

    def _style_for_pos(self, pos: int, ranges) -> str:
        """
        Return the color style for a given byte position based on ranges.
        """
        for start, end, style in ranges:
            if start <= pos < end:
                return style
        return ""

    @on(Button.Pressed, "#run-btn")
    def _on_run_pressed(self) -> None:
        error = self.query_one("#run-error", Static)
        error.update("")
        log = self.query_one("#log", RichLog)
        log.clear()

        try:
            options = self._build_options()
        except ValueError as e:
            error.update(f"Error: {e}")
            return

        def _run() -> api.RunResult:
            return api.run(options, emit_report=False)

        self.run_worker(_run, exclusive=True, name="run", group="run", thread=True)

    @on(Worker.StateChanged)
    def _on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """
        Handle worker completion for the run pipeline.
        """
        if event.worker.name != "run":
            return
        if event.state == WorkerState.ERROR:
            error = self.query_one("#run-error", Static)
            error.update(f"Error: {event.worker.error}")
            return
        if event.state != WorkerState.SUCCESS:
            return

        result = event.worker.result
        log = self.query_one("#log", RichLog)
        log.write(f"Done. Mutations: {result.mutation_count}")
        if result.gif_frames is not None:
            log.write(f"GIF frames: {result.gif_frames}")
        if result.ssim_sets is not None:
            log.write(f"SSIM sets: {result.ssim_sets}")
        if result.metric_sets:
            for path, count in result.metric_sets.items():
                log.write(f"Metric chart: {path} (sets={count})")
        if result.wave_len is not None:
            log.write(f"Wave chart bytes: {result.wave_len}")
        if result.sliding_len is not None:
            log.write(f"Sliding wave bytes: {result.sliding_len}")
        if result.dc_blocks is not None:
            by, bx = result.dc_blocks
            log.write(f"DC heatmap blocks: {by}x{bx}")
        if result.ac_blocks is not None:
            by, bx = result.ac_blocks
            log.write(f"AC heatmap blocks: {by}x{bx}")


def run_tui(defaults: Optional[TuiDefaults] = None) -> None:
    """
    Launch the Textual TUI.
    """
    app = JpegFaultTui(defaults=defaults)
    app.run()

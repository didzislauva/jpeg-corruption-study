"""
Textual-based fullscreen TUI for the JPEG fault tolerance tool.

The TUI is designed for interactive use and mirrors the CLI options, allowing
users to select input files, mutation strategies, outputs, and then execute the
run via the core API layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from pprint import pformat
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
from .jpeg_parse import (
    build_dri_payload,
    build_dht_payload,
    build_dqt_payload,
    build_sof0_payload,
    decode_app0,
    decode_dri,
    decode_dht,
    decode_dht_tables,
    decode_dqt,
    decode_dqt_tables,
    decode_sof0,
    decode_sof_components,
    decode_sos_components,
    dqt_natural_grid_to_values,
    dqt_values_to_natural_grid,
    parse_jpeg,
)
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
    .dqt-left { width: 1fr; border: solid $secondary; }
    .dqt-right { width: 1fr; border: solid $secondary; }
    .dht-left { width: 1fr; border: solid $secondary; }
    .dht-right { width: 1fr; border: solid $secondary; }
    .dri-left { width: 1fr; border: solid $secondary; }
    .dri-right { width: 1fr; border: solid $secondary; }
    .sof-left { width: 1fr; border: solid $secondary; }
    .sof-right { width: 1fr; border: solid $secondary; }
    .dqt-log { height: 1fr; }
    .dqt-edit-area { height: 16; }
    .dht-log { height: 1fr; }
    .dht-edit-area { height: 16; }
    .dri-log { height: 1fr; }
    .dri-edit-area { height: 16; }
    .sof-log { height: 1fr; }
    .sof-edit-area { height: 16; }
    #input-left { width: 1fr; }
    #input-fields { width: 1fr; }
    #input-right { width: 2fr; }
    #file-tree { height: 1fr; }
    #jpg-list { height: 1fr; }
    #input-preview { height: 1fr; content-align: center middle; }
    #input-meta { content-align: center middle; }
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
    preview_path: Optional[str] = None
    app2_segment_info: dict[str, Tuple[int, int, int, int]] = {}
    app2_original_payload: dict[str, bytes] = {}
    app2_preview_payload: dict[str, bytes] = {}
    app2_dirty: dict[str, bool] = {}
    app2_tag_types: dict[str, dict[str, str]] = {}
    dqt_segment_info: dict[str, Tuple[int, int, int, int]] = {}
    dqt_original_payload: dict[str, bytes] = {}
    dqt_preview_payload: dict[str, bytes] = {}
    dqt_dirty: dict[str, bool] = {}
    dht_segment_info: dict[str, Tuple[int, int, int, int]] = {}
    dht_original_payload: dict[str, bytes] = {}
    dht_preview_payload: dict[str, bytes] = {}
    dht_dirty: dict[str, bool] = {}
    dri_segment_info: Optional[Tuple[int, int, int, int]] = None
    dri_original_payload: Optional[bytes] = None
    dri_preview_payload: Optional[bytes] = None
    dri_dirty = reactive(False)
    sof0_segment_info: Optional[Tuple[int, int, int, int]] = None
    sof0_original_payload: Optional[bytes] = None
    sof0_preview_payload: Optional[bytes] = None
    sof0_dirty = reactive(False)

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
        self.call_later(self._init_info_tabs)
        self.call_later(self._init_sof0_tabs)
        self.call_later(self._init_dri_tabs)
        self.call_later(self._apply_app0_mode_visibility)
        self.call_later(self._apply_dri_mode_visibility)
        self.call_later(self._apply_sof0_mode_visibility)
        self.call_later(lambda: self._set_current_dir(Path(".")))

    def on_resize(self) -> None:
        if self.preview_path:
            self._update_input_preview(self.preview_path)
        try:
            panel = self.query_one("#panel-input", VerticalScroll)
        except Exception:
            return
        panel.refresh(layout=True)

    def _build_input_panel(self) -> VerticalScroll:
        panel = VerticalScroll(
            Horizontal(
                Vertical(
                    Label("Current directory", classes="field"),
                    Static(".", id="current-dir"),
                    Label("Folders", classes="field"),
                    JpegOnlyDirTree(".", id="file-tree"),
                    Label("JPEG files", classes="field"),
                    ListView(id="jpg-list"),
                    id="input-left",
                ),
                Vertical(
                    Label("Input JPEG path", classes="field"),
                    Input(value=self.defaults.input_path, id="input-path"),
                    Label("Output directory", classes="field"),
                    Input(value=self.defaults.output_dir, id="output-dir"),
                    Label("Color mode (auto|always|never)", classes="field"),
                    Input(value=self.defaults.color, id="color-mode"),
                    id="input-fields",
                ),
                Vertical(
                    Label("Preview", classes="field"),
                    Static("No preview loaded.", id="input-preview"),
                    Static("", id="input-meta"),
                    id="input-right",
                ),
                classes="row",
            ),
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
        suffix = event.path.suffix.lower()
        if suffix not in {".jpg", ".jpeg"}:
            return
        input_widget = self.query_one("#input-path", Input)
        input_widget.value = str(event.path)
        self._update_input_preview(str(event.path))
        self._auto_load_info()

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
        path = str(Path(self.current_dir) / filename)
        input_widget.value = path
        self._update_input_preview(path)
        self._auto_load_info()
        self._mark_app0_dirty(False)

    @on(Input.Changed, "#input-path")
    def _on_input_path_changed(self, event: Input.Changed) -> None:
        path = event.input.value.strip()
        if not path or path == self.preview_path:
            return
        if not Path(path).exists():
            return
        if Path(path).suffix.lower() not in {".jpg", ".jpeg"}:
            return
        self._update_input_preview(path)
        self._auto_load_info()

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
        self._add_sof0_tab()
        self._add_dri_tab()
        self._add_appn_tab()
        self._add_dqt_tab()
        self._add_dht_tab()
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

    def _add_sof0_tab(self) -> None:
        tabs = self.query_one("#info-tabs", TabbedContent)
        tabs.add_pane(TabPane("SOF0", self._build_sof0_pane()))

    def _add_dri_tab(self) -> None:
        tabs = self.query_one("#info-tabs", TabbedContent)
        tabs.add_pane(TabPane("DRI", self._build_dri_pane()))

    def _add_dqt_tab(self) -> None:
        tabs = self.query_one("#info-tabs", TabbedContent)
        tabs.add_pane(TabPane("DQT", self._build_dqt_pane()))
        self._reset_dqt_tabs([])

    def _add_dht_tab(self) -> None:
        tabs = self.query_one("#info-tabs", TabbedContent)
        tabs.add_pane(TabPane("DHT", self._build_dht_pane()))
        self._reset_dht_tabs([])

    def _build_appn_pane(self) -> Vertical:
        return Vertical(
            Static("APPn segments (APP0, APP1, ...)", classes="field"),
            TabbedContent(id="appn-tabs"),
            id="appn-panel",
        )

    def _build_sof0_pane(self) -> Horizontal:
        return Horizontal(
            VerticalScroll(
                Static("SOF0 bytes and frame summary", classes="field"),
                RichLog(id="info-sof0-left", highlight=True, classes="sof-log sof-left"),
            ),
            VerticalScroll(
                Static("Views: frame, components, tables, edit", classes="field"),
                TabbedContent(id="sof0-tabs"),
                classes="sof-right",
            ),
            classes="row",
        )

    def _build_dri_pane(self) -> Horizontal:
        return Horizontal(
            VerticalScroll(
                Static("DRI bytes and restart summary", classes="field"),
                RichLog(id="info-dri-left", highlight=True, classes="dri-log dri-left"),
            ),
            VerticalScroll(
                Static("Views: summary, effect, edit", classes="field"),
                TabbedContent(id="dri-tabs"),
                classes="dri-right",
            ),
            classes="row",
        )

    def _init_sof0_tabs(self) -> None:
        tabs = self.query_one("#sof0-tabs", TabbedContent)
        tabs.clear_panes()
        for name in ("Frame", "Components", "Tables"):
            pane_id = name.lower()
            tabs.add_pane(TabPane(name, RichLog(id=f"info-sof0-{pane_id}", highlight=True, classes="sof-log")))
        tabs.add_pane(
            TabPane(
                "Edit",
                VerticalScroll(
                    Static("Edit SOF0 frame fields as Python literal or raw payload hex.", classes="field"),
                    Checkbox("Advanced mode (raw payload hex)", value=False, id="sof0-advanced-mode"),
                    Checkbox("Manual length (dangerous)", value=False, id="sof0-manual-length"),
                    Input(value="", id="sof0-length", placeholder="Length (hex, e.g. 0011)"),
                    Button("Save edited file", id="sof0-save", variant="success", disabled=True),
                    Static("", id="sof0-edit-error"),
                    Static("Structured editor", classes="field", id="sof0-simple-title"),
                    TextArea("", id="sof0-struct-edit", soft_wrap=True, show_line_numbers=True, classes="sof-edit-area"),
                    Static("Raw payload hex", classes="field", id="sof0-adv-title"),
                    TextArea("", id="sof0-raw-hex", soft_wrap=True, show_line_numbers=True, classes="sof-edit-area"),
                ),
            )
        )

    def _init_dri_tabs(self) -> None:
        tabs = self.query_one("#dri-tabs", TabbedContent)
        tabs.clear_panes()
        for name in ("Summary", "Effect"):
            pane_id = name.lower()
            tabs.add_pane(TabPane(name, RichLog(id=f"info-dri-{pane_id}", highlight=True, classes="dri-log")))
        tabs.add_pane(
            TabPane(
                "Edit",
                VerticalScroll(
                    Static("Edit DRI restart interval or raw payload hex.", classes="field"),
                    Checkbox("Advanced mode (raw payload hex)", value=False, id="dri-advanced-mode"),
                    Checkbox("Manual length (dangerous)", value=False, id="dri-manual-length"),
                    Input(value="", id="dri-length", placeholder="Length (hex, e.g. 0004)"),
                    Button("Save edited file", id="dri-save", variant="success", disabled=True),
                    Static("", id="dri-edit-error"),
                    Static("Structured editor", classes="field", id="dri-simple-title"),
                    TextArea("", id="dri-struct-edit", soft_wrap=True, show_line_numbers=True, classes="dri-edit-area"),
                    Static("Raw payload hex", classes="field", id="dri-adv-title"),
                    TextArea("", id="dri-raw-hex", soft_wrap=True, show_line_numbers=True, classes="dri-edit-area"),
                ),
            )
        )

    def _build_dqt_pane(self) -> Vertical:
        return Vertical(
            Static("Quantization tables (DQT)", classes="field"),
            TabbedContent(id="dqt-tabs"),
            id="dqt-panel",
        )

    def _build_dht_pane(self) -> Vertical:
        return Vertical(
            Static("Huffman tables (DHT)", classes="field"),
            TabbedContent(id="dht-tabs"),
            id="dht-panel",
        )

    def _build_dqt_segment_pane(self, key: str, title: str) -> Horizontal:
        return Horizontal(
            VerticalScroll(
                Static(f"{title} bytes and structure", classes="field"),
                RichLog(id=f"info-{key}-left", highlight=True, classes="dqt-log dqt-left"),
            ),
            VerticalScroll(
                Static("Views: grid, zigzag, stats, usage, heatmap, edit", classes="field"),
                TabbedContent(id=f"{key}-tabs"),
                classes="dqt-right",
            ),
            classes="row",
        )

    def _init_dqt_detail_tabs(self, key: str) -> None:
        tabs = self.query_one(f"#{key}-tabs", TabbedContent)
        tabs.clear_panes()
        for name in ("Grid", "Zigzag", "Stats", "Usage", "Heatmap"):
            pane_id = name.lower()
            tabs.add_pane(
                TabPane(name, RichLog(id=f"info-{key}-{pane_id}", highlight=True, classes="dqt-log"))
            )
        tabs.add_pane(
            TabPane(
                "Edit",
                VerticalScroll(
                    Static("Edit DQT tables in natural 8x8 order or raw payload hex.", classes="field"),
                    Checkbox("Advanced mode (raw payload hex)", value=False, id=f"{key}-advanced-mode"),
                    Checkbox("Manual length (dangerous)", value=False, id=f"{key}-manual-length"),
                    Input(value="", id=f"{key}-length", placeholder="Length (hex, e.g. 0043)"),
                    Button("Save edited file", id=f"{key}-save", variant="success", disabled=True),
                    Static("", id=f"{key}-error"),
                    Static("Natural-grid editor", classes="field", id=f"{key}-simple-title"),
                    TextArea("", id=f"{key}-grid-edit", soft_wrap=True, show_line_numbers=True, classes="dqt-edit-area"),
                    Static("Raw payload hex", classes="field", id=f"{key}-adv-title"),
                    TextArea("", id=f"{key}-raw-hex", soft_wrap=True, show_line_numbers=True, classes="dqt-edit-area"),
                ),
            )
        )

    def _build_dht_segment_pane(self, key: str, title: str) -> Horizontal:
        return Horizontal(
            VerticalScroll(
                Static(f"{title} bytes and structure", classes="field"),
                RichLog(id=f"info-{key}-left", highlight=True, classes="dht-log dht-left"),
            ),
            VerticalScroll(
                Static("Views: tables, counts, symbols, usage, codes, edit", classes="field"),
                TabbedContent(id=f"{key}-tabs"),
                classes="dht-right",
            ),
            classes="row",
        )

    def _init_dht_detail_tabs(self, key: str) -> None:
        tabs = self.query_one(f"#{key}-tabs", TabbedContent)
        tabs.clear_panes()
        for name in ("Tables", "Counts", "Symbols", "Usage", "Codes"):
            pane_id = name.lower()
            tabs.add_pane(
                TabPane(name, RichLog(id=f"info-{key}-{pane_id}", highlight=True, classes="dht-log"))
            )
        tabs.add_pane(
            TabPane(
                "Edit",
                VerticalScroll(
                    Static("Edit DHT tables as Python literal or raw payload hex.", classes="field"),
                    Checkbox("Advanced mode (raw payload hex)", value=False, id=f"{key}-advanced-mode"),
                    Checkbox("Manual length (dangerous)", value=False, id=f"{key}-manual-length"),
                    Input(value="", id=f"{key}-length", placeholder="Length (hex, e.g. 001F)"),
                    Button("Save edited file", id=f"{key}-save", variant="success", disabled=True),
                    Static("", id=f"{key}-error"),
                    Static("Structured editor", classes="field", id=f"{key}-simple-title"),
                    TextArea("", id=f"{key}-table-edit", soft_wrap=True, show_line_numbers=True, classes="dht-edit-area"),
                    Static("Raw payload hex", classes="field", id=f"{key}-adv-title"),
                    TextArea("", id=f"{key}-raw-hex", soft_wrap=True, show_line_numbers=True, classes="dht-edit-area"),
                ),
            )
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

    def _build_app2_pane(self, key: str, title: str) -> Horizontal:
        return Horizontal(
            VerticalScroll(
                Static(f"{title} info (decoded + hex)", classes="field"),
                TabbedContent(id=f"{key}-tabs"),
                id=f"{key}-info",
            ),
            VerticalScroll(
                TabbedContent(id=f"{key}-right-tabs"),
                id=f"{key}-right",
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

    def _update_input_preview(self, path: str) -> None:
        preview = self.query_one("#input-preview", Static)
        meta = self.query_one("#input-meta", Static)
        self.preview_path = path
        try:
            data = Path(path).read_bytes()
        except Exception as e:
            preview.update("Preview error.")
            meta.update(f"Error: {e}")
            return
        size_bytes = len(data)
        try:
            from PIL import Image as PilImage
        except Exception:
            preview.update("Pillow not available for thumbnail.")
            meta.update(f"Size: {size_bytes} bytes")
            return
        try:
            with PilImage.open(path) as img:
                width, height = img.size
                max_w, max_h = self._preview_box_size(preview)
                thumb = self._thumbnail_ascii(img, max_w, max_h)
        except Exception as e:
            preview.update("Preview error.")
            meta.update(f"Size: {size_bytes} bytes | Error: {e}")
            return
        preview.update(thumb)
        meta.update(f"{width} x {height} | {size_bytes} bytes")

    def _thumbnail_ascii(self, img, max_w: int, max_h: int) -> str:
        chars = " .:-=+*#%@"
        w, h = img.size
        if w == 0 or h == 0:
            return ""
        max_w = max(10, max_w)
        max_h = max(6, max_h)
        scale_w = max_w / w
        scale_h = max_h / (h * 0.55)
        scale = min(scale_w, scale_h)
        width = max(4, int(w * scale))
        height = max(4, int(h * scale * 0.55))
        thumb = img.convert("L").resize((width, height))
        pixels = list(thumb.getdata())
        lines = []
        for y in range(height):
            row = pixels[y * width : (y + 1) * width]
            line = "".join(chars[p * (len(chars) - 1) // 255] for p in row)
            lines.append(line)
        return "\n".join(lines)

    def _preview_box_size(self, preview: Static) -> Tuple[int, int]:
        size = preview.size
        if size.width and size.height:
            return size.width, size.height
        return 40, 12

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
        try:
            adv = self.query_one("#app0-advanced-mode", Checkbox).value
            self.query_one("#app0-simple", Vertical).display = not adv
            self.query_one("#app0-simple-title", Static).display = not adv
            self.query_one("#app0-adv-title", Static).display = adv
            self.query_one("#app0-raw-hex", TextArea).display = adv

            manual = self.query_one("#app0-manual-length", Checkbox).value
            self.query_one("#app0-length", Input).disabled = not manual
        except Exception:
            # APP0 editor not mounted (no APP0 tab)
            return

    def _apply_sof0_mode_visibility(self) -> None:
        try:
            adv = self.query_one("#sof0-advanced-mode", Checkbox).value
            self.query_one("#sof0-struct-edit", TextArea).display = not adv
            self.query_one("#sof0-simple-title", Static).display = not adv
            self.query_one("#sof0-raw-hex", TextArea).display = adv
            self.query_one("#sof0-adv-title", Static).display = adv
            manual = self.query_one("#sof0-manual-length", Checkbox).value
            self.query_one("#sof0-length", Input).disabled = not manual
        except Exception:
            return

    def _apply_dri_mode_visibility(self) -> None:
        try:
            adv = self.query_one("#dri-advanced-mode", Checkbox).value
            self.query_one("#dri-struct-edit", TextArea).display = not adv
            self.query_one("#dri-simple-title", Static).display = not adv
            self.query_one("#dri-raw-hex", TextArea).display = adv
            self.query_one("#dri-adv-title", Static).display = adv
            manual = self.query_one("#dri-manual-length", Checkbox).value
            self.query_one("#dri-length", Input).disabled = not manual
        except Exception:
            return

    def _sync_dri_editor_for_mode(self) -> None:
        adv = self.query_one("#dri-advanced-mode", Checkbox).value
        if adv:
            # When switching into raw mode, serialize the structured editor once.
            text = self.query_one("#dri-struct-edit", TextArea).text
            parsed = ast.literal_eval(text)
            if not isinstance(parsed, dict):
                raise ValueError("DRI editor must be a dictionary.")
            payload = build_dri_payload(int(parsed.get("restart_interval", 0)))
            self.query_one("#dri-raw-hex", TextArea).text = self._bytes_to_hex(payload)
            return
        # When switching back, rebuild the structured editor from the current bytes.
        payload = self._parse_hex(self.query_one("#dri-raw-hex", TextArea).text)
        self._set_dri_editor_values(payload, len(payload) + 2)

    def _build_dri_payload(self) -> bytes:
        if self.query_one("#dri-advanced-mode", Checkbox).value:
            return self._parse_hex(self.query_one("#dri-raw-hex", TextArea).text)
        try:
            parsed = ast.literal_eval(self.query_one("#dri-struct-edit", TextArea).text)
        except Exception as e:
            raise ValueError(f"invalid DRI editor content: {e}")
        if not isinstance(parsed, dict):
            raise ValueError("DRI editor must be a dictionary.")
        return build_dri_payload(int(parsed.get("restart_interval", 0)))

    def _dri_length_from_ui(self, payload: bytes) -> int:
        if not self.query_one("#dri-manual-length", Checkbox).value:
            return len(payload) + 2
        text = self.query_one("#dri-length", Input).value.strip()
        if not text:
            raise ValueError("length is required in manual mode.")
        try:
            length_field = int(text, 16)
        except ValueError:
            raise ValueError("length must be hex (e.g. 0004).")
        if length_field < 2:
            raise ValueError("length must be >= 2.")
        return length_field

    def _mark_dri_dirty(self, dirty: bool) -> None:
        self.dri_dirty = dirty
        try:
            self.query_one("#dri-save", Button).disabled = not dirty
        except Exception:
            return

    def _refresh_dri_preview(self) -> None:
        if not self.dri_segment_info:
            return
        err = self.query_one("#dri-edit-error", Static)
        try:
            payload = self._build_dri_payload()
            length_field = self._dri_length_from_ui(payload)
        except Exception as e:
            err.update(f"Error: {e}")
            return
        err.update("")
        self.dri_preview_payload = payload
        offset, _, _, _ = self.dri_segment_info
        self._render_dri_views(offset, length_field, payload)
        self._mark_dri_dirty(True)

    def _dri_save_inputs(self) -> Tuple[str, bytes, int]:
        input_path = self.query_one("#input-path", Input).value.strip()
        if not input_path:
            raise ValueError("input path is required.")
        if not self.dri_segment_info:
            raise ValueError("DRI not loaded. Click Load Info first.")
        payload = self._build_dri_payload()
        return input_path, payload, self._dri_length_from_ui(payload)

    def _dri_write_file(self, input_path: str, payload: bytes, length_field: int) -> Path:
        offset, total_len, _, _ = self.dri_segment_info
        data = Path(input_path).read_bytes()
        marker = data[offset:offset + 2]
        new_seg = marker + length_field.to_bytes(2, "big") + payload
        new_data = data[:offset] + new_seg + data[offset + total_len:]
        out_path = Path(input_path).with_name(Path(input_path).stem + "_dri_edit.jpg")
        idx = 1
        while out_path.exists():
            out_path = Path(input_path).with_name(Path(input_path).stem + f"_dri_edit_{idx}.jpg")
            idx += 1
        out_path.write_bytes(new_data)
        return out_path

    def _dri_save_log(self, out_path: Path, payload: bytes, length_field: int) -> None:
        log = self.query_one("#info-dri-left", RichLog)
        log.write(f"Saved edited file: {out_path}")
        if self.query_one("#dri-manual-length", Checkbox).value and length_field != len(payload) + 2:
            log.write(f"Warning: manual length {length_field} does not match payload ({len(payload) + 2}).")

    def _sync_sof0_editor_for_mode(self) -> None:
        adv = self.query_one("#sof0-advanced-mode", Checkbox).value
        if adv:
            # Mirror the current structured frame header into raw payload hex.
            parsed = ast.literal_eval(self.query_one("#sof0-struct-edit", TextArea).text)
            if not isinstance(parsed, dict):
                raise ValueError("SOF0 editor must be a dictionary.")
            precision = int(parsed.get("precision_bits", 8))
            width = int(parsed.get("width", 0))
            height = int(parsed.get("height", 0))
            components = parsed.get("components", [])
            if not isinstance(components, list):
                raise ValueError("SOF0 components must be a list.")
            normalized = []
            for idx, comp in enumerate(components, start=1):
                if not isinstance(comp, dict):
                    raise ValueError(f"SOF0 component {idx} must be a dictionary.")
                normalized.append({
                    "id": int(comp.get("id", 0)),
                    "h_sampling": int(comp.get("h_sampling", 1)),
                    "v_sampling": int(comp.get("v_sampling", 1)),
                    "quant_table_id": int(comp.get("quant_table_id", 0)),
                })
            payload = build_sof0_payload(precision, width, height, normalized)
            self.query_one("#sof0-raw-hex", TextArea).text = self._bytes_to_hex(payload)
            return
        # Re-derive structured fields from the edited payload when leaving raw mode.
        payload = self._parse_hex(self.query_one("#sof0-raw-hex", TextArea).text)
        self._set_sof0_editor_values(payload, len(payload) + 2)

    def _build_sof0_payload(self) -> bytes:
        if self.query_one("#sof0-advanced-mode", Checkbox).value:
            return self._parse_hex(self.query_one("#sof0-raw-hex", TextArea).text)
        try:
            parsed = ast.literal_eval(self.query_one("#sof0-struct-edit", TextArea).text)
        except Exception as e:
            raise ValueError(f"invalid SOF0 editor content: {e}")
        if not isinstance(parsed, dict):
            raise ValueError("SOF0 editor must be a dictionary.")
        precision = int(parsed.get("precision_bits", 8))
        width = int(parsed.get("width", 0))
        height = int(parsed.get("height", 0))
        components = parsed.get("components", [])
        if not isinstance(components, list):
            raise ValueError("SOF0 components must be a list.")
        normalized = []
        for idx, comp in enumerate(components, start=1):
            if not isinstance(comp, dict):
                raise ValueError(f"SOF0 component {idx} must be a dictionary.")
            normalized.append({
                "id": int(comp.get("id", 0)),
                "h_sampling": int(comp.get("h_sampling", 1)),
                "v_sampling": int(comp.get("v_sampling", 1)),
                "quant_table_id": int(comp.get("quant_table_id", 0)),
            })
        return build_sof0_payload(precision, width, height, normalized)

    def _sof0_length_from_ui(self, payload: bytes) -> int:
        if not self.query_one("#sof0-manual-length", Checkbox).value:
            return len(payload) + 2
        text = self.query_one("#sof0-length", Input).value.strip()
        if not text:
            raise ValueError("length is required in manual mode.")
        try:
            length_field = int(text, 16)
        except ValueError:
            raise ValueError("length must be hex (e.g. 0011).")
        if length_field < 2:
            raise ValueError("length must be >= 2.")
        return length_field

    def _mark_sof0_dirty(self, dirty: bool) -> None:
        self.sof0_dirty = dirty
        try:
            self.query_one("#sof0-save", Button).disabled = not dirty
        except Exception:
            return

    def _refresh_sof0_preview(self) -> None:
        if not self.sof0_segment_info:
            return
        err = self.query_one("#sof0-edit-error", Static)
        try:
            payload = self._build_sof0_payload()
            length_field = self._sof0_length_from_ui(payload)
        except Exception as e:
            err.update(f"Error: {e}")
            return
        err.update("")
        self.sof0_preview_payload = payload
        offset, _, _, _ = self.sof0_segment_info
        self._render_sof0_views(offset, length_field, payload)
        self._mark_sof0_dirty(True)

    def _sof0_save_inputs(self) -> Tuple[str, bytes, int]:
        input_path = self.query_one("#input-path", Input).value.strip()
        if not input_path:
            raise ValueError("input path is required.")
        if not self.sof0_segment_info:
            raise ValueError("SOF0 not loaded. Click Load Info first.")
        payload = self._build_sof0_payload()
        return input_path, payload, self._sof0_length_from_ui(payload)

    def _sof0_write_file(self, input_path: str, payload: bytes, length_field: int) -> Path:
        offset, total_len, _, _ = self.sof0_segment_info
        data = Path(input_path).read_bytes()
        marker = data[offset:offset + 2]
        new_seg = marker + length_field.to_bytes(2, "big") + payload
        new_data = data[:offset] + new_seg + data[offset + total_len:]
        out_path = Path(input_path).with_name(Path(input_path).stem + "_sof0_edit.jpg")
        idx = 1
        while out_path.exists():
            out_path = Path(input_path).with_name(Path(input_path).stem + f"_sof0_edit_{idx}.jpg")
            idx += 1
        out_path.write_bytes(new_data)
        return out_path

    def _sof0_save_log(self, out_path: Path, payload: bytes, length_field: int) -> None:
        log = self.query_one("#info-sof0-left", RichLog)
        log.write(f"Saved edited file: {out_path}")
        if self.query_one("#sof0-manual-length", Checkbox).value and length_field != len(payload) + 2:
            log.write(f"Warning: manual length {length_field} does not match payload ({len(payload) + 2}).")

    @on(Checkbox.Changed, "#app0-advanced-mode")
    def _on_app0_mode_changed(self) -> None:
        self._apply_app0_mode_visibility()
        self._update_app0_length_field()
        self._refresh_app0_preview()
        self._mark_app0_dirty(True)

    @on(Checkbox.Changed)
    def _on_sof0_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id == "sof0-advanced-mode":
            self._apply_sof0_mode_visibility()
            try:
                self._sync_sof0_editor_for_mode()
            except Exception:
                pass
            self._refresh_sof0_preview()
            return
        if event.checkbox.id != "sof0-manual-length":
            return
        self._apply_sof0_mode_visibility()
        if not event.checkbox.value and self.sof0_preview_payload is not None:
            self.query_one("#sof0-length", Input).value = f"{len(self.sof0_preview_payload) + 2:04X}"
        self._refresh_sof0_preview()

    @on(Checkbox.Changed)
    def _on_dri_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id == "dri-advanced-mode":
            self._apply_dri_mode_visibility()
            try:
                self._sync_dri_editor_for_mode()
            except Exception:
                pass
            self._refresh_dri_preview()
            return
        if event.checkbox.id != "dri-manual-length":
            return
        self._apply_dri_mode_visibility()
        if not event.checkbox.value and self.dri_preview_payload is not None:
            self.query_one("#dri-length", Input).value = f"{len(self.dri_preview_payload) + 2:04X}"
        self._refresh_dri_preview()

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

    @on(Input.Changed)
    def _on_sof0_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "sof0-length":
            return
        self._mark_sof0_dirty(True)
        if self.query_one("#sof0-manual-length", Checkbox).value:
            self._refresh_sof0_preview()

    @on(Input.Changed)
    def _on_dri_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "dri-length":
            return
        self._mark_dri_dirty(True)
        if self.query_one("#dri-manual-length", Checkbox).value:
            self._refresh_dri_preview()

    @on(TextArea.Changed)
    def _on_app0_textarea_changed(self, event: TextArea.Changed) -> None:
        if not event.text_area.id or not event.text_area.id.startswith("app0-"):
            return
        self._update_app0_length_field()
        self._refresh_app0_preview()
        self._mark_app0_dirty(True)

    @on(TextArea.Changed)
    def _on_sof0_textarea_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id not in {"sof0-struct-edit", "sof0-raw-hex"}:
            return
        if not self.query_one("#sof0-manual-length", Checkbox).value:
            try:
                payload = self._build_sof0_payload()
            except Exception:
                self._mark_sof0_dirty(True)
            else:
                self.query_one("#sof0-length", Input).value = f"{len(payload) + 2:04X}"
        self._refresh_sof0_preview()

    @on(TextArea.Changed)
    def _on_dri_textarea_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id not in {"dri-struct-edit", "dri-raw-hex"}:
            return
        if not self.query_one("#dri-manual-length", Checkbox).value:
            try:
                payload = self._build_dri_payload()
            except Exception:
                self._mark_dri_dirty(True)
            else:
                self.query_one("#dri-length", Input).value = f"{len(payload) + 2:04X}"
        self._refresh_dri_preview()

    @on(Button.Pressed, "#sof0-save")
    def _on_sof0_save(self) -> None:
        err = self.query_one("#sof0-edit-error", Static)
        err.update("")
        try:
            input_path, payload, length_field = self._sof0_save_inputs()
        except Exception as e:
            err.update(f"Error: {e}")
            return
        out_path = self._sof0_write_file(input_path, payload, length_field)
        self._sof0_save_log(out_path, payload, length_field)
        self._mark_sof0_dirty(False)

    @on(Button.Pressed, "#dri-save")
    def _on_dri_save(self) -> None:
        err = self.query_one("#dri-edit-error", Static)
        err.update("")
        try:
            input_path, payload, length_field = self._dri_save_inputs()
        except Exception as e:
            err.update(f"Error: {e}")
            return
        out_path = self._dri_write_file(input_path, payload, length_field)
        self._dri_save_log(out_path, payload, length_field)
        self._mark_dri_dirty(False)

    @on(Select.Changed)
    def _on_app0_select_changed(self, event: Select.Changed) -> None:
        if not event.select.id or not event.select.id.startswith("app0-"):
            return
        self._update_app0_length_field()
        self._refresh_app0_preview()
        self._mark_app0_dirty(True)

    @on(Checkbox.Changed)
    def _on_dqt_checkbox_changed(self, event: Checkbox.Changed) -> None:
        key = self._dqt_key_from_id(event.checkbox.id, "-advanced-mode")
        if key:
            self._apply_dqt_mode_visibility(key)
            try:
                self._sync_dqt_editor_for_mode(key)
            except Exception:
                pass
            self._refresh_dqt_preview(key)
            return
        key = self._dqt_key_from_id(event.checkbox.id, "-manual-length")
        if not key:
            return
        self._apply_dqt_mode_visibility(key)
        if not event.checkbox.value and key in self.dqt_preview_payload:
            payload = self.dqt_preview_payload[key]
            self.query_one(f"#{key}-length", Input).value = f"{len(payload) + 2:04X}"
        self._refresh_dqt_preview(key)

    @on(Input.Changed)
    def _on_dqt_input_changed(self, event: Input.Changed) -> None:
        key = self._dqt_key_from_id(event.input.id, "-length")
        if not key:
            return
        self._set_dqt_dirty(key, True)
        if self.query_one(f"#{key}-manual-length", Checkbox).value:
            self._refresh_dqt_preview(key)

    @on(TextArea.Changed)
    def _on_dqt_textarea_changed(self, event: TextArea.Changed) -> None:
        key = self._dqt_key_from_id(event.text_area.id, "-grid-edit")
        if not key:
            key = self._dqt_key_from_id(event.text_area.id, "-raw-hex")
        if not key:
            return
        if not self.query_one(f"#{key}-manual-length", Checkbox).value:
            try:
                payload = self._build_dqt_payload(key)
            except Exception:
                self._set_dqt_dirty(key, True)
            else:
                self.query_one(f"#{key}-length", Input).value = f"{len(payload) + 2:04X}"
        self._refresh_dqt_preview(key)

    @on(Button.Pressed)
    def _on_dqt_save(self, event: Button.Pressed) -> None:
        key = self._dqt_key_from_id(event.button.id, "-save")
        if not key:
            return
        err = self.query_one(f"#{key}-error", Static)
        err.update("")
        try:
            input_path, payload, length_field = self._dqt_save_inputs(key)
        except Exception as e:
            err.update(f"Error: {e}")
            return
        out_path = self._dqt_write_file(key, input_path, payload, length_field)
        self._dqt_save_log(key, out_path, payload, length_field)
        self._set_dqt_dirty(key, False)

    @on(Checkbox.Changed)
    def _on_dht_checkbox_changed(self, event: Checkbox.Changed) -> None:
        key = self._dht_key_from_id(event.checkbox.id, "-advanced-mode")
        if key:
            self._apply_dht_mode_visibility(key)
            try:
                self._sync_dht_editor_for_mode(key)
            except Exception:
                pass
            self._refresh_dht_preview(key)
            return
        key = self._dht_key_from_id(event.checkbox.id, "-manual-length")
        if not key:
            return
        self._apply_dht_mode_visibility(key)
        if not event.checkbox.value and key in self.dht_preview_payload:
            payload = self.dht_preview_payload[key]
            self.query_one(f"#{key}-length", Input).value = f"{len(payload) + 2:04X}"
        self._refresh_dht_preview(key)

    @on(Input.Changed)
    def _on_dht_input_changed(self, event: Input.Changed) -> None:
        key = self._dht_key_from_id(event.input.id, "-length")
        if not key:
            return
        self._set_dht_dirty(key, True)
        if self.query_one(f"#{key}-manual-length", Checkbox).value:
            self._refresh_dht_preview(key)

    @on(TextArea.Changed)
    def _on_dht_textarea_changed(self, event: TextArea.Changed) -> None:
        key = self._dht_key_from_id(event.text_area.id, "-table-edit")
        if not key:
            key = self._dht_key_from_id(event.text_area.id, "-raw-hex")
        if not key:
            return
        if not self.query_one(f"#{key}-manual-length", Checkbox).value:
            try:
                payload = self._build_dht_payload(key)
            except Exception:
                self._set_dht_dirty(key, True)
            else:
                self.query_one(f"#{key}-length", Input).value = f"{len(payload) + 2:04X}"
        self._refresh_dht_preview(key)

    @on(Button.Pressed)
    def _on_dht_save(self, event: Button.Pressed) -> None:
        key = self._dht_key_from_id(event.button.id, "-save")
        if not key:
            return
        err = self.query_one(f"#{key}-error", Static)
        err.update("")
        try:
            input_path, payload, length_field = self._dht_save_inputs(key)
        except Exception as e:
            err.update(f"Error: {e}")
            return
        out_path = self._dht_write_file(key, input_path, payload, length_field)
        self._dht_save_log(key, out_path, payload, length_field)
        self._set_dht_dirty(key, False)

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

    @on(Select.Changed)
    def _on_app2_select_changed(self, event: Select.Changed) -> None:
        key = self._app2_key_from_id(event.select.id, "-desc-preset")
        if key:
            val = event.select.value
            self.query_one(f"#{key}-desc-input", Input).value = val or ""
            self._set_app2_dirty(key, True)
            return
        key = self._app2_key_from_id(event.select.id, "-cprt-preset")
        if key:
            val = event.select.value
            self.query_one(f"#{key}-cprt-input", Input).value = val or ""
            self._set_app2_dirty(key, True)
            return

    @on(Input.Changed)
    def _on_app2_input_changed(self, event: Input.Changed) -> None:
        key = self._app2_key_from_id(event.input.id, "-desc-input")
        if key:
            self._refresh_app2_preview(key)
            return
        key = self._app2_key_from_id(event.input.id, "-cprt-input")
        if key:
            self._refresh_app2_preview(key)
            return
        key = self._app2_key_from_id(event.input.id, "-dmnd-input")
        if key:
            self._refresh_app2_preview(key)
            return
        key = self._app2_key_from_id(event.input.id, "-dmdd-input")
        if key:
            self._refresh_app2_preview(key)
            return
        for suffix in [
            "-wtpt-input",
            "-bkpt-input",
            "-rxyz-input",
            "-gxyz-input",
            "-bxyz-input",
            "-rtrc-input",
            "-gtrc-input",
            "-btrc-input",
        ]:
            key = self._app2_key_from_id(event.input.id, suffix)
            if key:
                self._refresh_app2_preview(key)
                return
            return

    @on(Button.Pressed)
    def _on_app2_save(self, event: Button.Pressed) -> None:
        key = self._app2_key_from_id(event.button.id, "-save")
        if not key:
            return
        err = self.query_one(f"#{key}-error", Static)
        err.update("")
        try:
            input_path, payload = self._app2_save_inputs(key)
        except Exception as e:
            err.update(f"Error: {e}")
            return
        out_path = self._app2_write_file(input_path, key, payload)
        self.query_one(f"#info-{key}-raw", RichLog).write(f"Saved edited file: {out_path}")
        self._set_app2_dirty(key, False)

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
        self._populate_info_tabs(input_path, data, segments, entropy_ranges)

    def _auto_load_info(self) -> None:
        try:
            input_path, data, segments, entropy_ranges = self._load_info_data()
        except Exception:
            return
        self._populate_info_tabs(input_path, data, segments, entropy_ranges)

    def _populate_info_tabs(self, input_path: str, data: bytes, segments, entropy_ranges) -> None:
        self.info_data = data
        self.info_segments = segments
        self.hex_page = 0

        general, segments_log, details_log, entropy_log = self._info_logs()
        self._clear_info_logs(general, segments_log, details_log, entropy_log)
        appn_targets = self._reset_appn_tabs(segments)
        dqt_targets = self._reset_dqt_tabs(segments)
        dht_targets = self._reset_dht_tabs(segments)
        self._write_general(general, input_path, data, segments, entropy_ranges)
        self._write_segments(segments_log, segments, entropy_ranges, data)
        self._write_details(details_log, segments, data)
        self._write_entropy(entropy_log, entropy_ranges)
        try:
            self._render_app0_segment(data, segments)
        except Exception:
            # APP0 pane not present.
            pass
        try:
            self._render_sof0_segment(data, segments)
        except Exception:
            pass
        try:
            self._render_dri_segment(data, segments)
        except Exception:
            pass
        self._render_appn_segments(data, appn_targets)
        self._render_dqt_segments(data, dqt_targets)
        self._render_dht_segments(data, dht_targets)
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
        first_pane_id = None

        self.app1_segment_info = {}
        self.app1_original_payload = {}
        self.app1_dirty = {}
        counts: dict[str, int] = {}
        targets: list[Tuple[str, object]] = []
        has_app0 = any(seg.name == "APP0" for seg in segments)
        if has_app0:
            pane = TabPane("APP0", self._build_app0_pane())
            appn_tabs.add_pane(pane)
            first_pane_id = pane.id
            self._apply_app0_mode_visibility()
        for seg in segments:
            if not seg.name.startswith("APP"):
                continue
            counts[seg.name] = counts.get(seg.name, 0) + 1
            if seg.name == "APP0" and counts[seg.name] == 1:
                continue
            label = seg.name if counts[seg.name] == 1 else f"{seg.name} #{counts[seg.name]}"
            if seg.name == "APP1":
                key = f"app1-{seg.offset:08X}"
                pane = TabPane(label, self._build_app1_pane(key, label))
                appn_tabs.add_pane(pane)
                if first_pane_id is None:
                    first_pane_id = pane.id
                self._init_app1_tabs(key)
                targets.append((key, seg))
            elif seg.name == "APP2":
                key = f"app2-{seg.offset:08X}"
                pane = TabPane(label, self._build_app2_pane(key, label))
                appn_tabs.add_pane(pane)
                if first_pane_id is None:
                    first_pane_id = pane.id
                self._init_app2_tabs(key)
                targets.append((key, seg))
            else:
                log_id = f"info-appn-{seg.offset}"
                pane = TabPane(label, self._build_appn_readonly_pane(label, log_id))
                appn_tabs.add_pane(pane)
                if first_pane_id is None:
                    first_pane_id = pane.id
                targets.append((log_id, seg))
        if first_pane_id is None:
            pane = TabPane("APPn", RichLog(id="info-appn-empty", highlight=True))
            appn_tabs.add_pane(pane)
            first_pane_id = pane.id
            self.query_one("#info-appn-empty", RichLog).write("No APPn segments found.")
        if first_pane_id is not None:
            appn_tabs.show_tab(first_pane_id)
        return targets

    def _render_appn_segments(self, data: bytes, targets: list[Tuple[str, object]]) -> None:
        for key, seg in targets:
            if key.startswith("app1-"):
                self._render_app1_segment(data, seg, key)
                continue
            if key.startswith("app2-"):
                self._render_app2_segment(data, seg, key)
                continue
            log = self.query_one(f"#{key}", RichLog)
            log.clear()
            self._render_appn_segment(data, seg, log)

    def _reset_dqt_tabs(self, segments) -> list[Tuple[str, object]]:
        dqt_tabs = self.query_one("#dqt-tabs", TabbedContent)
        dqt_tabs.clear_panes()
        targets: list[Tuple[str, object]] = []
        dqt_segments = [s for s in segments if s.name == "DQT"]
        if not dqt_segments:
            pane = TabPane("DQT", RichLog(id="info-dqt-empty", highlight=True))
            dqt_tabs.add_pane(pane)
            self.query_one("#info-dqt-empty", RichLog).write("No DQT segments found.")
            dqt_tabs.show_tab(pane.id)
            return targets
        first_pane_id = None
        for idx, seg in enumerate(dqt_segments, start=1):
            key = f"dqt-{seg.offset:08X}"
            label = f"DQT #{idx}"
            pane = TabPane(label, self._build_dqt_segment_pane(key, label))
            dqt_tabs.add_pane(pane)
            self._init_dqt_detail_tabs(key)
            if first_pane_id is None:
                first_pane_id = pane.id
            targets.append((key, seg))
        if first_pane_id is not None:
            dqt_tabs.show_tab(first_pane_id)
        return targets

    def _reset_dht_tabs(self, segments) -> list[Tuple[str, object]]:
        dht_tabs = self.query_one("#dht-tabs", TabbedContent)
        dht_tabs.clear_panes()
        targets: list[Tuple[str, object]] = []
        dht_segments = [s for s in segments if s.name == "DHT"]
        if not dht_segments:
            pane = TabPane("DHT", RichLog(id="info-dht-empty", highlight=True))
            dht_tabs.add_pane(pane)
            self.query_one("#info-dht-empty", RichLog).write("No DHT segments found.")
            dht_tabs.show_tab(pane.id)
            return targets
        first_pane_id = None
        for idx, seg in enumerate(dht_segments, start=1):
            key = f"dht-{seg.offset:08X}"
            label = f"DHT #{idx}"
            pane = TabPane(label, self._build_dht_segment_pane(key, label))
            dht_tabs.add_pane(pane)
            self._init_dht_detail_tabs(key)
            if first_pane_id is None:
                first_pane_id = pane.id
            targets.append((key, seg))
        if first_pane_id is not None:
            dht_tabs.show_tab(first_pane_id)
        return targets

    def _render_dqt_segments(self, data: bytes, targets: list[Tuple[str, object]]) -> None:
        for key, seg in targets:
            self._render_dqt_segment(data, seg, key)

    def _render_dht_segments(self, data: bytes, targets: list[Tuple[str, object]]) -> None:
        for key, seg in targets:
            self._render_dht_segment(data, seg, key)

    def _render_dht_segment(self, data: bytes, seg, key: str) -> None:
        left_log = self.query_one(f"#info-{key}-left", RichLog)
        if seg.payload_offset is None or seg.payload_length is None:
            left_log.clear()
            left_log.write("DHT has no payload.")
            return
        payload = data[seg.payload_offset:seg.payload_offset + seg.payload_length]
        self.dht_segment_info[key] = (seg.offset, seg.total_length, seg.length_field or 0, seg.payload_offset)
        self.dht_original_payload[key] = payload
        self.dht_preview_payload[key] = payload
        self._set_dht_editor_values(key, payload, seg.length_field or 0)
        self._apply_dht_mode_visibility(key)
        self._set_dht_dirty(key, False)
        self._render_dht_views(key, payload, seg.offset, seg.length_field or 0)

    def _render_dht_views(self, key: str, payload: bytes, offset: int, length_field: int) -> None:
        left_log = self.query_one(f"#info-{key}-left", RichLog)
        tables_log = self.query_one(f"#info-{key}-tables", RichLog)
        counts_log = self.query_one(f"#info-{key}-counts", RichLog)
        symbols_log = self.query_one(f"#info-{key}-symbols", RichLog)
        usage_log = self.query_one(f"#info-{key}-usage", RichLog)
        codes_log = self.query_one(f"#info-{key}-codes", RichLog)
        for log in (left_log, tables_log, counts_log, symbols_log, usage_log, codes_log):
            log.clear()
        # Keep one decode pass for summaries and one for the full structured views.
        summaries = decode_dht(payload)
        tables = decode_dht_tables(payload)
        self._write_dht_left_panel(left_log, offset, length_field, payload, summaries, tables)
        self._write_dht_tables_tab(tables_log, tables)
        self._write_dht_counts_tab(counts_log, tables)
        self._write_dht_symbols_tab(symbols_log, tables)
        self._write_dht_usage_tab(usage_log, tables)
        self._write_dht_codes_tab(codes_log, tables)

    def _write_dht_left_panel(self, log: RichLog, offset: int, length_field: int, payload: bytes, summaries, tables) -> None:
        log.write(f"DHT at 0x{offset:08X} length=0x{length_field:04X} payload={len(payload)}")
        log.write(f"Tables in segment: {len(tables)}")
        log.write("JPEG stores canonical Huffman tables as 16 code-length counts followed by symbols.")
        log.write("Legend:")
        for label, style in [
            ("Marker", "bold yellow"),
            ("Length", "bold cyan"),
            ("Table header (Tc/Th)", "bright_blue"),
            ("Code-length counts", "magenta"),
            ("Symbol values", "green"),
        ]:
            log.write(Text("  " + label, style=style))
        for idx, table in enumerate(summaries, start=1):
            log.write(f"Table {idx}: {', '.join(f'{k}={v}' for k, v in table.items())}")
        segment_bytes = b"\xFF\xC4" + length_field.to_bytes(2, "big") + payload
        for line in self._hex_dump(segment_bytes, 0, len(segment_bytes), self._dht_ranges(payload)):
            log.write(line)

    def _dht_ranges(self, payload: bytes) -> list[Tuple[int, int, str]]:
        ranges = [(0, 2, "bold yellow"), (2, 4, "bold cyan")]
        payload_idx = 0
        cursor = 4
        colors = [("magenta", "green"), ("bright_magenta", "bright_green")]
        table_idx = 0
        while payload_idx + 17 <= len(payload):
            header_start = cursor
            ranges.append((header_start, header_start + 1, "bright_blue"))
            payload_idx += 1
            cursor += 1
            counts = list(payload[payload_idx:payload_idx + 16])
            ranges.append((cursor, cursor + 16, colors[table_idx % 2][0]))
            payload_idx += 16
            cursor += 16
            total = sum(counts)
            sym_end = min(cursor + total, 4 + len(payload))
            if total > 0:
                ranges.append((cursor, sym_end, colors[table_idx % 2][1]))
            payload_idx += total
            cursor = sym_end
            table_idx += 1
        return ranges

    def _write_dht_tables_tab(self, log: RichLog, tables: list[dict[str, object]]) -> None:
        if not tables:
            log.write("No decodable DHT tables found.")
            return
        log.write("Canonical Huffman table summaries.")
        for idx, table in enumerate(tables, start=1):
            log.write("")
            log.write(f"Table {idx}: class={table['class']} id={table['id']}")
            log.write(f"  symbols={len(table['symbols'])} max_code_length={self._dht_max_length(table)}")
            log.write(f"  total_count_sum={sum(table['counts'])}")

    def _write_dht_counts_tab(self, log: RichLog, tables: list[dict[str, object]]) -> None:
        if not tables:
            log.write("No decodable DHT tables found.")
            return
        log.write("Counts are the number of codes for bit lengths 1..16.")
        for idx, table in enumerate(tables, start=1):
            counts = list(table["counts"])
            log.write("")
            log.write(f"Table {idx}: class={table['class']} id={table['id']}")
            for start in range(0, 16, 8):
                chunk = counts[start:start + 8]
                line = " ".join(f"L{start + i + 1:02d}:{count:3d}" for i, count in enumerate(chunk))
                log.write(line)

    def _write_dht_symbols_tab(self, log: RichLog, tables: list[dict[str, object]]) -> None:
        if not tables:
            log.write("No decodable DHT tables found.")
            return
        log.write("Symbols are listed in JPEG payload order after the 16 count bytes.")
        for idx, table in enumerate(tables, start=1):
            symbols = list(table["symbols"])
            log.write("")
            log.write(f"Table {idx}: class={table['class']} id={table['id']}")
            if not symbols:
                log.write("  No symbols.")
                continue
            for start in range(0, len(symbols), 8):
                chunk = symbols[start:start + 8]
                line = " ".join(f"{start + i:02d}:0x{symbol:02X}" for i, symbol in enumerate(chunk))
                log.write(line)

    def _write_dht_usage_tab(self, log: RichLog, tables: list[dict[str, object]]) -> None:
        if not tables:
            log.write("No decodable DHT tables found.")
            return
        scans = self._scan_huffman_usage()
        if not scans:
            log.write("No SOS component mapping found, so Huffman-table usage cannot be inferred.")
            return
        log.write("Usage is inferred from SOS component selectors (DC/AC table ids per scan component).")
        for table in tables:
            table_class = str(table["class"])
            table_id = int(table["id"])
            log.write("")
            log.write(f"Table class={table_class} id={table_id}")
            hits = []
            for scan_idx, scan in enumerate(scans, start=1):
                for comp in scan:
                    wanted = comp["dc_table_id"] if table_class == "DC" else comp["ac_table_id"]
                    if wanted != table_id:
                        continue
                    hits.append((scan_idx, comp))
            if not hits:
                log.write("  No scan components reference this table.")
                continue
            for scan_idx, comp in hits:
                log.write(f"  Scan {scan_idx}: component {comp['id']} ({self._component_name(comp['id'])})")

    def _write_dht_codes_tab(self, log: RichLog, tables: list[dict[str, object]]) -> None:
        if not tables:
            log.write("No decodable DHT tables found.")
            return
        log.write("Canonical codes reconstructed from the JPEG count bytes.")
        for idx, table in enumerate(tables, start=1):
            codes = list(table["codes"])
            log.write("")
            log.write(f"Table {idx}: class={table['class']} id={table['id']}")
            if not codes:
                log.write("  No codes.")
                continue
            for start in range(0, len(codes), 8):
                chunk = codes[start:start + 8]
                parts = [
                    f"{entry['code']:0{entry['length']}b}:{entry['symbol']:02X}"
                    for entry in chunk
                ]
                log.write(" ".join(parts))

    def _dht_max_length(self, table: dict[str, object]) -> int:
        counts = list(table["counts"])
        for idx in range(15, -1, -1):
            if counts[idx]:
                return idx + 1
        return 0

    def _scan_huffman_usage(self) -> list[list[dict[str, int]]]:
        if not self.info_segments or not self.info_data:
            return []
        scans = []
        for seg in self.info_segments:
            if seg.name != "SOS" or seg.payload_offset is None or seg.payload_length is None:
                continue
            payload = self.info_data[seg.payload_offset:seg.payload_offset + seg.payload_length]
            components = decode_sos_components(payload)
            if components:
                scans.append(components)
        return scans

    def _render_dqt_segment(self, data: bytes, seg, key: str) -> None:
        left_log = self.query_one(f"#info-{key}-left", RichLog)
        if seg.payload_offset is None or seg.payload_length is None:
            left_log.clear()
            left_log.write("DQT has no payload.")
            return
        payload = data[seg.payload_offset:seg.payload_offset + seg.payload_length]
        self.dqt_segment_info[key] = (seg.offset, seg.total_length, seg.length_field or 0, seg.payload_offset)
        self.dqt_original_payload[key] = payload
        self.dqt_preview_payload[key] = payload
        self._set_dqt_editor_values(key, payload, seg.length_field or 0)
        self._apply_dqt_mode_visibility(key)
        self._set_dqt_dirty(key, False)
        self._render_dqt_views(key, payload, seg.offset, seg.length_field or 0)

    def _render_dqt_views(self, key: str, payload: bytes, offset: int, length_field: int) -> None:
        left_log = self.query_one(f"#info-{key}-left", RichLog)
        grid_log = self.query_one(f"#info-{key}-grid", RichLog)
        zigzag_log = self.query_one(f"#info-{key}-zigzag", RichLog)
        stats_log = self.query_one(f"#info-{key}-stats", RichLog)
        usage_log = self.query_one(f"#info-{key}-usage", RichLog)
        heatmap_log = self.query_one(f"#info-{key}-heatmap", RichLog)
        for log in (left_log, grid_log, zigzag_log, stats_log, usage_log, heatmap_log):
            log.clear()
        # The left panel shows the segment as stored; the right panels show derived views.
        tables = decode_dqt(payload)
        full_tables = decode_dqt_tables(payload)
        self._write_dqt_left_panel(left_log, offset, length_field, payload, tables, full_tables)
        self._write_dqt_grid_tab(grid_log, full_tables)
        self._write_dqt_zigzag_tab(zigzag_log, full_tables)
        self._write_dqt_stats_tab(stats_log, full_tables)
        self._write_dqt_usage_tab(usage_log, full_tables)
        self._write_dqt_heatmap_tab(heatmap_log, full_tables)

    def _write_dqt_left_panel(self, log: RichLog, offset: int, length_field: int, payload: bytes, tables, full_tables) -> None:
        log.write(f"DQT at 0x{offset:08X} length=0x{length_field:04X} payload={len(payload)}")
        log.write(f"Tables in segment: {len(full_tables)}")
        log.write("JPEG stores DQT values in zigzag order; analysis views may remap them into natural 8x8 order.")
        log.write("Legend:")
        for label, style in [
            ("Marker", "bold yellow"),
            ("Length", "bold cyan"),
            ("Table header (Pq/Tq)", "bright_blue"),
            ("Table payload", "green"),
        ]:
            log.write(Text("  " + label, style=style))
        for idx, table in enumerate(tables, start=1):
            log.write(f"Table {idx}: {', '.join(f'{k}={v}' for k, v in table.items())}")
        segment_bytes = b"\xFF\xDB" + length_field.to_bytes(2, "big") + payload
        ranges = self._dqt_ranges(payload, log)
        for line in self._hex_dump(segment_bytes, 0, len(segment_bytes), ranges):
            log.write(line)

    def _dqt_ranges(self, payload: bytes, log: RichLog) -> list[Tuple[int, int, str]]:
        ranges = [(0, 2, "bold yellow"), (2, 4, "bold cyan")]
        cursor = 4
        payload_idx = 0
        colors = ["green", "bright_green"]
        while payload_idx < len(payload):
            table_start = cursor
            if payload_idx >= len(payload):
                break
            pq_tq = payload[payload_idx]
            payload_idx += 1
            cursor += 1
            precision = 16 if (pq_tq >> 4) else 8
            size = 128 if precision == 16 else 64
            table_end = min(cursor + size, 4 + len(payload))
            ranges.append((table_start, table_start + 1, "bright_blue"))
            if table_start + 1 < table_end:
                ranges.append((table_start + 1, table_end, colors[(len(ranges) // 2) % len(colors)]))
            payload_idx += size
            cursor = table_end
        return ranges

    def _write_dqt_grid_tab(self, log: RichLog, tables: list[dict[str, object]]) -> None:
        if not tables:
            log.write("No decodable DQT tables found.")
            return
        log.write("Natural 8x8 view. Top-left is DC / lowest spatial frequency.")
        log.write("Rows and columns increase toward higher spatial frequencies.")
        for idx, table in enumerate(tables, start=1):
            table_id = int(table.get("id", 0))
            precision = int(table.get("precision_bits", 8))
            grid = dqt_values_to_natural_grid(list(table.get("values", [])))
            log.write("")
            log.write(f"Table {idx} (id={table_id}, precision={precision}-bit)")
            for line in self._format_dqt_grid(grid, precision):
                log.write(line)

    def _write_dqt_zigzag_tab(self, log: RichLog, tables: list[dict[str, object]]) -> None:
        if not tables:
            log.write("No decodable DQT tables found.")
            return
        log.write("Raw JPEG serialization order (zigzag). Index 0 is DC, later indices move toward higher frequencies.")
        for idx, table in enumerate(tables, start=1):
            values = list(table.get("values", []))
            precision = int(table.get("precision_bits", 8))
            width = 4 if precision <= 8 else 6
            log.write("")
            log.write(f"Table {idx} zigzag order:")
            for start in range(0, len(values), 8):
                chunk = values[start:start + 8]
                text = " ".join(f"{start + i:02d}:{value:{width}d}" for i, value in enumerate(chunk))
                log.write(text)

    def _write_dqt_stats_tab(self, log: RichLog, tables: list[dict[str, object]]) -> None:
        if not tables:
            log.write("No decodable DQT tables found.")
            return
        log.write("Stats use raw zigzag values. Low-frequency = first 10 entries; high-frequency = last 10 entries.")
        for idx, table in enumerate(tables, start=1):
            values = list(table.get("values", []))
            if not values:
                continue
            low_band = values[:10]
            high_band = values[-10:]
            mean = sum(values) / len(values)
            median = sorted(values)[len(values) // 2]
            log.write("")
            log.write(f"Table {idx} (id={table.get('id')}, precision={table.get('precision_bits')}-bit)")
            log.write(f"  min={min(values)} max={max(values)} mean={mean:.2f} median={median}")
            log.write(f"  DC={values[0]} low-band avg={sum(low_band) / len(low_band):.2f}")
            log.write(f"  high-band avg={sum(high_band) / len(high_band):.2f}")
            log.write(f"  monotonic trend: {'rising' if values[-1] >= values[0] else 'mixed/non-rising'}")

    def _write_dqt_usage_tab(self, log: RichLog, tables: list[dict[str, object]]) -> None:
        if not tables:
            log.write("No decodable DQT tables found.")
            return
        components = self._frame_components()
        if not components:
            log.write("No SOF component mapping found, so table usage cannot be inferred.")
            return
        log.write("Usage is inferred from the frame header's component -> quantization table mapping.")
        for table in tables:
            table_id = int(table.get("id", 0))
            users = [comp for comp in components if comp["quant_table_id"] == table_id]
            log.write("")
            log.write(f"Table id={table_id}")
            if not users:
                log.write("  No frame components reference this table.")
                continue
            for comp in users:
                name = self._component_name(comp["id"])
                sampling = f"{comp['h_sampling']}x{comp['v_sampling']}"
                log.write(f"  Component {comp['id']} ({name}) sampling={sampling}")

    def _write_dqt_heatmap_tab(self, log: RichLog, tables: list[dict[str, object]]) -> None:
        if not tables:
            log.write("No decodable DQT tables found.")
            return
        log.write("Heatmap view of the natural 8x8 grid. Hotter cells indicate larger quantization values.")
        for idx, table in enumerate(tables, start=1):
            grid = dqt_values_to_natural_grid(list(table.get("values", [])))
            flat = [value for row in grid for value in row]
            vmin, vmax = min(flat), max(flat)
            log.write("")
            log.write(f"Table {idx} heatmap (id={table.get('id')}):")
            log.write(f"Range: {vmin}..{vmax}")
            for row_idx, row in enumerate(grid):
                line = Text(f"v{row_idx} ", style="bold white")
                for col_idx, value in enumerate(row):
                    # The TUI has no true canvas here, so the heatmap is encoded in cell background color.
                    style = self._heatmap_style(value, vmin, vmax)
                    label = f"{value:4d}"
                    if row_idx == 0 and col_idx == 0:
                        label = f"[{value:02d}]"
                    line.append(label + " ", style=style)
                log.write(line)

    def _format_dqt_grid(self, grid: list[list[int]], precision: int) -> list[Text]:
        if precision <= 8:
            fmt = "{:4d}"
        else:
            fmt = "{:6d}"
        lines: list[Text] = []
        header = "      " + " ".join(f"h{idx:>3}" for idx in range(8))
        lines.append(Text(header, style="bold white"))
        for row_idx, row in enumerate(grid):
            line = Text(f"v{row_idx:>2} ", style="bold white")
            for col_idx, value in enumerate(row):
                cell = fmt.format(value)
                style = "bold yellow" if row_idx == 0 and col_idx == 0 else "white"
                line.append(cell + " ", style=style)
            lines.append(line)
        return lines

    def _frame_components(self) -> list[dict[str, int]]:
        if not self.info_segments or not self.info_data:
            return []
        for seg in self.info_segments:
            if not seg.name.startswith("SOF") or seg.payload_offset is None or seg.payload_length is None:
                continue
            payload = self.info_data[seg.payload_offset:seg.payload_offset + seg.payload_length]
            components = decode_sof_components(payload)
            if components:
                return components
        return []

    def _component_name(self, comp_id: int) -> str:
        names = {1: "Y / luma", 2: "Cb", 3: "Cr", 4: "I", 5: "Q"}
        return names.get(comp_id, "unknown / custom")

    def _heatmap_style(self, value: int, vmin: int, vmax: int) -> str:
        if vmax <= vmin:
            r, g, b = 96, 96, 96
        else:
            ratio = (value - vmin) / (vmax - vmin)
            r = int(40 + 190 * ratio)
            g = int(60 + 110 * (1.0 - abs(ratio - 0.5) * 2.0))
            b = int(180 - 140 * ratio)
        fg = "black" if (r + g + b) > 380 else "white"
        return f"{fg} on rgb({r},{g},{b})"

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

    def _init_app2_tabs(self, key: str) -> None:
        tabs = self.query_one(f"#{key}-tabs", TabbedContent)
        tabs.clear_panes()
        tabs.add_pane(TabPane("Raw", RichLog(id=f"info-{key}-raw", highlight=True)))
        tabs.add_pane(TabPane("Hex", RichLog(id=f"info-{key}-hex", highlight=True)))
        tabs.add_pane(TabPane("Table", RichLog(id=f"info-{key}-table", highlight=True)))
        right = self.query_one(f"#{key}-right-tabs", TabbedContent)
        right.clear_panes()
        right.add_pane(TabPane("Header", RichLog(id=f"{key}-header", highlight=True)))
        right.add_pane(TabPane("Tags", RichLog(id=f"{key}-tags", highlight=True)))
        right.add_pane(TabPane("Tag Table", RichLog(id=f"{key}-tag-table", highlight=True)))
        right.add_pane(
            TabPane(
                "Edit",
                Vertical(
                    Label("Profile description", classes="field"),
                    Select(
                        [
                            ("", ""),
                            ("sRGB IEC61966-2.1", "sRGB IEC61966-2.1"),
                            ("Adobe RGB (1998)", "Adobe RGB (1998)"),
                            ("Display P3", "Display P3"),
                            ("ProPhoto RGB", "ProPhoto RGB"),
                        ],
                        value="",
                        id=f"{key}-desc-preset",
                    ),
                    Input(value="", id=f"{key}-desc-input"),
                    Label("Copyright", classes="field"),
                    Select(
                        [
                            ("", ""),
                            ("Copyright (c)", "Copyright (c)"),
                            ("Copyright (c) Adobe Systems", "Copyright (c) Adobe Systems"),
                        ],
                        value="",
                        id=f"{key}-cprt-preset",
                    ),
                    Input(value="", id=f"{key}-cprt-input"),
                    Label("Device manufacturer", classes="field"),
                    Input(value="", id=f"{key}-dmnd-input"),
                    Label("Device model", classes="field"),
                    Input(value="", id=f"{key}-dmdd-input"),
                    Label("White point (XYZ)", classes="field"),
                    Input(value="", id=f"{key}-wtpt-input"),
                    Label("Black point (XYZ)", classes="field"),
                    Input(value="", id=f"{key}-bkpt-input"),
                    Label("Red/Green/Blue colorants (XYZ)", classes="field"),
                    Input(value="", id=f"{key}-rxyz-input"),
                    Input(value="", id=f"{key}-gxyz-input"),
                    Input(value="", id=f"{key}-bxyz-input"),
                    Label("TRC gamma (r,g,b)", classes="field"),
                    Input(value="", id=f"{key}-rtrc-input"),
                    Input(value="", id=f"{key}-gtrc-input"),
                    Input(value="", id=f"{key}-btrc-input"),
                    Button("Save ICC edited file", id=f"{key}-save", variant="success", disabled=True),
                    Static("", id=f"{key}-error"),
                ),
            )
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

    def _render_app2_segment(self, data: bytes, seg, key: str) -> None:
        log_hex = self.query_one(f"#info-{key}-hex", RichLog)
        log_raw = self.query_one(f"#info-{key}-raw", RichLog)
        log_table = self.query_one(f"#info-{key}-table", RichLog)
        log_header = self.query_one(f"#{key}-header", RichLog)
        log_tags = self.query_one(f"#{key}-tags", RichLog)
        log_table2 = self.query_one(f"#{key}-tag-table", RichLog)
        err = self.query_one(f"#{key}-error", Static)
        desc_input = self.query_one(f"#{key}-desc-input", Input)
        cprt_input = self.query_one(f"#{key}-cprt-input", Input)
        log_hex.clear()
        log_raw.clear()
        log_table.clear()
        log_header.clear()
        log_tags.clear()
        log_table2.clear()
        err.update("")
        if seg.payload_offset is None or seg.payload_length is None:
            log_hex.write("APP2 has no payload.")
            return
        payload = data[seg.payload_offset:seg.payload_offset + seg.payload_length]
        self.app2_segment_info[key] = (seg.offset, seg.total_length, seg.length_field or 0, seg.payload_offset)
        self.app2_original_payload[key] = payload
        self.app2_preview_payload[key] = payload
        icc = self._parse_icc_profile(payload, seg.payload_offset)
        if icc.get("error"):
            log_hex.write(f"ICC decode error: {icc['error']}")
            self._render_app2_raw_hex(log_raw, data, seg)
            return
        self._write_icc_header(log_header, icc)
        self._write_icc_tags(log_tags, icc)
        self._write_icc_table(log_table, icc)
        self._write_icc_tag_table(log_table2, icc, payload)
        ranges = self._icc_hex_ranges(seg, icc)
        self._write_icc_hex_legend(log_hex)
        self._render_icc_hex_sections(log_hex, data, seg, icc, ranges)
        self._render_app2_raw_hex(log_raw, data, seg)
        tag_map = self._icc_tag_data_map(icc, payload)
        desc_text, desc_type = self._decode_icc_text_tag(tag_map.get("desc"))
        cprt_text, cprt_type = self._decode_icc_text_tag(tag_map.get("cprt"))
        desc_input.value = desc_text
        cprt_input.value = cprt_text
        self.query_one(f"#{key}-dmnd-input", Input).value = self._decode_icc_ascii(tag_map.get("dmnd"))
        self.query_one(f"#{key}-dmdd-input", Input).value = self._decode_icc_ascii(tag_map.get("dmdd"))
        self.query_one(f"#{key}-wtpt-input", Input).value = self._decode_icc_xyz(tag_map.get("wtpt"))
        self.query_one(f"#{key}-bkpt-input", Input).value = self._decode_icc_xyz(tag_map.get("bkpt"))
        self.query_one(f"#{key}-rxyz-input", Input).value = self._decode_icc_xyz(tag_map.get("rXYZ"))
        self.query_one(f"#{key}-gxyz-input", Input).value = self._decode_icc_xyz(tag_map.get("gXYZ"))
        self.query_one(f"#{key}-bxyz-input", Input).value = self._decode_icc_xyz(tag_map.get("bXYZ"))
        self.query_one(f"#{key}-rtrc-input", Input).value = self._decode_icc_gamma(tag_map.get("rTRC"))
        self.query_one(f"#{key}-gtrc-input", Input).value = self._decode_icc_gamma(tag_map.get("gTRC"))
        self.query_one(f"#{key}-btrc-input", Input).value = self._decode_icc_gamma(tag_map.get("bTRC"))
        self.app2_tag_types[key] = {"desc": desc_type, "cprt": cprt_type}
        self._set_app2_dirty(key, False)

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

    def _render_app2_raw_hex(self, log: RichLog, data: bytes, seg) -> None:
        for line in self._hex_dump(data, seg.offset, seg.total_length, []):
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

    def _parse_icc_profile(self, payload: bytes, payload_offset: int) -> dict:
        if not payload.startswith(b"ICC_PROFILE\x00"):
            return {"error": "missing ICC_PROFILE header"}
        if len(payload) < 14:
            return {"error": "truncated ICC header"}
        seq = payload[12]
        total = payload[13]
        icc = payload[14:]
        icc_start = payload_offset + 14
        if seq != 1 or total != 1:
            return {"error": f"multi-part ICC not supported (seq {seq}/{total})"}
        if len(icc) < 128:
            return {"error": "truncated ICC profile"}
        header = self._parse_icc_header(icc)
        tags = self._parse_icc_tags(icc)
        return {
            "error": None,
            "seq": seq,
            "total": total,
            "icc_start": icc_start,
            "icc_len": len(icc),
            "tag_count": len(tags),
            "header": header,
            "tags": tags,
        }

    def _parse_icc_header(self, icc: bytes) -> dict:
        return {
            "size": self._icc_u32(icc[0:4]),
            "cmm": icc[4:8].decode(errors="replace"),
            "version": self._icc_u32(icc[8:12]),
            "device_class": icc[12:16].decode(errors="replace"),
            "color_space": icc[16:20].decode(errors="replace"),
            "pcs": icc[20:24].decode(errors="replace"),
            "date": self._icc_date(icc[24:36]),
            "magic": icc[36:40].decode(errors="replace"),
        }

    def _parse_icc_tags(self, icc: bytes) -> list[dict]:
        if len(icc) < 132:
            return []
        count = self._icc_u32(icc[128:132])
        tags = []
        off = 132
        for _ in range(count):
            if off + 12 > len(icc):
                break
            sig = icc[off:off + 4].decode(errors="replace")
            tag_off = self._icc_u32(icc[off + 4:off + 8])
            size = self._icc_u32(icc[off + 8:off + 12])
            tags.append({"sig": sig, "offset": tag_off, "size": size})
            off += 12
        return tags

    def _icc_tag_data_map(self, icc: dict, payload: bytes) -> dict[str, bytes]:
        icc_start = icc["icc_start"]
        icc_bytes = payload[14:]
        out: dict[str, bytes] = {}
        for t in icc["tags"]:
            start = t["offset"]
            end = start + t["size"]
            if end <= len(icc_bytes):
                out[t["sig"]] = icc_bytes[start:end]
        return out

    def _decode_icc_text_tag(self, data: Optional[bytes]) -> tuple[str, str]:
        if not data or len(data) < 8:
            return "", ""
        tag_type = data[0:4].decode(errors="replace")
        if tag_type == "text":
            return data[8:].split(b"\x00", 1)[0].decode(errors="replace"), "text"
        if tag_type == "desc":
            if len(data) < 12:
                return "", "desc"
            count = self._icc_u32(data[8:12])
            text = data[12:12 + max(0, count - 1)]
            return text.decode(errors="replace"), "desc"
        if tag_type == "mluc":
            if len(data) < 16:
                return "", "mluc"
            count = self._icc_u32(data[8:12])
            rec_size = self._icc_u32(data[12:16])
            if count < 1 or len(data) < 16 + rec_size:
                return "", "mluc"
            rec = data[16:16 + rec_size]
            length = self._icc_u32(rec[4:8])
            offset = self._icc_u32(rec[8:12])
            start = offset
            end = start + length
            if end <= len(data):
                return data[start:end].decode("utf-16be", errors="replace"), "mluc"
            return "", "mluc"
        return "", tag_type

    def _decode_icc_ascii(self, data: Optional[bytes]) -> str:
        if not data or len(data) < 8:
            return ""
        tag_type = data[0:4].decode(errors="replace")
        if tag_type == "text":
            return data[8:].split(b"\x00", 1)[0].decode(errors="replace")
        return ""

    def _decode_icc_xyz(self, data: Optional[bytes]) -> str:
        if not data or len(data) < 20:
            return ""
        if data[0:4] != b"XYZ ":
            return ""
        x = self._icc_s15fixed16(data[8:12])
        y = self._icc_s15fixed16(data[12:16])
        z = self._icc_s15fixed16(data[16:20])
        return f"{x:.4f},{y:.4f},{z:.4f}"

    def _decode_icc_gamma(self, data: Optional[bytes]) -> str:
        if not data or len(data) < 14:
            return ""
        if data[0:4] != b"curv":
            return ""
        count = self._icc_u32(data[8:12])
        if count != 1:
            return ""
        gamma = int.from_bytes(data[12:14], "big") / 256.0
        return f"{gamma:.4f}"

    def _icc_s15fixed16(self, data: bytes) -> float:
        if len(data) < 4:
            return 0.0
        val = int.from_bytes(data, "big", signed=True)
        return val / 65536.0

    def _build_icc_text_tag(self, text: str, tag_type: str) -> bytes:
        if tag_type == "mluc":
            encoded = text.encode("utf-16be")
            header = b"mluc" + b"\x00\x00\x00\x00"
            header += (1).to_bytes(4, "big") + (12).to_bytes(4, "big")
            record = b"enUS" + len(encoded).to_bytes(4, "big") + (len(header) + 12).to_bytes(4, "big")
            return header + record + encoded
        if tag_type == "desc":
            encoded = text.encode(errors="replace") + b"\x00"
            header = b"desc" + b"\x00\x00\x00\x00" + len(encoded).to_bytes(4, "big")
            return header + encoded
        # default to 'text'
        encoded = text.encode(errors="replace")
        return b"text" + b"\x00\x00\x00\x00" + encoded

    def _build_icc_xyz_tag(self, text: str) -> bytes:
        parts = [p.strip() for p in text.split(",") if p.strip()]
        if len(parts) != 3:
            raise ValueError("XYZ must be three comma-separated floats.")
        vals = [float(p) for p in parts]
        out = bytearray()
        out.extend(b"XYZ ")
        out.extend(b"\x00\x00\x00\x00")
        for v in vals:
            fixed = int(round(v * 65536.0))
            out.extend(fixed.to_bytes(4, "big", signed=True))
        return bytes(out)

    def _build_icc_gamma_tag(self, text: str) -> bytes:
        gamma = float(text)
        val = int(round(gamma * 256.0))
        out = bytearray()
        out.extend(b"curv")
        out.extend(b"\x00\x00\x00\x00")
        out.extend((1).to_bytes(4, "big"))
        out.extend(val.to_bytes(2, "big"))
        return bytes(out)

    def _icc_u32(self, data: bytes) -> int:
        return int.from_bytes(data, "big")

    def _icc_u16(self, data: bytes) -> int:
        return int.from_bytes(data, "big")

    def _icc_date(self, data: bytes) -> str:
        if len(data) < 12:
            return ""
        y = self._icc_u16(data[0:2])
        mo = self._icc_u16(data[2:4])
        d = self._icc_u16(data[4:6])
        h = self._icc_u16(data[6:8])
        mi = self._icc_u16(data[8:10])
        s = self._icc_u16(data[10:12])
        return f"{y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{s:02d}"

    def _write_icc_header(self, log: RichLog, icc: dict) -> None:
        h = icc["header"]
        log.write(f"ICC profile size: {h['size']} bytes")
        log.write(f"CMM: {h['cmm']}")
        log.write(f"Version: 0x{h['version']:08X}")
        log.write(f"Device class: {h['device_class']}")
        log.write(f"Color space: {h['color_space']}")
        log.write(f"PCS: {h['pcs']}")
        log.write(f"Date: {h['date']}")
        log.write(f"Magic: {h['magic']}")

    def _write_icc_tags(self, log: RichLog, icc: dict) -> None:
        tags = icc["tags"]
        if not tags:
            log.write("No ICC tags.")
            return
        for t in tags:
            log.write(f"{t['sig']} off=0x{t['offset']:08X} size={t['size']}")

    def _write_icc_tag_table(self, log: RichLog, icc: dict, payload: bytes) -> None:
        if not icc["tags"]:
            log.write("No ICC tags.")
            return
        icc_start = icc["icc_start"]
        icc_bytes = payload[14:]
        for t in icc["tags"]:
            abs_off = icc_start + t["offset"]
            tag_type = ""
            if t["offset"] + 4 <= len(icc_bytes):
                tag_type = icc_bytes[t["offset"]:t["offset"] + 4].decode(errors="replace")
            log.write(
                f"{t['sig']} type={tag_type} rel=0x{t['offset']:08X} abs=0x{abs_off:08X} size={t['size']}"
            )

    def _write_icc_table(self, log: RichLog, icc: dict) -> None:
        log.write(f"ICC start: 0x{icc['icc_start']:08X} len={icc['icc_len']}")
        log.write(f"Tag count: {len(icc['tags'])}")
        for t in icc["tags"]:
            abs_off = icc["icc_start"] + t["offset"]
            log.write(f"{t['sig']} rel=0x{t['offset']:08X} abs=0x{abs_off:08X} size={t['size']}")

    def _icc_hex_ranges(self, seg, icc: dict) -> list[Tuple[int, int, str]]:
        ranges: list[Tuple[int, int, str]] = []
        icc_start = icc["icc_start"]
        ranges.append((icc_start, icc_start + 128, "bright_blue"))
        table_start = icc_start + 128
        table_end = table_start + 4 + len(icc["tags"]) * 12
        ranges.append((table_start, table_end, "bright_cyan"))
        for t in icc["tags"]:
            start = icc_start + t["offset"]
            end = start + t["size"]
            ranges.append((start, end, "bright_magenta"))
        return ranges

    def _render_icc_hex_sections(self, log: RichLog, data: bytes, seg, icc: dict, ranges) -> None:
        icc_start = icc["icc_start"]
        icc_end = icc_start + icc["icc_len"]
        self._write_hex_section(log, "ICC header", data, icc_start, icc_start + 128, ranges, seg)
        table_start = icc_start + 128
        table_end = table_start + 4 + len(icc["tags"]) * 12
        self._write_hex_section(log, "Tag table", data, table_start, table_end, ranges, seg)
        for t in icc["tags"]:
            start = icc_start + t["offset"]
            end = start + t["size"]
            self._write_hex_section(log, f"Tag {t['sig']}", data, start, end, ranges, seg)
        if icc_end > table_end:
            self._write_hex_section(log, "ICC data", data, table_end, icc_end, ranges, seg)

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

    def _write_icc_hex_legend(self, log: RichLog) -> None:
        log.write("Legend (ICC):")
        log.write(Text("  ICC header", style="bright_blue"))
        log.write(Text("  Tag table", style="bright_cyan"))
        log.write(Text("  Tag data", style="bright_magenta"))

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

    def _app2_key_from_id(self, widget_id: Optional[str], suffix: str) -> Optional[str]:
        if not widget_id or not widget_id.startswith("app2-") or not widget_id.endswith(suffix):
            return None
        return widget_id[: -len(suffix)]

    def _set_app2_dirty(self, key: str, dirty: bool) -> None:
        self.app2_dirty[key] = dirty
        try:
            self.query_one(f"#{key}-save", Button).disabled = not dirty
        except Exception:
            return

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

    def _render_sof0_segment(self, data: bytes, segments) -> None:
        left_log = self.query_one("#info-sof0-left", RichLog)
        frame_log = self.query_one("#info-sof0-frame", RichLog)
        comps_log = self.query_one("#info-sof0-components", RichLog)
        tables_log = self.query_one("#info-sof0-tables", RichLog)
        for log in (left_log, frame_log, comps_log, tables_log):
            log.clear()
        seg = next((s for s in segments if s.name == "SOF0"), None)
        if seg is None or seg.payload_offset is None or seg.payload_length is None:
            self._clear_sof0_editor()
            left_log.write("No SOF0 segment found.")
            return
        payload = data[seg.payload_offset:seg.payload_offset + seg.payload_length]
        self.sof0_segment_info = (seg.offset, seg.total_length, seg.length_field or 0, seg.payload_offset)
        self.sof0_original_payload = payload
        self.sof0_preview_payload = payload
        self._set_sof0_editor_values(payload, seg.length_field or 0)
        self._apply_sof0_mode_visibility()
        self._mark_sof0_dirty(False)
        self._render_sof0_views(seg.offset, seg.length_field or 0, payload)

    def _render_sof0_views(self, offset: int, length_field: int, payload: bytes) -> None:
        left_log = self.query_one("#info-sof0-left", RichLog)
        frame_log = self.query_one("#info-sof0-frame", RichLog)
        comps_log = self.query_one("#info-sof0-components", RichLog)
        tables_log = self.query_one("#info-sof0-tables", RichLog)
        for log in (left_log, frame_log, comps_log, tables_log):
            log.clear()
        info = decode_sof0(payload)
        components = decode_sof_components(payload)
        self._write_sof0_left_panel(left_log, offset, length_field, payload, info, components)
        self._write_sof0_frame_tab(frame_log, info)
        self._write_sof0_components_tab(comps_log, components)
        self._write_sof0_tables_tab(tables_log, components)

    def _write_sof0_left_panel(self, log: RichLog, offset: int, length_field: int, payload: bytes, info, components) -> None:
        log.write(f"SOF0 at 0x{offset:08X} length=0x{length_field:04X} payload={len(payload)}")
        if info:
            log.write(
                f"Frame: {info['width']}x{info['height']} precision={info['precision_bits']} components={info['components']}"
            )
        log.write("SOF0 stores the baseline frame header: geometry plus one descriptor per image component.")
        log.write("Legend:")
        for label, style in [
            ("Marker", "bold yellow"),
            ("Length", "bold cyan"),
            ("Sample precision", "magenta"),
            ("Image height/width", "bright_cyan"),
            ("Component count", "bright_yellow"),
            ("Component descriptors", "green"),
        ]:
            log.write(Text("  " + label, style=style))
        for idx, comp in enumerate(components, start=1):
            log.write(
                f"Component {idx}: id={comp['id']} ({self._component_name(comp['id'])}) "
                f"sampling={comp['h_sampling']}x{comp['v_sampling']} qtable={comp['quant_table_id']}"
            )
        segment_bytes = b"\xFF\xC0" + length_field.to_bytes(2, "big") + payload
        for line in self._hex_dump(segment_bytes, 0, len(segment_bytes), self._sof0_ranges(payload)):
            log.write(line)

    def _sof0_ranges(self, payload: bytes) -> list[Tuple[int, int, str]]:
        ranges = [(0, 2, "bold yellow"), (2, 4, "bold cyan")]
        if len(payload) < 6:
            return ranges
        ranges.extend([
            (4, 5, "magenta"),
            (5, 9, "bright_cyan"),
            (9, 10, "bright_yellow"),
        ])
        cursor = 10
        while cursor + 3 <= 4 + len(payload):
            ranges.append((cursor, cursor + 3, "green"))
            cursor += 3
        return ranges

    def _write_sof0_frame_tab(self, log: RichLog, info) -> None:
        if not info:
            log.write("Could not decode SOF0 frame header.")
            return
        log.write("Baseline frame header")
        log.write(f"  Width: {info['width']}")
        log.write(f"  Height: {info['height']}")
        log.write(f"  Precision: {info['precision_bits']} bits/sample")
        log.write(f"  Components: {info['components']}")

    def _write_sof0_components_tab(self, log: RichLog, components: list[dict[str, int]]) -> None:
        if not components:
            log.write("No SOF0 component descriptors found.")
            return
        log.write("Per-component frame descriptors")
        for comp in components:
            log.write("")
            log.write(f"Component {comp['id']} ({self._component_name(comp['id'])})")
            log.write(f"  Sampling factors: H={comp['h_sampling']} V={comp['v_sampling']}")
            log.write(f"  Sampling ratio: {comp['h_sampling']}x{comp['v_sampling']}")
            log.write(f"  Quantization table id: {comp['quant_table_id']}")

    def _write_sof0_tables_tab(self, log: RichLog, components: list[dict[str, int]]) -> None:
        if not components:
            log.write("No SOF0 component descriptors found.")
            return
        log.write("Quantization-table references inferred from SOF0 component descriptors.")
        groups: dict[int, list[dict[str, int]]] = {}
        for comp in components:
            groups.setdefault(comp["quant_table_id"], []).append(comp)
        for qid in sorted(groups):
            log.write("")
            log.write(f"Quantization table id={qid}")
            for comp in groups[qid]:
                log.write(
                    f"  Component {comp['id']} ({self._component_name(comp['id'])}) "
                    f"sampling={comp['h_sampling']}x{comp['v_sampling']}"
                )

    def _clear_sof0_editor(self) -> None:
        self.sof0_segment_info = None
        self.sof0_original_payload = None
        self.sof0_preview_payload = None
        self.query_one("#sof0-raw-hex", TextArea).text = ""
        self.query_one("#sof0-struct-edit", TextArea).text = ""
        self.query_one("#sof0-length", Input).value = ""
        self._mark_sof0_dirty(False)

    def _set_sof0_editor_values(self, payload: bytes, length_field: int) -> None:
        info = decode_sof0(payload) or {
            "precision_bits": "8",
            "width": "0",
            "height": "0",
            "components": "0",
        }
        struct = {
            "precision_bits": int(info["precision_bits"]),
            "width": int(info["width"]),
            "height": int(info["height"]),
            "components": decode_sof_components(payload),
        }
        self.query_one("#sof0-raw-hex", TextArea).text = self._bytes_to_hex(payload)
        self.query_one("#sof0-struct-edit", TextArea).text = pformat(struct, width=100, sort_dicts=False)
        self.query_one("#sof0-length", Input).value = f"{length_field:04X}"

    def _render_dri_segment(self, data: bytes, segments) -> None:
        left_log = self.query_one("#info-dri-left", RichLog)
        summary_log = self.query_one("#info-dri-summary", RichLog)
        effect_log = self.query_one("#info-dri-effect", RichLog)
        for log in (left_log, summary_log, effect_log):
            log.clear()
        seg = next((s for s in segments if s.name == "DRI"), None)
        if seg is None or seg.payload_offset is None or seg.payload_length is None:
            self._clear_dri_editor()
            left_log.write("No DRI segment found.")
            return
        payload = data[seg.payload_offset:seg.payload_offset + seg.payload_length]
        self.dri_segment_info = (seg.offset, seg.total_length, seg.length_field or 0, seg.payload_offset)
        self.dri_original_payload = payload
        self.dri_preview_payload = payload
        self._set_dri_editor_values(payload, seg.length_field or 0)
        self._apply_dri_mode_visibility()
        self._mark_dri_dirty(False)
        self._render_dri_views(seg.offset, seg.length_field or 0, payload)

    def _render_dri_views(self, offset: int, length_field: int, payload: bytes) -> None:
        left_log = self.query_one("#info-dri-left", RichLog)
        summary_log = self.query_one("#info-dri-summary", RichLog)
        effect_log = self.query_one("#info-dri-effect", RichLog)
        for log in (left_log, summary_log, effect_log):
            log.clear()
        info = decode_dri(payload)
        self._write_dri_left_panel(left_log, offset, length_field, payload, info)
        self._write_dri_summary_tab(summary_log, info)
        self._write_dri_effect_tab(effect_log, info)

    def _write_dri_left_panel(self, log: RichLog, offset: int, length_field: int, payload: bytes, info) -> None:
        log.write(f"DRI at 0x{offset:08X} length=0x{length_field:04X} payload={len(payload)}")
        if info:
            log.write(f"Restart interval: {info['restart_interval']} MCUs")
        log.write("DRI sets the restart interval used by restart markers in the entropy-coded stream.")
        log.write("Legend:")
        for label, style in [
            ("Marker", "bold yellow"),
            ("Length", "bold cyan"),
            ("Restart interval", "magenta"),
        ]:
            log.write(Text("  " + label, style=style))
        segment_bytes = b"\xFF\xDD" + length_field.to_bytes(2, "big") + payload
        ranges = [(0, 2, "bold yellow"), (2, 4, "bold cyan"), (4, 6, "magenta")]
        for line in self._hex_dump(segment_bytes, 0, len(segment_bytes), ranges):
            log.write(line)

    def _write_dri_summary_tab(self, log: RichLog, info) -> None:
        if not info:
            log.write("Could not decode DRI payload.")
            return
        interval = int(info["restart_interval"])
        log.write("Define Restart Interval")
        log.write(f"  Restart interval: {interval} MCUs")
        log.write(f"  Enabled: {'yes' if interval > 0 else 'no'}")

    def _write_dri_effect_tab(self, log: RichLog, info) -> None:
        if not info:
            log.write("Could not decode DRI payload.")
            return
        interval = int(info["restart_interval"])
        log.write("Effect on entropy-coded data")
        if interval == 0:
            log.write("  Restart markers are effectively disabled.")
            log.write("  The scan may omit RST markers entirely.")
            return
        log.write(f"  Decoder expects a restart opportunity every {interval} MCUs.")
        log.write("  Restart markers can improve error resynchronization after bitstream damage.")
        log.write("  This segment does not contain the markers; it only configures their spacing.")

    def _clear_dri_editor(self) -> None:
        self.dri_segment_info = None
        self.dri_original_payload = None
        self.dri_preview_payload = None
        self.query_one("#dri-raw-hex", TextArea).text = ""
        self.query_one("#dri-struct-edit", TextArea).text = ""
        self.query_one("#dri-length", Input).value = ""
        self._mark_dri_dirty(False)

    def _set_dri_editor_values(self, payload: bytes, length_field: int) -> None:
        info = decode_dri(payload) or {"restart_interval": "0"}
        struct = {"restart_interval": int(info["restart_interval"])}
        self.query_one("#dri-raw-hex", TextArea).text = self._bytes_to_hex(payload)
        self.query_one("#dri-struct-edit", TextArea).text = pformat(struct, width=100, sort_dicts=False)
        self.query_one("#dri-length", Input).value = f"{length_field:04X}"

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
        try:
            self.query_one("#app0-save", Button).disabled = not dirty
        except Exception:
            # APP0 editor not mounted.
            return

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

    def _dqt_key_from_id(self, widget_id: Optional[str], suffix: str) -> Optional[str]:
        if not widget_id or not widget_id.startswith("dqt-") or not widget_id.endswith(suffix):
            return None
        return widget_id[: -len(suffix)]

    def _apply_dqt_mode_visibility(self, key: str) -> None:
        try:
            adv = self.query_one(f"#{key}-advanced-mode", Checkbox).value
            self.query_one(f"#{key}-grid-edit", TextArea).display = not adv
            self.query_one(f"#{key}-simple-title", Static).display = not adv
            self.query_one(f"#{key}-raw-hex", TextArea).display = adv
            self.query_one(f"#{key}-adv-title", Static).display = adv
            manual = self.query_one(f"#{key}-manual-length", Checkbox).value
            self.query_one(f"#{key}-length", Input).disabled = not manual
        except Exception:
            return

    def _set_dqt_editor_values(self, key: str, payload: bytes, length_field: int) -> None:
        tables = []
        for table in decode_dqt_tables(payload):
            tables.append({
                "id": int(table.get("id", 0)),
                "precision_bits": int(table.get("precision_bits", 8)),
                "grid": dqt_values_to_natural_grid(list(table.get("values", []))),
            })
        self.query_one(f"#{key}-raw-hex", TextArea).text = self._bytes_to_hex(payload)
        self.query_one(f"#{key}-grid-edit", TextArea).text = pformat(tables, width=100, sort_dicts=False)
        self.query_one(f"#{key}-length", Input).value = f"{length_field:04X}"

    def _sync_dqt_editor_for_mode(self, key: str) -> None:
        adv = self.query_one(f"#{key}-advanced-mode", Checkbox).value
        if adv:
            # Serialize the currently visible natural-order grids into JPEG payload order.
            parsed = ast.literal_eval(self.query_one(f"#{key}-grid-edit", TextArea).text)
            if not isinstance(parsed, list):
                raise ValueError("grid editor must be a list of table dictionaries.")
            tables = []
            for idx, item in enumerate(parsed, start=1):
                if not isinstance(item, dict):
                    raise ValueError(f"table {idx} must be a dictionary.")
                grid = item.get("grid")
                if not isinstance(grid, list) or len(grid) != 8 or any(
                    not isinstance(row, list) or len(row) != 8 for row in grid
                ):
                    raise ValueError(f"table {idx} grid must be an 8x8 list.")
                tables.append({
                    "id": int(item.get("id", 0)),
                    "precision_bits": int(item.get("precision_bits", 8)),
                    "values": dqt_natural_grid_to_values([[int(value) for value in row] for row in grid]),
                })
            payload = build_dqt_payload(tables)
            self.query_one(f"#{key}-raw-hex", TextArea).text = self._bytes_to_hex(payload)
            return
        # Switching back to structured mode should re-derive grids from the byte payload.
        payload = self._parse_hex(self.query_one(f"#{key}-raw-hex", TextArea).text)
        tables = []
        for table in decode_dqt_tables(payload):
            tables.append({
                "id": int(table.get("id", 0)),
                "precision_bits": int(table.get("precision_bits", 8)),
                "grid": dqt_values_to_natural_grid(list(table.get("values", []))),
            })
        self.query_one(f"#{key}-grid-edit", TextArea).text = pformat(tables, width=100, sort_dicts=False)

    def _build_dqt_payload(self, key: str) -> bytes:
        if self.query_one(f"#{key}-advanced-mode", Checkbox).value:
            return self._parse_hex(self.query_one(f"#{key}-raw-hex", TextArea).text)
        try:
            parsed = ast.literal_eval(self.query_one(f"#{key}-grid-edit", TextArea).text)
        except Exception as e:
            raise ValueError(f"invalid grid editor content: {e}")
        if not isinstance(parsed, list):
            raise ValueError("grid editor must be a list of table dictionaries.")
        tables = []
        for idx, item in enumerate(parsed, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"table {idx} must be a dictionary.")
            grid = item.get("grid")
            if not isinstance(grid, list) or len(grid) != 8 or any(not isinstance(row, list) or len(row) != 8 for row in grid):
                raise ValueError(f"table {idx} grid must be an 8x8 list.")
            precision = int(item.get("precision_bits", 8))
            values = dqt_natural_grid_to_values([[int(value) for value in row] for row in grid])
            tables.append({
                "id": int(item.get("id", 0)),
                "precision_bits": precision,
                "values": values,
            })
        return build_dqt_payload(tables)

    def _set_dqt_dirty(self, key: str, dirty: bool) -> None:
        self.dqt_dirty[key] = dirty
        try:
            self.query_one(f"#{key}-save", Button).disabled = not dirty
        except Exception:
            return

    def _dqt_length_from_ui(self, key: str, payload: bytes) -> int:
        if not self.query_one(f"#{key}-manual-length", Checkbox).value:
            return len(payload) + 2
        text = self.query_one(f"#{key}-length", Input).value.strip()
        if not text:
            raise ValueError("length is required in manual mode.")
        try:
            length_field = int(text, 16)
        except ValueError:
            raise ValueError("length must be hex (e.g. 0043).")
        if length_field < 2:
            raise ValueError("length must be >= 2.")
        return length_field

    def _refresh_dqt_preview(self, key: str) -> None:
        if key not in self.dqt_segment_info:
            return
        err = self.query_one(f"#{key}-error", Static)
        try:
            payload = self._build_dqt_payload(key)
            length_field = self._dqt_length_from_ui(key, payload)
        except Exception as e:
            err.update(f"Error: {e}")
            return
        err.update("")
        self.dqt_preview_payload[key] = payload
        offset, _, _, _ = self.dqt_segment_info[key]
        self._render_dqt_views(key, payload, offset, length_field)
        self._set_dqt_dirty(key, True)

    def _dqt_save_inputs(self, key: str) -> Tuple[str, bytes, int]:
        input_path = self.query_one("#input-path", Input).value.strip()
        if not input_path:
            raise ValueError("input path is required.")
        if key not in self.dqt_segment_info:
            raise ValueError("DQT not loaded. Click Load Info first.")
        payload = self._build_dqt_payload(key)
        return input_path, payload, self._dqt_length_from_ui(key, payload)

    def _dqt_write_file(self, key: str, input_path: str, payload: bytes, length_field: int) -> Path:
        offset, total_len, _, _ = self.dqt_segment_info[key]
        data = Path(input_path).read_bytes()
        marker = data[offset:offset + 2]
        new_seg = marker + length_field.to_bytes(2, "big") + payload
        new_data = data[:offset] + new_seg + data[offset + total_len:]
        out_path = Path(input_path).with_name(Path(input_path).stem + f"_{key}_edit.jpg")
        idx = 1
        while out_path.exists():
            out_path = Path(input_path).with_name(Path(input_path).stem + f"_{key}_edit_{idx}.jpg")
            idx += 1
        out_path.write_bytes(new_data)
        return out_path

    def _dqt_save_log(self, key: str, out_path: Path, payload: bytes, length_field: int) -> None:
        log = self.query_one(f"#info-{key}-left", RichLog)
        log.write(f"Saved edited file: {out_path}")
        if self.query_one(f"#{key}-manual-length", Checkbox).value and length_field != len(payload) + 2:
            log.write(f"Warning: manual length {length_field} does not match payload ({len(payload) + 2}).")

    def _dht_key_from_id(self, widget_id: Optional[str], suffix: str) -> Optional[str]:
        if not widget_id or not widget_id.startswith("dht-") or not widget_id.endswith(suffix):
            return None
        return widget_id[: -len(suffix)]

    def _apply_dht_mode_visibility(self, key: str) -> None:
        try:
            adv = self.query_one(f"#{key}-advanced-mode", Checkbox).value
            self.query_one(f"#{key}-table-edit", TextArea).display = not adv
            self.query_one(f"#{key}-simple-title", Static).display = not adv
            self.query_one(f"#{key}-raw-hex", TextArea).display = adv
            self.query_one(f"#{key}-adv-title", Static).display = adv
            manual = self.query_one(f"#{key}-manual-length", Checkbox).value
            self.query_one(f"#{key}-length", Input).disabled = not manual
        except Exception:
            return

    def _set_dht_editor_values(self, key: str, payload: bytes, length_field: int) -> None:
        tables = []
        for table in decode_dht_tables(payload):
            tables.append({
                "class": str(table["class"]),
                "id": int(table["id"]),
                "counts": list(table["counts"]),
                "symbols": list(table["symbols"]),
            })
        self.query_one(f"#{key}-raw-hex", TextArea).text = self._bytes_to_hex(payload)
        self.query_one(f"#{key}-table-edit", TextArea).text = pformat(tables, width=100, sort_dicts=False)
        self.query_one(f"#{key}-length", Input).value = f"{length_field:04X}"

    def _sync_dht_editor_for_mode(self, key: str) -> None:
        adv = self.query_one(f"#{key}-advanced-mode", Checkbox).value
        if adv:
            # Serialize the current structured Huffman tables into JPEG DHT payload bytes.
            parsed = ast.literal_eval(self.query_one(f"#{key}-table-edit", TextArea).text)
            if not isinstance(parsed, list):
                raise ValueError("table editor must be a list of table dictionaries.")
            tables = []
            for idx, item in enumerate(parsed, start=1):
                if not isinstance(item, dict):
                    raise ValueError(f"table {idx} must be a dictionary.")
                tables.append({
                    "class": str(item.get("class", "DC")),
                    "id": int(item.get("id", 0)),
                    "counts": [int(v) for v in list(item.get("counts", []))],
                    "symbols": [int(v) for v in list(item.get("symbols", []))],
                })
            payload = build_dht_payload(tables)
            self.query_one(f"#{key}-raw-hex", TextArea).text = self._bytes_to_hex(payload)
            return
        # Decode the edited bytes back into table/count/symbol dictionaries on mode switch.
        payload = self._parse_hex(self.query_one(f"#{key}-raw-hex", TextArea).text)
        tables = []
        for table in decode_dht_tables(payload):
            tables.append({
                "class": str(table["class"]),
                "id": int(table["id"]),
                "counts": list(table["counts"]),
                "symbols": list(table["symbols"]),
            })
        self.query_one(f"#{key}-table-edit", TextArea).text = pformat(tables, width=100, sort_dicts=False)

    def _build_dht_payload(self, key: str) -> bytes:
        if self.query_one(f"#{key}-advanced-mode", Checkbox).value:
            return self._parse_hex(self.query_one(f"#{key}-raw-hex", TextArea).text)
        try:
            parsed = ast.literal_eval(self.query_one(f"#{key}-table-edit", TextArea).text)
        except Exception as e:
            raise ValueError(f"invalid table editor content: {e}")
        if not isinstance(parsed, list):
            raise ValueError("table editor must be a list of table dictionaries.")
        tables = []
        for idx, item in enumerate(parsed, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"table {idx} must be a dictionary.")
            tables.append({
                "class": str(item.get("class", "DC")),
                "id": int(item.get("id", 0)),
                "counts": [int(v) for v in list(item.get("counts", []))],
                "symbols": [int(v) for v in list(item.get("symbols", []))],
            })
        return build_dht_payload(tables)

    def _set_dht_dirty(self, key: str, dirty: bool) -> None:
        self.dht_dirty[key] = dirty
        try:
            self.query_one(f"#{key}-save", Button).disabled = not dirty
        except Exception:
            return

    def _dht_length_from_ui(self, key: str, payload: bytes) -> int:
        if not self.query_one(f"#{key}-manual-length", Checkbox).value:
            return len(payload) + 2
        text = self.query_one(f"#{key}-length", Input).value.strip()
        if not text:
            raise ValueError("length is required in manual mode.")
        try:
            length_field = int(text, 16)
        except ValueError:
            raise ValueError("length must be hex (e.g. 001F).")
        if length_field < 2:
            raise ValueError("length must be >= 2.")
        return length_field

    def _refresh_dht_preview(self, key: str) -> None:
        if key not in self.dht_segment_info:
            return
        err = self.query_one(f"#{key}-error", Static)
        try:
            payload = self._build_dht_payload(key)
            length_field = self._dht_length_from_ui(key, payload)
        except Exception as e:
            err.update(f"Error: {e}")
            return
        err.update("")
        self.dht_preview_payload[key] = payload
        offset, _, _, _ = self.dht_segment_info[key]
        self._render_dht_views(key, payload, offset, length_field)
        self._set_dht_dirty(key, True)

    def _dht_save_inputs(self, key: str) -> Tuple[str, bytes, int]:
        input_path = self.query_one("#input-path", Input).value.strip()
        if not input_path:
            raise ValueError("input path is required.")
        if key not in self.dht_segment_info:
            raise ValueError("DHT not loaded. Click Load Info first.")
        payload = self._build_dht_payload(key)
        return input_path, payload, self._dht_length_from_ui(key, payload)

    def _dht_write_file(self, key: str, input_path: str, payload: bytes, length_field: int) -> Path:
        offset, total_len, _, _ = self.dht_segment_info[key]
        data = Path(input_path).read_bytes()
        marker = data[offset:offset + 2]
        new_seg = marker + length_field.to_bytes(2, "big") + payload
        new_data = data[:offset] + new_seg + data[offset + total_len:]
        out_path = Path(input_path).with_name(Path(input_path).stem + f"_{key}_edit.jpg")
        idx = 1
        while out_path.exists():
            out_path = Path(input_path).with_name(Path(input_path).stem + f"_{key}_edit_{idx}.jpg")
            idx += 1
        out_path.write_bytes(new_data)
        return out_path

    def _dht_save_log(self, key: str, out_path: Path, payload: bytes, length_field: int) -> None:
        log = self.query_one(f"#info-{key}-left", RichLog)
        log.write(f"Saved edited file: {out_path}")
        if self.query_one(f"#{key}-manual-length", Checkbox).value and length_field != len(payload) + 2:
            log.write(f"Warning: manual length {length_field} does not match payload ({len(payload) + 2}).")

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

    def _app2_save_inputs(self, key: str) -> Tuple[str, bytes]:
        input_path = self.query_one("#input-path", Input).value.strip()
        if not input_path:
            raise ValueError("input path is required.")
        if key not in self.app2_segment_info:
            raise ValueError("APP2 not loaded. Click Load Info first.")
        payload = self.app2_original_payload.get(key, b"")
        icc = self._parse_icc_profile(payload, self.app2_segment_info[key][3])
        if icc.get("error"):
            raise ValueError(f"ICC parse error: {icc['error']}")
        tag_map = self._icc_tag_data_map(icc, payload)
        desc = self.query_one(f"#{key}-desc-input", Input).value.strip()
        cprt = self.query_one(f"#{key}-cprt-input", Input).value.strip()
        dmnd = self.query_one(f"#{key}-dmnd-input", Input).value.strip()
        dmdd = self.query_one(f"#{key}-dmdd-input", Input).value.strip()
        wtpt = self.query_one(f"#{key}-wtpt-input", Input).value.strip()
        bkpt = self.query_one(f"#{key}-bkpt-input", Input).value.strip()
        rxyz = self.query_one(f"#{key}-rxyz-input", Input).value.strip()
        gxyz = self.query_one(f"#{key}-gxyz-input", Input).value.strip()
        bxyz = self.query_one(f"#{key}-bxyz-input", Input).value.strip()
        rtrc = self.query_one(f"#{key}-rtrc-input", Input).value.strip()
        gtrc = self.query_one(f"#{key}-gtrc-input", Input).value.strip()
        btrc = self.query_one(f"#{key}-btrc-input", Input).value.strip()
        tag_types = self.app2_tag_types.get(key, {})
        updates: dict[str, bytes] = {}
        if desc:
            updates["desc"] = self._build_icc_text_tag(desc, tag_types.get("desc", "desc") or "desc")
        if cprt:
            updates["cprt"] = self._build_icc_text_tag(cprt, tag_types.get("cprt", "text") or "text")
        if dmnd:
            updates["dmnd"] = self._build_icc_text_tag(dmnd, "text")
        if dmdd:
            updates["dmdd"] = self._build_icc_text_tag(dmdd, "text")
        if wtpt:
            updates["wtpt"] = self._build_icc_xyz_tag(wtpt)
        if bkpt:
            updates["bkpt"] = self._build_icc_xyz_tag(bkpt)
        if rxyz:
            updates["rXYZ"] = self._build_icc_xyz_tag(rxyz)
        if gxyz:
            updates["gXYZ"] = self._build_icc_xyz_tag(gxyz)
        if bxyz:
            updates["bXYZ"] = self._build_icc_xyz_tag(bxyz)
        if rtrc:
            updates["rTRC"] = self._build_icc_gamma_tag(rtrc)
        if gtrc:
            updates["gTRC"] = self._build_icc_gamma_tag(gtrc)
        if btrc:
            updates["bTRC"] = self._build_icc_gamma_tag(btrc)
        new_icc = self._rebuild_icc_profile(payload[14:], icc["tags"], tag_map, updates)
        new_payload = b"ICC_PROFILE\x00" + bytes([1, 1]) + new_icc
        return input_path, new_payload

    def _rebuild_icc_profile(
        self, icc: bytes, tags: list[dict], tag_map: dict[str, bytes], updates: dict[str, bytes]
    ) -> bytes:
        order = [t["sig"] for t in tags]
        for sig in updates.keys():
            if sig not in order:
                order.append(sig)
        tag_data = {**tag_map, **updates}
        table_size = 4 + len(order) * 12
        data_start = 128 + table_size
        offsets: list[tuple[str, int, int]] = []
        cursor = data_start
        for sig in order:
            data_bytes = tag_data.get(sig, b"")
            size = len(data_bytes)
            offsets.append((sig, cursor, size))
            pad = (4 - (size % 4)) % 4
            cursor += size + pad
        size = cursor
        header = bytearray(icc[:128])
        header[0:4] = size.to_bytes(4, "big")
        out = bytearray()
        out.extend(header)
        out.extend(len(order).to_bytes(4, "big"))
        for sig, off, sz in offsets:
            out.extend(sig.encode("ascii", errors="replace"))
            out.extend(off.to_bytes(4, "big"))
            out.extend(sz.to_bytes(4, "big"))
        for sig, off, sz in offsets:
            data_bytes = tag_data.get(sig, b"")
            out.extend(data_bytes)
            pad = (4 - (len(data_bytes) % 4)) % 4
            if pad:
                out.extend(b"\x00" * pad)
        return bytes(out)

    def _app2_write_file(self, input_path: str, key: str, payload: bytes) -> Path:
        offset, total_len, _, _ = self.app2_segment_info[key]
        data = Path(input_path).read_bytes()
        marker = data[offset:offset + 2]
        length_field = len(payload) + 2
        new_seg = marker + length_field.to_bytes(2, "big") + payload
        new_data = data[:offset] + new_seg + data[offset + total_len:]
        out_path = Path(input_path).with_name(Path(input_path).stem + "_app2_edit.jpg")
        idx = 1
        while out_path.exists():
            out_path = Path(input_path).with_name(Path(input_path).stem + f"_app2_edit_{idx}.jpg")
            idx += 1
        out_path.write_bytes(new_data)
        return out_path

    def _refresh_app2_preview(self, key: str) -> None:
        err = self.query_one(f"#{key}-error", Static)
        err.update("")
        try:
            _, payload = self._app2_save_inputs(key)
        except Exception as e:
            err.update(f"Error: {e}")
            return
        self.app2_preview_payload[key] = payload
        seg_info = self.app2_segment_info.get(key)
        if not seg_info:
            return
        seg = self._app2_seg_from_info(seg_info, payload)
        data = self._app2_preview_data(self.info_data or b"", seg, payload)
        icc = self._parse_icc_profile(payload, seg.payload_offset)
        log_hex = self.query_one(f"#info-{key}-hex", RichLog)
        log_raw = self.query_one(f"#info-{key}-raw", RichLog)
        log_table = self.query_one(f"#info-{key}-table", RichLog)
        log_header = self.query_one(f"#{key}-header", RichLog)
        log_tags = self.query_one(f"#{key}-tags", RichLog)
        log_table2 = self.query_one(f"#{key}-tag-table", RichLog)
        log_hex.clear()
        log_raw.clear()
        log_table.clear()
        log_header.clear()
        log_tags.clear()
        log_table2.clear()
        if icc.get("error"):
            log_hex.write(f"ICC decode error: {icc['error']}")
            self._render_app2_raw_hex(log_raw, data, seg)
            return
        self._write_icc_header(log_header, icc)
        self._write_icc_tags(log_tags, icc)
        self._write_icc_table(log_table, icc)
        self._write_icc_tag_table(log_table2, icc, payload)
        ranges = self._icc_hex_ranges(seg, icc)
        self._write_icc_hex_legend(log_hex)
        self._render_icc_hex_sections(log_hex, data, seg, icc, ranges)
        self._render_app2_raw_hex(log_raw, data, seg)
        self._set_app2_dirty(key, True)

    def _app2_preview_data(self, data: bytes, seg, payload: bytes) -> bytes:
        if not data:
            return payload
        return data[:seg.payload_offset] + payload + data[seg.payload_offset + seg.payload_length:]

    def _app2_seg_from_info(self, seg_info: Tuple[int, int, int, int], payload: bytes):
        offset, total_len, length_field, payload_offset = seg_info
        seg = type("Seg", (), {})()
        seg.offset = offset
        seg.total_length = total_len
        seg.length_field = length_field
        seg.payload_offset = payload_offset
        seg.payload_length = len(payload)
        return seg

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
        ranges: list[Tuple[int, int, str]] = []
        for idx, seg in enumerate(self.info_segments):
            start = seg.offset
            end = seg.offset + seg.total_length
            ranges.append((start, end, self._segment_color(idx)))
        return ranges

    def _segment_color(self, idx: int) -> str:
        # Deterministic bright colors with good separation.
        hue = (idx * 0.61803398875) % 1.0
        sat = 0.65
        val = 0.95
        r, g, b = self._hsv_to_rgb(hue, sat, val)
        return f"#{r:02X}{g:02X}{b:02X}"

    def _hsv_to_rgb(self, h: float, s: float, v: float) -> tuple[int, int, int]:
        i = int(h * 6.0)
        f = (h * 6.0) - i
        p = v * (1.0 - s)
        q = v * (1.0 - f * s)
        t = v * (1.0 - (1.0 - f) * s)
        i = i % 6
        if i == 0:
            r, g, b = v, t, p
        elif i == 1:
            r, g, b = q, v, p
        elif i == 2:
            r, g, b = p, v, t
        elif i == 3:
            r, g, b = p, q, v
        elif i == 4:
            r, g, b = t, p, v
        else:
            r, g, b = v, p, q
        return int(r * 255), int(g * 255), int(b * 255)

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

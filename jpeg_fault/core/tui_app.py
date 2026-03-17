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
from typing import Callable, Optional, Tuple
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

from .tui_segments_basic import TuiSegmentsBasicMixin
from .tui_segments_tables import TuiSegmentsTablesMixin
from .tui_segments_appn import TuiSegmentsAppnMixin
from .tui_hex import TuiHexMixin



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


class JpegFaultTui(App, TuiSegmentsBasicMixin, TuiSegmentsTablesMixin, TuiSegmentsAppnMixin, TuiHexMixin):
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

    def _apply_editor_mode_visibility(
        self,
        *,
        advanced_id: str,
        struct_id: str,
        simple_title_id: str,
        raw_id: str,
        adv_title_id: str,
        manual_length_id: str,
        length_id: str,
    ) -> None:
        try:
            adv = self.query_one(f"#{advanced_id}", Checkbox).value
            self.query_one(f"#{struct_id}", TextArea).display = not adv
            self.query_one(f"#{simple_title_id}", Static).display = not adv
            self.query_one(f"#{raw_id}", TextArea).display = adv
            self.query_one(f"#{adv_title_id}", Static).display = adv
            manual = self.query_one(f"#{manual_length_id}", Checkbox).value
            self.query_one(f"#{length_id}", Input).disabled = not manual
        except Exception:
            return

    def _length_from_ui_hex(
        self,
        *,
        manual_length_id: str,
        length_id: str,
        payload: bytes,
        example: str,
    ) -> int:
        if not self.query_one(f"#{manual_length_id}", Checkbox).value:
            return len(payload) + 2
        text = self.query_one(f"#{length_id}", Input).value.strip()
        if not text:
            raise ValueError("length is required in manual mode.")
        try:
            length_field = int(text, 16)
        except ValueError:
            raise ValueError(f"length must be hex (e.g. {example}).")
        if length_field < 2:
            raise ValueError("length must be >= 2.")
        return length_field

    def _write_segment_edit_file(
        self,
        *,
        input_path: str,
        offset: int,
        total_len: int,
        payload: bytes,
        length_field: int,
        suffix: str,
    ) -> Path:
        data = Path(input_path).read_bytes()
        marker = data[offset:offset + 2]
        new_seg = marker + length_field.to_bytes(2, "big") + payload
        new_data = data[:offset] + new_seg + data[offset + total_len:]
        out_path = Path(input_path).with_name(Path(input_path).stem + suffix + ".jpg")
        idx = 1
        while out_path.exists():
            out_path = Path(input_path).with_name(Path(input_path).stem + f"{suffix}_{idx}.jpg")
            idx += 1
        out_path.write_bytes(new_data)
        return out_path

    def _segment_save_log(
        self,
        *,
        log_id: str,
        out_path: Path,
        payload: bytes,
        length_field: int,
        manual_length_id: str,
    ) -> None:
        log = self.query_one(f"#{log_id}", RichLog)
        log.write(f"Saved edited file: {out_path}")
        if (
            self.query_one(f"#{manual_length_id}", Checkbox).value
            and length_field != len(payload) + 2
        ):
            log.write(
                f"Warning: manual length {length_field} does not match payload ({len(payload) + 2})."
            )

    def _refresh_single_segment_preview(
        self,
        *,
        segment_info: Optional[Tuple[int, int, int, int]],
        err_id: str,
        build_payload: Callable[[], bytes],
        length_from_ui: Callable[[bytes], int],
        set_preview: Callable[[bytes], None],
        render_views: Callable[[int, int, bytes], None],
        mark_dirty: Callable[[bool], None],
    ) -> None:
        if not segment_info:
            return
        err = self.query_one(f"#{err_id}", Static)
        try:
            payload = build_payload()
            length_field = length_from_ui(payload)
        except Exception as e:
            err.update(f"Error: {e}")
            return
        err.update("")
        set_preview(payload)
        offset, _, _, _ = segment_info
        render_views(offset, length_field, payload)
        mark_dirty(True)

    def _sync_editor_for_mode(
        self,
        *,
        advanced_id: str,
        raw_id: str,
        serialize_struct: Callable[[], bytes],
        deserialize_payload: Callable[[bytes], None],
    ) -> None:
        adv = self.query_one(f"#{advanced_id}", Checkbox).value
        if adv:
            payload = serialize_struct()
            self.query_one(f"#{raw_id}", TextArea).text = self._bytes_to_hex(payload)
            return
        payload = self._parse_hex(self.query_one(f"#{raw_id}", TextArea).text)
        deserialize_payload(payload)

    def _sync_keyed_editor_for_mode(
        self,
        *,
        key: str,
        advanced_id: str,
        raw_id: str,
        serialize_struct: Callable[[str], bytes],
        deserialize_payload: Callable[[str, bytes], None],
    ) -> None:
        adv = self.query_one(f"#{advanced_id}", Checkbox).value
        if adv:
            payload = serialize_struct(key)
            self.query_one(f"#{raw_id}", TextArea).text = self._bytes_to_hex(payload)
            return
        payload = self._parse_hex(self.query_one(f"#{raw_id}", TextArea).text)
        deserialize_payload(key, payload)

    def _refresh_keyed_segment_preview(
        self,
        *,
        key: str,
        segment_info: dict[str, Tuple[int, int, int, int]],
        err_id: str,
        build_payload: Callable[[str], bytes],
        length_from_ui: Callable[[str, bytes], int],
        set_preview: Callable[[str, bytes], None],
        render_views: Callable[[str, bytes, int, int], None],
        set_dirty: Callable[[str, bool], None],
    ) -> None:
        if key not in segment_info:
            return
        err = self.query_one(f"#{err_id}", Static)
        try:
            payload = build_payload(key)
            length_field = length_from_ui(key, payload)
        except Exception as e:
            err.update(f"Error: {e}")
            return
        err.update("")
        set_preview(key, payload)
        offset, _, _, _ = segment_info[key]
        render_views(key, payload, offset, length_field)
        set_dirty(key, True)

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

    def _parse_hex_lenient(self, text: str) -> bytes:
        """
        Parse hex for live preview, tolerating odd-length input by trimming the last nibble.
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
            compact = compact[:-1]
        if not compact:
            return b""
        return bytes.fromhex(compact)

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


def _register_mixin_handlers() -> None:
    if getattr(JpegFaultTui, "_mixin_handlers_registered", False):
        return
    JpegFaultTui._mixin_handlers_registered = True
    for mixin in (
        TuiSegmentsBasicMixin,
        TuiSegmentsTablesMixin,
        TuiSegmentsAppnMixin,
        TuiHexMixin,
    ):
        for value in mixin.__dict__.values():
            if callable(value) and hasattr(value, "_textual_on"):
                for message_type, selectors in value._textual_on:  # type: ignore[attr-defined]
                    JpegFaultTui._decorated_handlers.setdefault(message_type, []).append((value, selectors))


_register_mixin_handlers()


def run_tui(defaults: Optional[TuiDefaults] = None) -> None:
    """
    Launch the Textual TUI.
    """
    app = JpegFaultTui(defaults=defaults)
    app.run()

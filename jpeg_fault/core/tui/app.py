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
from collections import defaultdict

try:
    import piexif
except ImportError:  # pragma: no cover - optional dependency
    piexif = None

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches, WrongType
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
from textual.widget import Widget
from textual.worker import Worker, WorkerState
from rich.text import Text

from .. import api
from ..analysis_registry import all_plugins, get_plugin, load_plugins
from ..analysis_types import AnalysisContext, PluginParamSpec, validate_plugin_params
from ..debug import debug_log
from ..mutation_registry import all_plugins as all_mutation_plugins, get_plugin as get_mutation_plugin, load_plugins as load_mutation_plugins
from ..plugin_contexts import build_analysis_context, build_mutation_context
from ..format_detect import detect_format
from ..tui_plugin_registry import all_tui_plugins
from ..jpeg_parse import (
    MARKER_NAMES,
    build_dri_payload,
    build_dht_payload,
    build_dqt_payload,
    build_sof0_payload,
    build_sos_payload,
    decode_app0,
    decode_dri,
    decode_dht,
    decode_dht_tables,
    decode_dqt,
    decode_dqt_tables,
    decode_sof0,
    decode_sof_components,
    decode_sos,
    decode_sos_components,
    dqt_natural_grid_to_values,
    dqt_values_to_natural_grid,
    parse_jpeg,
)
from ..mutate import total_entropy_length
from ..report import explain_segment
from ..entropy_trace import stream_entropy_scans

from .segments_basic import TuiSegmentsBasicMixin
from .segments_sos import TuiSegmentsSosMixin
from .segments_tables import TuiSegmentsTablesMixin
from .segments_appn import TuiSegmentsAppnMixin
from .entropy_trace import TuiEntropyTraceMixin
from .hex import TuiHexMixin


QUERY_ERRORS = (NoMatches, WrongType, AssertionError)



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
    analysis: str = ""
    mutation_plugins: str = ""
    debug: bool = False


class JpegOnlyDirTree(DirectoryTree):
    """
    DirectoryTree that shows directories only (no files).
    """

    def filter_paths(self, paths):
        return [p for p in paths if Path(p).is_dir()]


class JpegFaultTui(App, TuiSegmentsBasicMixin, TuiSegmentsSosMixin, TuiSegmentsTablesMixin, TuiSegmentsAppnMixin, TuiEntropyTraceMixin, TuiHexMixin):
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
    #log { height: 3; border: solid $secondary; }
    #mutation-left { width: 1fr; }
    #mutation-right { width: 1fr; }
    #mutation-help-col { width: 1fr; }
    #mutation-help { height: 1fr; border: solid $secondary; }
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
    info_entropy_ranges: Optional[list] = None
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
    dqt_active_highlight: dict[str, Tuple[int, int, str, str]] = {}
    dqt_dirty: dict[str, bool] = {}
    dht_segment_info: dict[str, Tuple[int, int, int, int]] = {}
    dht_original_payload: dict[str, bytes] = {}
    dht_preview_payload: dict[str, bytes] = {}
    dht_active_highlight: dict[str, Tuple[int, int, str, str]] = {}
    dht_dirty: dict[str, bool] = {}
    sos_segment_info: dict[str, Tuple[int, int, int, int]] = {}
    sos_original_payload: dict[str, bytes] = {}
    sos_preview_payload: dict[str, bytes] = {}
    sos_active_highlight: dict[str, Tuple[int, int, str, str]] = {}
    sos_dirty: dict[str, bool] = {}
    sos_scan_index: dict[str, int] = {}
    sos_root_ids: dict[str, str] = {}
    dri_segment_info: Optional[Tuple[int, int, int, int]] = None
    dri_original_payload: Optional[bytes] = None
    dri_preview_payload: Optional[bytes] = None
    dri_dirty = reactive(False)
    sof0_segment_info: Optional[Tuple[int, int, int, int]] = None
    sof0_original_payload: Optional[bytes] = None
    sof0_preview_payload: Optional[bytes] = None
    sof0_active_highlight: Optional[Tuple[int, int, str, str]] = None
    sof0_dirty = reactive(False)
    sof_root_ids: dict[str, str] = {}
    sof_render_retry_budget: dict[str, int] = {}
    plugin_ids: list[str] = []
    plugin_button_ids: dict[str, str] = {}
    selected_plugin_info_id: str = ""
    plugins_render_counter = reactive(0)
    plugin_panels: dict[str, VerticalScroll] = {}
    plugin_panel_tabs: dict[str, TabbedContent] = {}
    entropy_trace_scans: dict[str, object] = {}
    entropy_trace_pages: dict[str, int] = {}
    entropy_trace_selected: dict[str, int] = {}
    entropy_trace_item_ids: dict[str, dict[str, int]] = {}
    entropy_trace_log_ids: dict[str, dict[str, str]] = {}
    entropy_trace_item_counter = reactive(0)
    entropy_trace_loaded = reactive(False)
    entropy_trace_pending = reactive(False)
    _entropy_trace_worker_serial = 0
    _suppress_input_path_changed = False
    _pending_input_load_token = 0
    _info_rebuild_serial = 0

    def __init__(self, defaults: Optional[TuiDefaults] = None) -> None:
        super().__init__()
        self.defaults = defaults or TuiDefaults()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            with ListView(id="menu"):
                yield ListItem(Label("Input & Output"), id="menu-input")
                yield ListItem(Label("Info"), id="menu-info")
                yield ListItem(Label("Core Mutations"), id="menu-mutation")
                yield ListItem(Label("Outputs"), id="menu-outputs")
                yield ListItem(Label("Plugins"), id="menu-plugins")
            with Container(id="panel"):
                yield self._build_input_panel()
                yield self._build_info_panel()
                yield self._build_mutation_panel()
                yield self._build_outputs_panel()
                yield self._build_plugins_panel()
        yield Footer()

    def on_mount(self) -> None:
        """
        Select the first menu item on startup to show the initial panel.
        """
        menu = self.query_one("#menu", ListView)
        menu.index = 0
        self._show_panel("input")
        self.call_later(self._init_info_tabs)
        self.call_later(self._init_dri_tabs)
        self.call_later(self._apply_app0_mode_visibility)
        self.call_later(self._apply_dri_mode_visibility)
        self.call_later(self._apply_sof0_mode_visibility)
        self.call_later(self._apply_mutation_mode_visibility)
        self.call_later(self._refresh_mutation_help)
        self.call_later(lambda: self._set_current_dir(Path(".")))
        self.call_later(self._refresh_plugins_list)
        self.call_later(self._init_plugin_panels)

    def on_resize(self) -> None:
        if self.preview_path:
            self._update_input_preview(self.preview_path)
        try:
            panel = self.query_one("#panel-input", VerticalScroll)
        except QUERY_ERRORS:
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
                    Checkbox("Debug logging", value=self.defaults.debug, id="debug"),
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
            Horizontal(
                Vertical(
                    Label("Core Mutations", classes="field"),
                    Label("Mutation mode", classes="field"),
                    Select(
                        self._mutation_mode_options(),
                        value=self._default_mutation_mode_value(),
                        id="mutate-mode",
                    ),
                    Static("Bit indexes (comma-separated, or lsb/msb)", classes="field", id="mutate-bitflip-label"),
                    Input(value=self._default_mutation_bits_value(), id="mutate-bitflip-bits"),
                    Label("Sample (0 = all/maximum)", classes="field"),
                    Input(value=str(self.defaults.sample), id="sample"),
                    Label("Seed", classes="field"),
                    Input(value=str(self.defaults.seed), id="seed"),
                    Checkbox("Overflow wrap (add1/sub1)", value=self.defaults.overflow_wrap, id="overflow-wrap"),
                    id="mutation-left",
                ),
                Vertical(
                    Label("Strategy", classes="field"),
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
                    Checkbox("Report only", value=self.defaults.report_only, id="report-only"),
                    Static("", id="run-error"),
                    Button("Run", id="run-btn", variant="success"),
                    RichLog(id="log", highlight=True),
                    id="mutation-right",
                ),
                Vertical(
                    Label("Will Generate", classes="field"),
                    Static("", id="mutation-help"),
                    id="mutation-help-col",
                ),
                classes="row",
            ),
            id="panel-mutation",
        )
        panel.display = False
        return panel

    def _mutation_mode_options(self) -> list[tuple[str, str]]:
        return [(mode, mode) for mode in ("add1", "sub1", "flipall", "ff", "00", "bitflip")]

    def _default_mutation_mode_value(self) -> str:
        spec = self.defaults.mutate.strip()
        return "bitflip" if spec.startswith("bitflip:") else (spec or "add1")

    def _default_mutation_bits_value(self) -> str:
        spec = self.defaults.mutate.strip()
        if spec.startswith("bitflip:"):
            return spec.split(":", 1)[1] or "0,2,7"
        return "0,2,7"

    def _apply_mutation_mode_visibility(self) -> None:
        try:
            mode = self.query_one("#mutate-mode", Select).value
            label = self.query_one("#mutate-bitflip-label", Static)
            bits = self.query_one("#mutate-bitflip-bits", Input)
        except QUERY_ERRORS:
            return
        show = mode == "bitflip"
        label.display = show
        bits.display = show

    def _refresh_mutation_help(self) -> None:
        try:
            help_widget = self.query_one("#mutation-help", Static)
        except QUERY_ERRORS:
            return
        help_widget.update(self._mutation_help_text())

    def _mutation_help_text(self) -> str:
        mutate_mode = self._select_value("#mutate-mode", default="add1")
        bit_spec = self._input_value("#mutate-bitflip-bits", default="0,2,7")
        mutate = f"bitflip:{bit_spec}" if mutate_mode == "bitflip" else mutate_mode
        strategy = self._select_value("#mutation-apply", default="independent")
        sample = self._input_value("#sample", default="100")
        seed = self._input_value("#seed", default="3")
        repeats = self._input_value("#repeats", default="1")
        step = self._input_value("#step", default="1")
        overflow_wrap = self._checkbox_value("#overflow-wrap")
        report_only = self._checkbox_value("#report-only")
        debug = self._checkbox_value("#debug")
        gif = self._input_value("#gif")
        ssim_chart = self._input_value("#ssim-chart")
        metrics_prefix = self._input_value("#metrics-prefix")
        selected_plugins = self._safe_selected_plugins_csv()
        input_path = self._input_value("#input-path", default="<input.jpg>")
        output_dir = self._input_value("#output-dir", default="mutations")

        lines = [
            self._describe_mutation_mode(mutate, sample, overflow_wrap),
            self._describe_mutation_strategy(strategy, repeats, step),
        ]
        if report_only:
            lines.append(
                "Report only is enabled, so the app will parse and report the JPEG structure but will not write mutated JPEG files."
            )
        else:
            lines.append(
                "The main output will be mutated JPEG files written into the selected output directory according to the mutation mode and strategy above."
            )
        extras: list[str] = []
        if gif:
            extras.append("a GIF built from the generated mutation outputs")
        if ssim_chart:
            extras.append("an SSIM chart for the generated mutation outputs")
        if metrics_prefix:
            extras.append("metric charts for the generated mutation outputs")
        if selected_plugins:
            extras.append(f"analysis plugin outputs from {selected_plugins}")
        if extras:
            lines.append("In addition, the current settings will generate " + ", ".join(extras) + ".")
        else:
            lines.append("No extra derived outputs are currently enabled beyond the main mutated JPEG files.")
        lines.append(self._mutation_cli_text(input_path, output_dir, mutate, sample, seed, strategy, repeats, step, overflow_wrap, report_only, debug))
        return "\n\n".join(lines)

    def _describe_mutation_mode(self, mutate: str, sample: str, overflow_wrap: bool) -> str:
        if mutate == "add1":
            effect = "Each selected entropy byte will be increased by 1."
            if overflow_wrap:
                effect += " If a byte is 0xFF, it will wrap to 0x00 instead of being skipped."
            else:
                effect += " Bytes already at 0xFF will be skipped."
        elif mutate == "sub1":
            effect = "Each selected entropy byte will be decreased by 1."
            if overflow_wrap:
                effect += " If a byte is 0x00, it will wrap to 0xFF instead of being skipped."
            else:
                effect += " Bytes already at 0x00 will be skipped."
        elif mutate == "flipall":
            effect = "Each selected entropy byte will be inverted bitwise."
        elif mutate == "ff":
            effect = "Each selected entropy byte will be replaced with 0xFF."
        elif mutate == "00":
            effect = "Each selected entropy byte will be replaced with 0x00."
        elif mutate.startswith("bitflip:"):
            bits = mutate.split(":", 1)[1]
            effect = f"Each selected entropy byte will have bit positions {bits} toggled."
        else:
            effect = f"Selected entropy bytes will be mutated using {mutate}."
        return f"{effect} The current sample setting is {sample}, which controls how many offsets or mutation steps will be generated."

    def _describe_mutation_strategy(self, strategy: str, repeats: str, step: str) -> str:
        if strategy == "independent":
            return (
                "Independent strategy means every output file starts from the original JPEG, so each file shows one isolated mutation result without carrying prior byte changes forward."
            )
        if strategy == "cumulative":
            return (
                f"Cumulative strategy means output files are populated in sequence, and each new file keeps all earlier byte changes and adds the next group of mutations. Repeats is {repeats} and step is {step}, so each step adds {step} more mutable-byte edits per repeat set."
            )
        if strategy == "sequential":
            return (
                f"Sequential strategy also keeps earlier byte changes in later files, but it walks forward through contiguous mutable entropy bytes instead of sampling them randomly. Repeats is {repeats} and step is {step}, so each successive file grows by {step} neighboring byte edits per repeat set."
            )
        return f"The selected strategy is {strategy} with repeats={repeats} and step={step}."

    def _mutation_cli_text(
        self,
        input_path: str,
        output_dir: str,
        mutate: str,
        sample: str,
        seed: str,
        strategy: str,
        repeats: str,
        step: str,
        overflow_wrap: bool,
        report_only: bool,
        debug: bool,
    ) -> str:
        parts = [
            f"./jpg_fault_tolerance.py {input_path}",
            f"-o {output_dir}",
            f"--mutate {mutate}",
            f"--sample {sample}",
            f"--seed {seed}",
            f"--mutation-apply {strategy}",
        ]
        if repeats != "1":
            parts.append(f"--repeats {repeats}")
        if step != "1":
            parts.append(f"--step {step}")
        if overflow_wrap:
            parts.append("--overflow-wrap")
        if report_only:
            parts.append("--report-only")
        if debug:
            parts.append("--debug")
        return "Equivalent CLI command:\n" + " ".join(parts)

    def _input_value(self, selector: str, default: str = "") -> str:
        try:
            return self.query_one(selector, Input).value.strip()
        except QUERY_ERRORS:
            return default

    def _select_value(self, selector: str, default: str = "") -> str:
        try:
            value = self.query_one(selector, Select).value
        except QUERY_ERRORS:
            return default
        return default if value is None else str(value).strip()

    def _checkbox_value(self, selector: str) -> bool:
        try:
            return bool(self.query_one(selector, Checkbox).value)
        except QUERY_ERRORS:
            return False

    def _safe_selected_plugins_csv(self) -> str:
        try:
            return self._selected_plugins_csv()
        except QUERY_ERRORS:
            return ""

    @on(Select.Changed, "#mutate-mode")
    def _on_mutation_mode_changed(self, _event: Select.Changed) -> None:
        self._apply_mutation_mode_visibility()
        self._refresh_mutation_help()
        self._refresh_mutation_plugin_help()

    @on(Select.Changed, "#mutation-apply")
    def _on_mutation_strategy_changed(self, _event: Select.Changed) -> None:
        self._refresh_mutation_help()
        self._refresh_mutation_plugin_help()

    @on(Input.Changed)
    def _on_mutation_help_input_changed(self, event: Input.Changed) -> None:
        if (event.input.id or "") in {
            "mutate-bitflip-bits",
            "sample",
            "seed",
            "repeats",
            "step",
            "gif",
            "ssim-chart",
            "metrics-prefix",
        }:
            self._refresh_mutation_help()
            self._refresh_mutation_plugin_help()
            return
        input_id = event.input.id or ""
        if input_id.startswith("plugin-"):
            plugin_id = self._plugin_id_from_widget_id(input_id)
            if plugin_id:
                self._update_mutation_plugin_help(plugin_id)

    @on(Checkbox.Changed)
    def _on_mutation_help_checkbox_changed(self, _event: Checkbox.Changed) -> None:
        self._refresh_mutation_help()
        self._refresh_mutation_plugin_help()

    def _build_info_panel(self) -> VerticalScroll:
        panel = VerticalScroll(
            TabbedContent(id="info-tabs"),
            id="panel-info",
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
            id="panel-outputs",
        )
        panel.display = False
        return panel

    def _build_plugins_panel(self) -> VerticalScroll:
        panel = VerticalScroll(
            Label("Plugins", classes="panel-title"),
            Static("Read-only analysis plugin inventory.", classes="field"),
            Horizontal(
                VerticalScroll(
                    Static("Detected format: unknown", classes="field", id="plugins-format"),
                    Static("Available plugins", classes="field"),
                    Vertical(id="plugins-list"),
                ),
                VerticalScroll(
                    Static("Plugin details", classes="field"),
                    Static("Click a plugin entry to inspect it.", classes="field", id="plugins-help"),
                ),
                classes="row",
            ),
            id="panel-plugins",
        )
        panel.display = False
        return panel

    def _init_plugin_panels(self) -> None:
        try:
            menu = self.query_one("#menu", ListView)
            panel = self.query_one("#panel", Container)
        except QUERY_ERRORS:
            return
        load_plugins(debug=False)
        load_mutation_plugins(debug=False)
        specs = sorted(list(all_tui_plugins()), key=lambda p: (p.panel_label, p.tab_label, p.id))
        if not specs:
            return
        grouped_specs: dict[str, list] = defaultdict(list)
        for spec in specs:
            grouped_specs[spec.panel_id].append(spec)
        # Build panel containers by panel_id.
        for panel_key, panel_specs in grouped_specs.items():
            if panel_key not in self.plugin_panels:
                panel_id = f"panel-plugin-{panel_key}"
                tab_id = f"plugin-tabs-{panel_key}"
                tabs = self._build_plugin_tabs(panel_specs, tab_id)
                children = [Label(panel_specs[0].panel_label, classes="panel-title")]
                if isinstance(tabs, Widget):
                    children.append(tabs)
                vs = VerticalScroll(*children, id=panel_id)
                if not isinstance(tabs, Widget):
                    try:
                        vs.mount(tabs)
                    except Exception:
                        # Tests may patch TabbedContent with a lightweight fake object.
                        pass
                vs.display = False
                panel.mount(vs)
                self.plugin_panels[panel_key] = vs
                self.plugin_panel_tabs[panel_key] = tabs
                self._append_list_view_item(
                    menu,
                    ListItem(Label(panel_specs[0].panel_label), id=f"menu-plugin-{panel_key}"),
                )
            self.call_after_refresh(self._populate_plugin_panel_tabs, panel_key, panel_specs)

    def _build_plugin_tabs(self, _panel_specs: list, tab_id: str) -> object:
        return TabbedContent(id=tab_id)

    def _populate_plugin_panel_tabs(self, panel_key: str, panel_specs: list) -> None:
        tabs = self.plugin_panel_tabs.get(panel_key)
        if not tabs:
            return
        if getattr(tabs, "_plugin_tabs_loaded", False):
            return
        for spec in panel_specs:
            tabs.add_pane(TabPane(spec.tab_label, self._plugin_tab_content(spec)))
        setattr(tabs, "_plugin_tabs_loaded", True)

    def _plugin_tab_content(self, spec) -> object:
        if spec.build_tab is not None:
            return spec.build_tab(self)
        plugin_id, plugin, family = self._resolve_tui_plugin(spec)
        if plugin is None:
            return VerticalScroll(Static(f"Plugin not found: {plugin_id}", classes="field"))
        if family == "mutation":
            return self._build_mutation_plugin_tab(plugin)
        return self._build_default_plugin_tab(plugin)

    def _build_default_plugin_tab(self, plugin) -> object:
        children: list[object] = []
        for param_spec in getattr(plugin, "params_spec", ()):
            children.extend(self._build_plugin_param_widgets(plugin.id, param_spec))
        if not children:
            children.append(Static("This plugin has no configurable parameters.", classes="field"))
        children.extend(
            [
                Button(f"Run {plugin.label}", id=f"plugin-run-{plugin.id}", variant="success", classes="plugin-run"),
                Static("", id=f"plugin-{plugin.id}-status"),
            ]
        )
        return VerticalScroll(*children)

    def _build_mutation_plugin_tab(self, plugin) -> object:
        left_children: list[object] = [Static("Mutation plugin parameters", classes="field")]
        for param_spec in getattr(plugin, "params_spec", ()):
            left_children.extend(self._build_plugin_param_widgets(plugin.id, param_spec))
        if len(left_children) == 1:
            left_children.append(Static("This mutation plugin has no configurable parameters.", classes="field"))
        left_children.extend(
            [
                Button(f"Run {plugin.label}", id=f"plugin-run-{plugin.id}", variant="success", classes="plugin-run"),
                Static("", id=f"plugin-{plugin.id}-status"),
            ]
        )
        right_children = [
            Static("What will happen", classes="field"),
            Static("", id=f"plugin-{plugin.id}-help", classes="field"),
        ]
        return Horizontal(
            VerticalScroll(*left_children),
            VerticalScroll(*right_children),
            classes="row",
        )

    def _build_plugin_param_widgets(self, plugin_id: str, spec: PluginParamSpec) -> list[object]:
        input_id = f"plugin-{plugin_id}-{spec.name.replace('_', '-')}"
        default_text = "" if spec.default is None else str(spec.default)
        label = spec.label + (" *" if spec.required else "")
        widgets: list[object] = [Static(label, classes="field")]
        if spec.type == "choice" and spec.choices:
            widgets.append(
                Select(
                    [(choice, choice) for choice in spec.choices],
                    value=default_text or spec.choices[0],
                    id=input_id,
                )
            )
        else:
            widgets.append(Input(value=default_text, id=input_id))
        if spec.help:
            widgets.append(Static(spec.help, classes="field"))
        return widgets

    def _refresh_mutation_plugin_help(self) -> None:
        load_mutation_plugins(debug=False)
        for plugin in all_mutation_plugins():
            self._update_mutation_plugin_help(plugin.id, plugin)

    def _update_mutation_plugin_help(self, plugin_id: str, plugin=None) -> None:
        if plugin is None:
            load_mutation_plugins(debug=False)
            plugin = get_mutation_plugin(plugin_id)
        if plugin is None:
            return
        try:
            help_widget = self.query_one(f"#plugin-{plugin_id}-help", Static)
        except QUERY_ERRORS:
            return
        help_widget.update(self._mutation_plugin_help_text(plugin))

    def _mutation_plugin_help_text(self, plugin) -> str:
        if plugin.id == "insert_appn":
            return self._insert_appn_plugin_help_text(plugin)
        strategy = self._select_value("#mutation-apply", default="independent")
        repeats = self._input_value("#repeats", default="1") or "1"
        step = self._input_value("#step", default="1") or "1"
        sample = self._plugin_param_value_by_name(plugin.id, "sample")
        seed = self._plugin_param_value_by_name(plugin.id, "seed")
        lines = [f"{plugin.label} writes mutated JPEG outputs through the mutation-plugin pipeline."]
        if sample:
            lines.append(f"Sample size: {sample}.")
        if seed:
            lines.append(f"Seed: {seed}.")
        lines.append(self._describe_mutation_strategy(strategy, repeats, step))
        if strategy == "independent":
            lines.append("Each output starts from the original JPEG and applies this plugin's mutation rule to one sampled step/set.")
        elif strategy == "cumulative":
            lines.append("Later outputs keep earlier plugin-applied mutations and add the next sampled group.")
        else:
            lines.append("Later outputs keep earlier plugin-applied mutations and advance through contiguous mutable bytes.")
        lines.append(f"Outputs are written under {self._input_value('#output-dir', default='mutations') or 'mutations'}.")
        return "\n\n".join(lines)

    def _insert_appn_plugin_help_text(self, plugin) -> str:
        appn = self._plugin_param_value_by_name(plugin.id, "appn") or "15"
        output_dir = self._input_value("#output-dir", default="mutations") or "mutations"
        appn_label = appn
        try:
            appn_label = f"{int(appn):02d}"
        except ValueError:
            pass
        lines = [f"{plugin.label} writes one segment-level JPEG output through the mutation-plugin pipeline."]
        lines.append(f"It inserts one APP{appn_label} segment near the start of the file, after existing APPn markers.")
        lines.append("Provide exactly one payload source: payload hex or payload file. Identifier is an optional ASCII prefix.")
        lines.append(f"If no explicit output path is provided, the file is written under {output_dir}.")
        return "\n\n".join(lines)

    def _plugin_param_value_by_name(self, plugin_id: str, name: str) -> str:
        selector = f"#plugin-{plugin_id}-{name.replace('_', '-')}"
        return self._input_value(selector)

    def _plugin_id_from_widget_id(self, widget_id: str) -> str | None:
        if not widget_id.startswith("plugin-"):
            return None
        suffixes = ("-status", "-help")
        for suffix in suffixes:
            if widget_id.endswith(suffix):
                return widget_id[len("plugin-"):-len(suffix)]
        for plugin in all_mutation_plugins():
            prefix = f"plugin-{plugin.id}-"
            if widget_id.startswith(prefix):
                return plugin.id
        return None

    def _plugin_info_id_from_button_id(self, button_id: str) -> str | None:
        if not button_id.startswith("plugin-info-"):
            return None
        body = button_id.replace("plugin-info-", "", 1)
        plugin_id, _sep, _render = body.rpartition("-")
        return plugin_id or None

    def _append_list_view_item(self, list_view: object, item: ListItem) -> None:
        append = getattr(list_view, "append", None)
        if callable(append):
            append(item)
            return
        add_item = getattr(list_view, "add_item", None)
        if callable(add_item):
            add_item(item)
            return
        raise AttributeError("List view does not support append or add_item")

    @on(DirectoryTree.FileSelected)
    def _on_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        """
        Update the input path when a file is selected in the tree.
        """
        suffix = event.path.suffix.lower()
        if suffix not in {".jpg", ".jpeg"}:
            return
        self._set_input_path_value(str(event.path))

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
        path = str(Path(self.current_dir) / filename)
        self._set_input_path_value(path)
        self._mark_app0_dirty(False)

    @on(Input.Changed, "#input-path")
    def _on_input_path_changed(self, event: Input.Changed) -> None:
        if self._suppress_input_path_changed:
            return
        path = event.input.value.strip()
        self._load_selected_input_path(path)

    def _set_input_path_value(self, path: str) -> None:
        input_widget = self.query_one("#input-path", Input)
        if input_widget.value == path:
            self._load_selected_input_path(path)
            return
        self._suppress_input_path_changed = True
        try:
            input_widget.value = path
        finally:
            self._suppress_input_path_changed = False
        self._load_selected_input_path(path)

    def _load_selected_input_path(self, path: str) -> None:
        path = path.strip()
        if not path or path == self.preview_path:
            return
        input_file = Path(path)
        if not input_file.exists():
            return
        if input_file.suffix.lower() not in {".jpg", ".jpeg"}:
            return
        self._update_input_preview(path)
        self._pending_input_load_token += 1
        token = self._pending_input_load_token
        self.call_after_refresh(self._finish_selected_input_load, path, token)

    def _finish_selected_input_load(self, path: str, token: int) -> None:
        if token != self._pending_input_load_token:
            return
        current_path = self._input_value("#input-path")
        if current_path.strip() != path.strip():
            return
        self._auto_load_info()
        self._refresh_plugins_list()

    @on(ListView.Selected)
    def _on_menu_selected(self, event: ListView.Selected) -> None:
        item_id = event.item.id or ""
        if item_id == "menu-input":
            self._show_panel("input")
        elif item_id == "menu-info":
            self._show_panel("info")
        elif item_id == "menu-mutation":
            self._show_panel("mutation")
        elif item_id == "menu-outputs":
            self._show_panel("outputs")
        elif item_id == "menu-plugins":
            self._show_panel("plugins")
        elif item_id.startswith("menu-plugin-"):
            panel_id = item_id.replace("menu-plugin-", "", 1)
            self._show_panel(f"plugin-{panel_id}")

    def _show_panel(self, name: str) -> None:
        self.current_panel = name
        self.query_one("#panel-input").display = name == "input"
        self.query_one("#panel-info").display = name == "info"
        self.query_one("#panel-mutation").display = name == "mutation"
        self.query_one("#panel-outputs").display = name == "outputs"
        self.query_one("#panel-plugins").display = name == "plugins"
        for panel_id, panel in self.plugin_panels.items():
            panel.display = name == f"plugin-{panel_id}"

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
        self._add_sos_tab()
        self._add_entropy_trace_tab()

    def _add_info_tabs(self) -> None:
        tabs = self.query_one("#info-tabs", TabbedContent)
        tabs.add_pane(TabPane("General", RichLog(id="info-general", highlight=True)))
        tabs.add_pane(TabPane("Segments", RichLog(id="info-segments", highlight=True)))
        tabs.add_pane(TabPane("Details", RichLog(id="info-details", highlight=True)))
        tabs.add_pane(TabPane("Hex", self._build_full_hex_pane()))

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

        mutate_value = self.query_one("#mutate-mode", Select).value
        mutate = "" if mutate_value is None else str(mutate_value).strip()
        if mutate == "bitflip":
            bits = self.query_one("#mutate-bitflip-bits", Input).value.strip() or "0,2,7"
            mutate = f"bitflip:{bits}"
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
        analysis = self._selected_plugins_csv()

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
            analysis=analysis,
            analysis_params=[],
            mutation_plugins="",
            mutation_plugin_params=[],
            wave_chart=None,
            sliding_wave_chart=None,
            wave_window=256,
            dc_heatmap=None,
            ac_energy_heatmap=None,
            debug=debug,
        )

    def _refresh_plugins_list(self) -> None:
        try:
            list_container = self.query_one("#plugins-list", Vertical)
            fmt_label = self.query_one("#plugins-format", Static)
            input_path = self.query_one("#input-path", Input).value.strip()
        except QUERY_ERRORS:
            return
        for child in list(list_container.children):
            child.remove()
        load_plugins(debug=False)
        fmt = "unknown"
        if input_path and Path(input_path).exists():
            try:
                fmt = detect_format(input_path)
            except Exception:
                fmt = "unknown"
        fmt_label.update(f"Detected format: {fmt}")
        plugins = sorted(list(all_plugins()), key=lambda p: p.id)
        self.plugin_ids = [plugin.id for plugin in plugins]
        self.plugins_render_counter += 1
        render_id = self.plugins_render_counter
        self.plugin_button_ids = {}
        if not plugins:
            list_container.mount(Static("No plugins registered.", classes="field"))
            try:
                self.query_one("#plugins-help", Static).update("No analysis plugins registered.")
            except QUERY_ERRORS:
                pass
            return
        for plugin in plugins:
            formats = ", ".join(sorted(plugin.supported_formats))
            prefix = "[on]" if fmt in plugin.supported_formats else "[off]"
            label = f"{prefix} {plugin.id}: {plugin.label} (formats: {formats})"
            button = Button(label, id=f"plugin-info-{plugin.id}-{render_id}", classes="plugin-info")
            list_container.mount(button)
            self.plugin_button_ids[plugin.id] = button.id
        self.selected_plugin_info_id = plugins[0].id
        self._update_analysis_plugin_help(plugins[0].id, plugins[0], fmt)
        self._refresh_mutation_help()

    def _selected_plugins_csv(self) -> str:
        return ""

    def _analysis_plugin_help_text(self, plugin, fmt: str) -> str:
        lines = [f"{plugin.label} (`{plugin.id}`)"]
        formats = ", ".join(sorted(plugin.supported_formats))
        lines.append(f"Supported formats: {formats}")
        lines.append(f"Detected format supported: {'yes' if fmt in plugin.supported_formats else 'no'}")
        needs = ", ".join(sorted(getattr(plugin, "needs", ()) or ())) or "none"
        lines.append(f"Host-provided needs: {needs}")
        requires_mutations = getattr(plugin, "requires_mutations", False)
        lines.append(f"Requires generated mutation outputs: {'yes' if requires_mutations else 'no'}")
        specs = tuple(getattr(plugin, "params_spec", ()) or ())
        if not specs:
            lines.append("Params: none")
            return "\n".join(lines)
        lines.append("Params:")
        for spec in specs:
            required = "required" if spec.required else "optional"
            default = "" if spec.default is None else f", default={spec.default}"
            desc = f"- {spec.name} ({spec.type}, {required}{default})"
            if spec.help:
                desc += f": {spec.help}"
            lines.append(desc)
        return "\n".join(lines)

    def _update_analysis_plugin_help(self, plugin_id: str, plugin=None, fmt: str | None = None) -> None:
        if plugin is None:
            load_plugins(debug=False)
            plugin = get_plugin(plugin_id)
        if plugin is None:
            return
        if fmt is None:
            input_path = self._input_value("#input-path")
            fmt = "unknown"
            if input_path and Path(input_path).exists():
                try:
                    fmt = detect_format(input_path)
                except Exception:
                    fmt = "unknown"
        try:
            help_widget = self.query_one("#plugins-help", Static)
        except QUERY_ERRORS:
            return
        help_widget.update(self._analysis_plugin_help_text(plugin, fmt))

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
        except QUERY_ERRORS:
            return

    def _length_from_ui_hex(
        self,
        *,
        manual_length_id: str,
        length_id: str,
        payload: bytes,
        example: str,
    ) -> int:
        try:
            manual = self.query_one(f"#{manual_length_id}", Checkbox).value
        except QUERY_ERRORS:
            return len(payload) + 2
        if not manual:
            return len(payload) + 2
        try:
            text = self.query_one(f"#{length_id}", Input).value.strip()
        except QUERY_ERRORS:
            return len(payload) + 2
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
        manual_length_id: Optional[str] = None,
    ) -> None:
        try:
            log = self.query_one(f"#{log_id}", RichLog)
        except QUERY_ERRORS:
            return
        log.write(f"Saved edited file: {out_path}")
        if (
            manual_length_id
            and self._checkbox_value(f"#{manual_length_id}")
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
        try:
            err = self.query_one(f"#{err_id}", Static)
        except QUERY_ERRORS:
            return
        try:
            payload = build_payload()
            length_field = length_from_ui(payload)
        except Exception as e:
            err.update(f"Error: {e}")
            return
        err.update("")
        set_preview(payload)
        offset, _, _, _ = segment_info
        try:
            render_views(offset, length_field, payload)
            mark_dirty(True)
        except QUERY_ERRORS:
            return

    def _sync_editor_for_mode(
        self,
        *,
        advanced_id: str,
        raw_id: str,
        serialize_struct: Callable[[], bytes],
        deserialize_payload: Callable[[bytes], None],
    ) -> None:
        try:
            adv = self.query_one(f"#{advanced_id}", Checkbox).value
        except QUERY_ERRORS:
            return
        if adv:
            payload = serialize_struct()
            try:
                self.query_one(f"#{raw_id}", TextArea).text = self._bytes_to_hex(payload)
            except QUERY_ERRORS:
                return
            return
        try:
            payload = self._parse_hex(self.query_one(f"#{raw_id}", TextArea).text)
        except QUERY_ERRORS:
            return
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
        try:
            adv = self.query_one(f"#{advanced_id}", Checkbox).value
        except QUERY_ERRORS:
            return
        if adv:
            payload = serialize_struct(key)
            try:
                self.query_one(f"#{raw_id}", TextArea).text = self._bytes_to_hex(payload)
            except QUERY_ERRORS:
                return
            return
        try:
            payload = self._parse_hex(self.query_one(f"#{raw_id}", TextArea).text)
        except QUERY_ERRORS:
            return
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
        recover_payload: Optional[Callable[[str, Exception], Tuple[bytes, Optional[str]]]] = None,
    ) -> None:
        if key not in segment_info:
            return
        try:
            err = self.query_one(f"#{err_id}", Static)
        except QUERY_ERRORS:
            return
        warning = ""
        try:
            payload = build_payload(key)
            length_field = length_from_ui(key, payload)
        except Exception as e:
            if recover_payload is None:
                err.update(f"Error: {e}")
                return
            try:
                payload, warning = recover_payload(key, e)
                length_field = length_from_ui(key, payload)
            except Exception:
                err.update(f"Error: {e}")
                return
        err.update(warning)
        set_preview(key, payload)
        offset, _, _, _ = segment_info[key]
        try:
            render_views(key, payload, offset, length_field)
            set_dirty(key, True)
        except QUERY_ERRORS:
            return

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
        self.info_entropy_ranges = entropy_ranges
        self.entropy_trace_loaded = False
        self.entropy_trace_pending = False
        self.hex_page = 0
        self._info_rebuild_serial += 1
        self._entropy_trace_worker_serial = self._info_rebuild_serial

        general, segments_log, details_log = self._info_logs()
        self._clear_info_logs(general, segments_log, details_log)
        sof_targets = self._reset_sof_tabs(segments)
        appn_targets = self._reset_appn_tabs(segments)
        dqt_targets = self._reset_dqt_tabs(segments)
        dht_targets = self._reset_dht_tabs(segments)
        sos_targets = self._reset_sos_tabs(segments)
        self._reset_entropy_trace_tabs(None)
        self._set_entropy_trace_status("Click Load Trace to decode entropy.")
        self._set_entropy_trace_load_button(disabled=False, label="Load Trace")
        self._write_general(general, input_path, data, segments, entropy_ranges)
        self._write_segments(segments_log, segments, entropy_ranges, data)
        self._write_details(details_log, segments, data)
        self.call_after_refresh(
            self._render_info_detail_tabs,
            data,
            segments,
            sof_targets,
            appn_targets,
            dqt_targets,
            dht_targets,
            sos_targets,
        )

    def _dynamic_pane_id(self, base: str) -> str:
        return f"{base}-{self._info_rebuild_serial}"

    def _render_info_detail_tabs(self, data: bytes, segments, sof_targets, appn_targets, dqt_targets, dht_targets, sos_targets) -> None:
        try:
            self._render_app0_segment(data, segments)
        except Exception:
            # APP0 pane not present.
            pass
        self._render_sof_segments(data, sof_targets)
        self.call_after_refresh(self._render_sof_segments, data, sof_targets)
        try:
            self._render_dri_segment(data, segments)
        except Exception:
            pass
        self._render_appn_segments(data, appn_targets)
        self._render_dqt_segments(data, dqt_targets)
        self._render_dht_segments(data, dht_targets)
        self._render_sos_segments(data, sos_targets)
        self._render_full_hex_page()
        self._mark_app0_dirty(False)

    def _start_entropy_trace_worker(self, data: bytes, segments, entropy_ranges, serial: int) -> None:
        self.entropy_trace_pending = True

        def _run():
            for chunk in stream_entropy_scans(data, segments, entropy_ranges, chunk_mcus=256):
                self.call_from_thread(self._apply_entropy_trace_chunk, serial, chunk)
            return serial

        self.run_worker(
            _run,
            exclusive=True,
            name=f"entropy-trace-{serial}",
            group="entropy-trace",
            thread=True,
        )

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
        unused = self._unused_segment_names(segments)
        if unused:
            log.write("")
            log.write(Text("Unused sections:", style="grey50"))
            for line in self._format_unused_segment_lines(unused):
                log.write(Text(f"  {line}", style="grey50"))
        log.write("")
        log.write(Text("Entropy-Coded Data Ranges:", style="grey50"))
        if entropy_ranges:
            for r in entropy_ranges:
                log.write(
                    f"  Scan {r.scan_index}: 0x{r.start:08X}..0x{r.end:08X} ({r.end - r.start} bytes)"
                )
        else:
            log.write("  No entropy-coded data ranges found.")

    def _unused_segment_names(self, segments) -> list[str]:
        present = {seg.name for seg in segments}
        known = [MARKER_NAMES[marker] for marker in sorted(MARKER_NAMES)]
        return [name for name in known if name not in present]

    def _format_unused_segment_lines(self, names: list[str]) -> list[str]:
        families = ("APP", "SOF", "JPG")
        grouped: list[str] = []
        singles: list[str] = []
        i = 0
        while i < len(names):
            name = names[i]
            family = next((prefix for prefix in families if name.startswith(prefix) and name[len(prefix):].isdigit()), None)
            if family is None:
                singles.append(name)
                i += 1
                continue
            run = [name]
            j = i + 1
            while j < len(names):
                nxt = names[j]
                if nxt.startswith(family) and nxt[len(family):].isdigit():
                    run.append(nxt)
                    j += 1
                    continue
                break
            grouped.append(", ".join(run))
            i = j
        return grouped + singles

    def _write_details(self, log: RichLog, segments, data: bytes) -> None:
        for idx, seg in enumerate(segments):
            log.write(f"{idx:03d} {seg.name}")
            for line in explain_segment(seg, data):
                log.write(f"  {line}")

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
        for start, end, style in reversed(ranges):
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

    @on(Button.Pressed, ".plugin-run")
    def _on_plugin_run_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if not button_id.startswith("plugin-run-"):
            return
        plugin_id = button_id.replace("plugin-run-", "", 1)
        self._run_plugin(plugin_id)

    @on(Button.Pressed, ".plugin-info")
    def _on_plugin_info_pressed(self, event: Button.Pressed) -> None:
        plugin_id = self._plugin_info_id_from_button_id(event.button.id or "")
        if not plugin_id:
            return
        self.selected_plugin_info_id = plugin_id
        self._update_analysis_plugin_help(plugin_id)

    def _plugin_status(self, plugin_id: str, message: str) -> None:
        try:
            status = self.query_one(f"#plugin-{plugin_id}-status", Static)
        except QUERY_ERRORS:
            return
        status.update(message)

    def _run_plugin(self, plugin_id: str) -> None:
        try:
            input_path = self.query_one("#input-path", Input).value.strip()
            output_dir = self.query_one("#output-dir", Input).value.strip() or "mutations"
            debug = self.query_one("#debug", Checkbox).value
        except QUERY_ERRORS:
            return
        if not input_path:
            self._plugin_status(plugin_id, "Input path is required.")
            return
        if not Path(input_path).exists():
            self._plugin_status(plugin_id, f"Input path not found: {input_path}")
            return
        load_plugins(debug=debug)
        load_mutation_plugins(debug=debug)
        plugin, family = self._resolve_plugin_by_id(plugin_id)
        if plugin is None:
            self._plugin_status(plugin_id, f"Plugin not found: {plugin_id}")
            return
        try:
            fmt = detect_format(input_path)
        except Exception:
            fmt = "unknown"
        if fmt not in plugin.supported_formats:
            self._plugin_status(plugin_id, f"Unsupported format: {fmt}")
            return
        params: dict[str, str] = {}
        for spec in getattr(plugin, "params_spec", ()):
            raw_value = self._plugin_param_input_value(plugin_id, spec)
            if raw_value is not None:
                params[spec.name] = raw_value
        try:
            params = validate_plugin_params(plugin, params)
        except ValueError as exc:
            self._plugin_status(plugin_id, f"Error: {exc}")
            return
        self._plugin_status(plugin_id, "Running...")

        def _run() -> None:
            try:
                data = Path(input_path).read_bytes()
                segments, entropy_ranges = parse_jpeg(data) if fmt == "jpeg" else ([], [])
                if family == "mutation":
                    context = build_mutation_context(
                        plugin=plugin,
                        input_path=input_path,
                        fmt=fmt,
                        output_dir=output_dir,
                        debug=debug,
                        mutation_apply=self._select_value("#mutation-apply", default="independent"),
                        repeats=int(self._input_value("#repeats", default="1") or "1"),
                        step=int(self._input_value("#step", default="1") or "1"),
                        params=params,
                        data=data,
                        segments=segments,
                        entropy_ranges=entropy_ranges,
                    )
                else:
                    context = build_analysis_context(
                        plugin=plugin,
                        input_path=input_path,
                        fmt=fmt,
                        output_dir=output_dir,
                        debug=debug,
                        params=params,
                        data=data,
                        segments=segments,
                        entropy_ranges=entropy_ranges,
                        mutation_paths=[],
                    )
                result = plugin.run(input_path, context)
            except Exception as exc:
                debug_log(debug, f"TUI plugin run failed for {plugin_id}: {type(exc).__name__}: {exc}")
                self.call_from_thread(self._plugin_status, plugin_id, f"Error: {exc}")
                return
            count = len(result.outputs)
            self.call_from_thread(self._plugin_status, plugin_id, f"Done: {count} output(s)")

        self.run_worker(_run, exclusive=True, name=f"plugin-{plugin_id}", group="plugin", thread=True)

    def _plugin_param_input_value(self, plugin_id: str, spec: PluginParamSpec) -> Optional[str]:
        candidates = [
            f"#plugin-{plugin_id}-{spec.name}",
            f"#plugin-{plugin_id}-{spec.name.replace('_', '-')}",
        ]
        if spec.name == "out_path":
            candidates.append(f"#plugin-{plugin_id}-out")
        for selector in candidates:
            try:
                widget = self.query_one(selector, Input)
                return widget.value.strip()
            except Exception:
                pass
            try:
                select = self.query_one(selector, Select)
                value = select.value
                return "" if value is None else str(value).strip()
            except Exception:
                continue
        return None

    def _resolve_tui_plugin(self, spec) -> tuple[str, object | None, str]:
        plugin_id = spec.analysis_plugin_id or spec.mutation_plugin_id or spec.id
        if spec.mutation_plugin_id:
            return plugin_id, get_mutation_plugin(plugin_id), "mutation"
        return plugin_id, get_plugin(plugin_id), "analysis"

    def _resolve_plugin_by_id(self, plugin_id: str) -> tuple[object | None, str]:
        plugin = get_plugin(plugin_id)
        if plugin is not None:
            return plugin, "analysis"
        plugin = get_mutation_plugin(plugin_id)
        if plugin is not None:
            return plugin, "mutation"
        return None, "analysis"

    @on(Worker.StateChanged)
    def _on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """
        Handle worker completion for the run pipeline.
        """
        if event.worker.name.startswith("entropy-trace-"):
            if event.state == WorkerState.ERROR:
                self.entropy_trace_pending = False
                self.entropy_trace_loaded = False
                self._set_entropy_trace_load_button(disabled=False, label="Load Trace")
                self._set_entropy_trace_status(f"Trace failed: {event.worker.error}")
                try:
                    self._reset_entropy_trace_tabs([])
                    log = self.query_one("#info-entropy-trace-empty", RichLog)
                    log.clear()
                    log.write(f"Entropy trace failed: {event.worker.error}")
                except Exception:
                    pass
                return
            if event.state != WorkerState.SUCCESS:
                return
            serial = event.worker.result
            if serial != self._entropy_trace_worker_serial:
                return
            self.entropy_trace_pending = False
            self.entropy_trace_loaded = True
            self._set_entropy_trace_load_button(disabled=False, label="Reload Trace")
            self._set_entropy_trace_status("Trace loaded.")
            return
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
        if result.plugin_results:
            for plugin_id, outputs in result.plugin_results.items():
                log.write(f"Plugin {plugin_id}: {len(outputs)} output(s)")
        if result.mutation_plugin_results:
            for plugin_id, outputs in result.mutation_plugin_results.items():
                log.write(f"Mutation plugin {plugin_id}: {len(outputs)} output(s)")
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

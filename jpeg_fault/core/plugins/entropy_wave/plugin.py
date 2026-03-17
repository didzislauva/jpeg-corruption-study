from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...analysis_registry import register
from ...analysis_types import AnalysisContext, AnalysisPlugin, AnalysisResult
from ...jpeg_parse import parse_jpeg
from ...tui_plugin_registry import register_tui_plugin
from ...tui_plugin_types import TuiPluginSpec
from textual.containers import VerticalScroll
from textual.widgets import Button, Input, Label, Static
from ...wave_analysis import write_wave_chart


@dataclass(frozen=True)
class EntropyWavePlugin(AnalysisPlugin):
    id: str = "entropy_wave"
    label: str = "Entropy Wave Chart"
    supported_formats: set[str] = frozenset({"jpeg"})
    requires_mutations: bool = False

    def run(self, input_path: str, context: AnalysisContext) -> AnalysisResult:
        params = context.params or {}
        out_dir = Path(context.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path_value = params.get("out_path")
        if out_path_value:
            out_path = Path(out_path_value)
            if out_path.is_dir() or str(out_path).endswith(("/", "\\")):
                out_path = out_path / (Path(input_path).stem + "_wave.png")
        else:
            out_path = out_dir / (Path(input_path).stem + "_wave.png")
        data = Path(input_path).read_bytes()
        _, entropy_ranges = parse_jpeg(data)
        write_wave_chart(data, entropy_ranges, str(out_path), debug=context.debug)
        return AnalysisResult(self.id, [str(out_path)])


plugin = EntropyWavePlugin()
register(plugin)


def _build_entropy_wave_tab(app) -> object:
    return VerticalScroll(
        Static("Entropy wave output path", classes="field"),
        Input(value="", id="plugin-entropy_wave-out"),
        Button(
            "Run Entropy Wave",
            id="plugin-run-entropy_wave",
            variant="success",
            classes="plugin-run",
        ),
        Static("", id="plugin-entropy_wave-status"),
    )


register_tui_plugin(
    TuiPluginSpec(
        id="entropy_wave",
        label="Entropy Wave Chart",
        panel_id="graphic-output",
        panel_label="Graphic Output",
        tab_label="Entropy Wave",
        build_tab=_build_entropy_wave_tab,
    )
)

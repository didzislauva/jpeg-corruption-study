from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...analysis_registry import register
from ...analysis_types import AnalysisContext, AnalysisPlugin, AnalysisResult, PluginParamSpec
from ...tui_plugin_registry import register_tui_plugin
from ...tui_plugin_types import TuiPluginSpec
from ...wave_analysis import write_wave_chart


@dataclass(frozen=True)
class EntropyWavePlugin(AnalysisPlugin):
    id: str = "entropy_wave"
    label: str = "Entropy Wave Chart"
    supported_formats: set[str] = frozenset({"jpeg"})
    requires_mutations: bool = False
    needs: frozenset[str] = frozenset({"source_bytes", "entropy_ranges"})
    params_spec: tuple[PluginParamSpec, ...] = (
        PluginParamSpec(
            name="out_path",
            label="Output path",
            type="path",
            required=False,
            help="Optional output file path for the generated wave chart.",
        ),
        PluginParamSpec(
            name="mode",
            label="Wave mode",
            type="choice",
            required=False,
            default="byte",
            choices=("byte", "bit", "both"),
            help="Choose which entropy stream view to render.",
        ),
        PluginParamSpec(
            name="csv_path",
            label="CSV output path",
            type="path",
            required=False,
            help="Optional CSV export path for the selected stream data.",
        ),
        PluginParamSpec(
            name="transform",
            label="Byte transform",
            type="choice",
            required=False,
            default="raw",
            choices=("raw", "diff1", "diff2"),
            help="Byte-stream transform. Supported only when mode=byte.",
        ),
    )

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
        mode = str(params.get("mode", "byte"))
        transform = str(params.get("transform", "raw"))
        csv_path = params.get("csv_path")
        data = context.source_bytes or Path(input_path).read_bytes()
        entropy_ranges = context.entropy_ranges or []
        write_wave_chart(
            data,
            entropy_ranges,
            str(out_path),
            debug=context.debug,
            mode=mode,
            transform=transform,
            csv_path=str(csv_path) if csv_path else None,
        )
        outputs = [str(out_path)]
        if csv_path:
            outputs.append(str(csv_path))
        return AnalysisResult(self.id, outputs, {"stream_len": len(data), "mode": mode, "transform": transform})


plugin = EntropyWavePlugin()
register(plugin)

register_tui_plugin(
    TuiPluginSpec(
        id="entropy_wave",
        label="Entropy Wave Chart",
        panel_id="graphic-output",
        panel_label="Graphic Output",
        tab_label="Entropy Wave",
        analysis_plugin_id="entropy_wave",
    )
)

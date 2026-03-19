from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...analysis_registry import register
from ...analysis_types import AnalysisContext, AnalysisPlugin, AnalysisResult, PluginParamSpec
from ...tui_plugin_registry import register_tui_plugin
from ...tui_plugin_types import TuiPluginSpec
from ...wave_analysis import write_sliding_wave_chart


@dataclass(frozen=True)
class SlidingWavePlugin(AnalysisPlugin):
    id: str = "sliding_wave"
    label: str = "Sliding Wave Chart"
    supported_formats: set[str] = frozenset({"jpeg"})
    requires_mutations: bool = False
    needs: frozenset[str] = frozenset({"source_bytes", "entropy_ranges"})
    params_spec: tuple[PluginParamSpec, ...] = (
        PluginParamSpec(name="out_path", label="Output path", type="path", help="Optional output image path."),
        PluginParamSpec(name="csv_path", label="CSV output path", type="path", help="Optional CSV export path."),
        PluginParamSpec(
            name="window",
            label="Window size",
            type="int",
            default=256,
            help="Sliding window size in bytes.",
        ),
        PluginParamSpec(
            name="stats",
            label="Stats",
            type="string",
            default="mean,variance,entropy",
            help="Comma-separated stats from mean,variance,std,entropy,min,max,range,energy.",
        ),
        PluginParamSpec(
            name="transform",
            label="Byte transform",
            type="choice",
            default="raw",
            choices=("raw", "diff1", "diff2"),
            help="Byte-stream transform applied before computing sliding stats.",
        ),
    )

    def run(self, input_path: str, context: AnalysisContext) -> AnalysisResult:
        params = context.params or {}
        out_dir = Path(context.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path_value = params.get("out_path")
        if out_path_value:
            out_path = Path(str(out_path_value))
            if out_path.is_dir() or str(out_path).endswith(("/", "\\")):
                out_path = out_path / (Path(input_path).stem + "_sliding_wave.png")
        else:
            out_path = out_dir / (Path(input_path).stem + "_sliding_wave.png")
        csv_path = params.get("csv_path")
        window = int(params.get("window", 256))
        stats_value = str(params.get("stats", "mean,variance,entropy"))
        stats = [part.strip() for part in stats_value.split(",") if part.strip()]
        transform = str(params.get("transform", "raw"))
        data = context.source_bytes or Path(input_path).read_bytes()
        entropy_ranges = context.entropy_ranges or []
        write_sliding_wave_chart(
            data,
            entropy_ranges,
            str(out_path),
            debug=context.debug,
            window=window,
            stats=stats,
            transform=transform,
            csv_path=str(csv_path) if csv_path else None,
        )
        outputs = [str(out_path)]
        if csv_path:
            outputs.append(str(csv_path))
        return AnalysisResult(self.id, outputs, {"stream_len": len(data), "window": window, "transform": transform})


plugin = SlidingWavePlugin()
register(plugin)

register_tui_plugin(
    TuiPluginSpec(
        id="sliding_wave",
        label="Sliding Wave Chart",
        panel_id="graphic-output",
        panel_label="Graphic Output",
        tab_label="Sliding Wave",
        analysis_plugin_id="sliding_wave",
    )
)

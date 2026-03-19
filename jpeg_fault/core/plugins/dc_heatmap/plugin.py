from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...analysis_registry import register
from ...analysis_types import AnalysisContext, AnalysisPlugin, AnalysisResult, PluginParamSpec
from .._shared.dct_heatmap import write_dc_heatmap
from ...tui_plugin_registry import register_tui_plugin
from ...tui_plugin_types import TuiPluginSpec


@dataclass(frozen=True)
class DcHeatmapPlugin(AnalysisPlugin):
    id: str = "dc_heatmap"
    label: str = "DC Heatmap"
    supported_formats: set[str] = frozenset({"jpeg"})
    requires_mutations: bool = False
    needs: frozenset[str] = frozenset()
    params_spec: tuple[PluginParamSpec, ...] = (
        PluginParamSpec(name="out_path", label="Output path", type="path", help="Optional output image path for the generated DC heatmap."),
        PluginParamSpec(name="cmap", label="Colormap", type="string", default="coolwarm", help="Matplotlib colormap name for the rendered heatmap."),
        PluginParamSpec(
            name="plane_mode",
            label="Plane mode",
            type="choice",
            default="bt601",
            choices=("bt601", "bt709", "average", "lightness", "max", "min", "red", "green", "blue"),
            help="Choose how RGB pixels are projected to the single-channel plane used for the block transform.",
        ),
        PluginParamSpec(name="block_size", label="Block size", type="int", default=8, help="Transform block size. 8 is JPEG-native; other values are exploratory."),
    )

    def run(self, input_path: str, context: AnalysisContext) -> AnalysisResult:
        params = context.params or {}
        cmap = str(params.get("cmap", "coolwarm"))
        plane_mode = str(params.get("plane_mode", "bt601"))
        block_size = int(params.get("block_size", 8))
        default_name = f"{Path(input_path).stem}_dc_heatmap_{plane_mode}_b{block_size}.png"
        out_path_value = params.get("out_path")
        if out_path_value:
            out_path = Path(str(out_path_value))
            if out_path.is_dir() or str(out_path).endswith(("/", "\\")):
                out_path = out_path / default_name
        else:
            out_path = Path.cwd() / default_name
        out_path.parent.mkdir(parents=True, exist_ok=True)
        block_rows, block_cols = write_dc_heatmap(
            input_path,
            str(out_path),
            context.debug,
            cmap=cmap,
            plane_mode=plane_mode,
            block_size=block_size,
        )
        return AnalysisResult(self.id, [str(out_path)], {"block_rows": block_rows, "block_cols": block_cols, "cmap": cmap, "plane_mode": plane_mode, "block_size": block_size})


plugin = DcHeatmapPlugin()
register(plugin)

register_tui_plugin(
    TuiPluginSpec(
        id="dc_heatmap",
        label="DC Heatmap",
        panel_id="graphic-output",
        panel_label="Graphic Output",
        tab_label="DC Heatmap",
        analysis_plugin_id="dc_heatmap",
    )
)

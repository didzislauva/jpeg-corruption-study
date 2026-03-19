from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ...analysis_registry import register
from ...analysis_types import AnalysisContext, AnalysisPlugin, AnalysisResult, PluginParamSpec
from ...entropy_trace import format_scan_trace_text, trace_entropy_scans


@dataclass(frozen=True)
class EntropyTracePlugin(AnalysisPlugin):
    id: str = "entropy_trace"
    label: str = "Entropy Trace"
    supported_formats: set[str] = frozenset({"jpeg"})
    requires_mutations: bool = False
    needs: frozenset[str] = frozenset({"source_bytes", "parsed_jpeg", "entropy_ranges"})
    params_spec: tuple[PluginParamSpec, ...] = (
        PluginParamSpec(
            name="out_path",
            label="Output path",
            type="path",
            required=False,
            help="Optional output path for the generated entropy trace artifact.",
        ),
        PluginParamSpec(
            name="format",
            label="Format",
            type="choice",
            required=False,
            default="text",
            choices=("text", "json"),
            help="Choose whether to write a human-readable text trace or JSON.",
        ),
    )

    def run(self, input_path: str, context: AnalysisContext) -> AnalysisResult:
        params = context.params or {}
        out_dir = Path(context.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        fmt = str(params.get("format", "text"))
        suffix = ".json" if fmt == "json" else ".txt"
        out_path_value = params.get("out_path")
        out_path = Path(out_path_value) if out_path_value else out_dir / f"{Path(input_path).stem}_entropy_trace{suffix}"

        data = context.source_bytes or Path(input_path).read_bytes()
        segments = context.segments or []
        entropy_ranges = context.entropy_ranges or []
        scans = trace_entropy_scans(data, segments, entropy_ranges)

        if fmt == "json":
            out_path.write_text(json.dumps([scan.to_dict() for scan in scans], indent=2) + "\n")
        else:
            out_path.write_text(format_scan_trace_text(scans))

        traced_blocks = sum(len(scan.blocks) for scan in scans)
        supported_scans = sum(1 for scan in scans if scan.supported)
        return AnalysisResult(
            self.id,
            [str(out_path)],
            {"scan_count": len(scans), "supported_scans": supported_scans, "block_count": traced_blocks, "format": fmt},
        )


plugin = EntropyTracePlugin()
register(plugin)

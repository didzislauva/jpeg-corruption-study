from __future__ import annotations

import json
from pathlib import Path

from jpeg_fault.core.analysis_registry import clear_registry_for_tests, get_plugin, load_plugins
from jpeg_fault.core.analysis_types import AnalysisContext
from jpeg_fault.core.jpeg_parse import parse_jpeg


def test_entropy_trace_plugin_runs_text(decodable_jpeg_path: Path) -> None:
    clear_registry_for_tests()
    load_plugins(force=True)
    plugin = get_plugin("entropy_trace")
    assert plugin is not None

    data = decodable_jpeg_path.read_bytes()
    segments, entropy_ranges = parse_jpeg(data)
    ctx = AnalysisContext(
        output_dir=str(decodable_jpeg_path.parent),
        params={"format": "text"},
        source_bytes=data,
        segments=segments,
        entropy_ranges=entropy_ranges,
    )

    result = plugin.run(str(decodable_jpeg_path), ctx)

    assert result.plugin_id == "entropy_trace"
    out_path = Path(result.outputs[0])
    assert out_path.exists()
    text = out_path.read_text()
    assert "Scan 0" in text
    assert "MCU 0 block 0 Y" in text


def test_entropy_trace_plugin_runs_json(decodable_jpeg_path: Path) -> None:
    clear_registry_for_tests()
    load_plugins(force=True)
    plugin = get_plugin("entropy_trace")
    assert plugin is not None

    data = decodable_jpeg_path.read_bytes()
    segments, entropy_ranges = parse_jpeg(data)
    out_path = decodable_jpeg_path.parent / "trace.json"
    ctx = AnalysisContext(
        output_dir=str(decodable_jpeg_path.parent),
        params={"format": "json", "out_path": str(out_path)},
        source_bytes=data,
        segments=segments,
        entropy_ranges=entropy_ranges,
    )

    result = plugin.run(str(decodable_jpeg_path), ctx)

    payload = json.loads(Path(result.outputs[0]).read_text())
    assert payload[0]["scan_index"] == 0
    assert payload[0]["blocks"][0]["component_name"] == "Y"

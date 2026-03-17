from __future__ import annotations

from pathlib import Path

from jpeg_fault.core.analysis_registry import clear_registry_for_tests, load_plugins, get_plugin
from jpeg_fault.core.analysis_types import AnalysisContext


def test_entropy_wave_plugin_runs(tmp_path: Path, monkeypatch) -> None:
    clear_registry_for_tests()
    load_plugins(force=True)
    plugin = get_plugin("entropy_wave")
    assert plugin is not None

    calls = {}

    def fake_write_wave_chart(data: bytes, entropy_ranges, out_path: str, debug: bool) -> int:
        calls["data_len"] = len(data)
        calls["ranges"] = entropy_ranges
        calls["out_path"] = out_path
        calls["debug"] = debug
        Path(out_path).write_bytes(b"fake")
        return 1

    import importlib

    entropy_wave_mod = importlib.import_module("jpeg_fault.core.plugins.entropy_wave.plugin")
    monkeypatch.setattr(entropy_wave_mod, "write_wave_chart", fake_write_wave_chart)

    input_path = tmp_path / "in.jpg"
    input_path.write_bytes(b"\xFF\xD8\xFF\xD9")
    ctx = AnalysisContext(output_dir=str(tmp_path), debug=True)
    result = plugin.run(str(input_path), ctx)

    assert result.plugin_id == "entropy_wave"
    assert result.outputs
    assert calls["data_len"] == len(input_path.read_bytes())
    assert calls["debug"] is True

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

    def fake_write_wave_chart(
        data: bytes,
        entropy_ranges,
        out_path: str,
        debug: bool,
        mode: str = "both",
        transform: str = "raw",
        csv_path: str | None = None,
    ) -> int:
        calls["data_len"] = len(data)
        calls["ranges"] = entropy_ranges
        calls["out_path"] = out_path
        calls["debug"] = debug
        calls["mode"] = mode
        calls["transform"] = transform
        calls["csv_path"] = csv_path
        Path(out_path).write_bytes(b"fake")
        if csv_path:
            Path(csv_path).write_text("x,y\n0,1\n")
        return 1

    import importlib

    entropy_wave_mod = importlib.import_module("jpeg_fault.core.plugins.entropy_wave.plugin")
    monkeypatch.setattr(entropy_wave_mod, "write_wave_chart", fake_write_wave_chart)

    input_path = tmp_path / "in.jpg"
    input_path.write_bytes(b"\xFF\xD8\xFF\xD9")
    ctx = AnalysisContext(
        output_dir=str(tmp_path),
        debug=True,
        params={"mode": "byte", "transform": "diff1", "csv_path": str(tmp_path / "wave.csv")},
    )
    result = plugin.run(str(input_path), ctx)

    assert result.plugin_id == "entropy_wave"
    assert result.outputs
    assert calls["data_len"] == len(input_path.read_bytes())
    assert calls["debug"] is True
    assert calls["mode"] == "byte"
    assert calls["transform"] == "diff1"
    assert str(calls["csv_path"]).endswith("wave.csv")

from __future__ import annotations

from pathlib import Path

from jpeg_fault.core.analysis_registry import clear_registry_for_tests, get_plugin, load_plugins
from jpeg_fault.core.analysis_types import AnalysisContext


def test_sliding_wave_plugin_runs(tmp_path: Path, monkeypatch) -> None:
    clear_registry_for_tests()
    load_plugins(force=True)
    plugin = get_plugin("sliding_wave")
    assert plugin is not None

    calls = {}

    def fake_write_sliding_wave_chart(
        data: bytes,
        entropy_ranges,
        out_path: str,
        window: int,
        debug: bool,
        stats=("mean", "variance", "entropy"),
        transform: str = "raw",
        csv_path: str | None = None,
    ) -> int:
        calls["data_len"] = len(data)
        calls["ranges"] = entropy_ranges
        calls["out_path"] = out_path
        calls["window"] = window
        calls["debug"] = debug
        calls["stats"] = list(stats)
        calls["transform"] = transform
        calls["csv_path"] = csv_path
        Path(out_path).write_bytes(b"fake")
        if csv_path:
            Path(csv_path).write_text("window_index,mean\n0,1\n")
        return 1

    import importlib

    sliding_wave_mod = importlib.import_module("jpeg_fault.core.plugins.sliding_wave.plugin")
    monkeypatch.setattr(sliding_wave_mod, "write_sliding_wave_chart", fake_write_sliding_wave_chart)

    input_path = tmp_path / "in.jpg"
    input_path.write_bytes(b"\xFF\xD8\xFF\xD9")
    ctx = AnalysisContext(
        output_dir=str(tmp_path),
        debug=True,
        params={
            "window": 128,
            "stats": "mean,max,energy",
            "transform": "diff2",
            "csv_path": str(tmp_path / "slide.csv"),
        },
    )
    result = plugin.run(str(input_path), ctx)

    assert result.plugin_id == "sliding_wave"
    assert len(result.outputs) == 2
    assert calls["data_len"] == len(input_path.read_bytes())
    assert calls["window"] == 128
    assert calls["stats"] == ["mean", "max", "energy"]
    assert calls["transform"] == "diff2"
    assert str(calls["csv_path"]).endswith("slide.csv")

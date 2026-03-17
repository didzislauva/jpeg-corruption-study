from __future__ import annotations

from pathlib import Path

from jpeg_fault.core.analysis_registry import clear_registry_for_tests, get_plugin, load_plugins
from jpeg_fault.core.analysis_types import AnalysisContext


def test_dc_heatmap_plugin_runs(tmp_path: Path, monkeypatch) -> None:
    clear_registry_for_tests()
    load_plugins(force=True)
    plugin = get_plugin("dc_heatmap")
    assert plugin is not None

    calls = {}

    def fake_write_dc_heatmap(
        input_path: str,
        out_path: str,
        debug: bool,
        cmap: str = "coolwarm",
        plane_mode: str = "bt601",
        block_size: int = 8,
    ) -> tuple[int, int]:
        calls["input_path"] = input_path
        calls["out_path"] = out_path
        calls["debug"] = debug
        calls["cmap"] = cmap
        calls["plane_mode"] = plane_mode
        calls["block_size"] = block_size
        Path(out_path).write_bytes(b"fake")
        return (5, 7)

    import importlib

    dc_heatmap_mod = importlib.import_module("jpeg_fault.core.plugins.dc_heatmap.plugin")
    monkeypatch.setattr(dc_heatmap_mod, "write_dc_heatmap", fake_write_dc_heatmap)

    input_path = tmp_path / "in.jpg"
    input_path.write_bytes(b"\xFF\xD8\xFF\xD9")
    ctx = AnalysisContext(
        output_dir=str(tmp_path),
        debug=True,
        params={
            "out_path": str(tmp_path / "custom.png"),
            "cmap": "viridis",
            "plane_mode": "green",
            "block_size": 16,
        },
    )
    result = plugin.run(str(input_path), ctx)

    assert result.plugin_id == "dc_heatmap"
    assert result.outputs
    assert calls["input_path"] == str(input_path)
    assert calls["debug"] is True
    assert calls["cmap"] == "viridis"
    assert calls["plane_mode"] == "green"
    assert calls["block_size"] == 16
    assert result.details == {
        "block_rows": 5,
        "block_cols": 7,
        "cmap": "viridis",
        "plane_mode": "green",
        "block_size": 16,
    }


def test_dc_heatmap_plugin_uses_descriptive_default_name(tmp_path: Path, monkeypatch) -> None:
    clear_registry_for_tests()
    load_plugins(force=True)
    plugin = get_plugin("dc_heatmap")
    assert plugin is not None

    calls = {}

    def fake_write_dc_heatmap(
        input_path: str,
        out_path: str,
        debug: bool,
        cmap: str = "coolwarm",
        plane_mode: str = "bt601",
        block_size: int = 8,
    ) -> tuple[int, int]:
        calls["out_path"] = out_path
        Path(out_path).write_bytes(b"fake")
        return (2, 3)

    import importlib

    dc_heatmap_mod = importlib.import_module("jpeg_fault.core.plugins.dc_heatmap.plugin")
    monkeypatch.setattr(dc_heatmap_mod, "write_dc_heatmap", fake_write_dc_heatmap)
    monkeypatch.chdir(tmp_path)

    input_path = tmp_path / "sample.jpg"
    input_path.write_bytes(b"\xFF\xD8\xFF\xD9")
    ctx = AnalysisContext(output_dir=str(tmp_path / "ignored"), debug=False, params={"plane_mode": "bt709", "block_size": 16})
    result = plugin.run(str(input_path), ctx)

    expected = tmp_path / "sample_dc_heatmap_bt709_b16.png"
    assert calls["out_path"] == str(expected)
    assert result.outputs == [str(expected)]

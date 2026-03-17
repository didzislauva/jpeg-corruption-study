from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from jpeg_fault.core import api
from jpeg_fault.core.analysis_registry import clear_registry_for_tests, register
from jpeg_fault.core.analysis_types import AnalysisContext, AnalysisResult, AnalysisPlugin


@dataclass(frozen=True)
class DummyPlugin(AnalysisPlugin):
    id: str
    label: str
    supported_formats: set[str]
    requires_mutations: bool = False

    def run(self, input_path: str, context: AnalysisContext) -> AnalysisResult:
        return AnalysisResult(self.id, [input_path])


def test_run_plugins_dispatch(tmp_path: Path) -> None:
    clear_registry_for_tests()
    register(DummyPlugin("dummy", "Dummy", {"jpeg"}))
    input_path = tmp_path / "in.jpg"
    input_path.write_bytes(b"\xFF\xD8\xFF\xD9")

    outputs = api._run_plugins(  # type: ignore[attr-defined]
        api.RunOptions(
            input_path=str(input_path),
            output_dir=str(tmp_path),
            mutate="add1",
            sample=1,
            seed=1,
            mutation_apply="independent",
            repeats=1,
            step=1,
            overflow_wrap=False,
            report_only=False,
            color="never",
            gif=None,
            gif_fps=10,
            gif_loop=0,
            gif_shuffle=False,
            ssim_chart=None,
            metrics="ssim",
            metrics_chart_prefix=None,
            jobs=None,
            analysis="dummy",
            wave_chart=None,
            sliding_wave_chart=None,
            wave_window=256,
            dc_heatmap=None,
            ac_energy_heatmap=None,
            debug=False,
        ),
        ["dummy"],
        0,
    )

    assert outputs["dummy"] == [str(input_path)]


def test_run_plugins_unsupported_format(tmp_path: Path) -> None:
    clear_registry_for_tests()
    register(DummyPlugin("dummy", "Dummy", {"png"}))
    input_path = tmp_path / "in.jpg"
    input_path.write_bytes(b"\xFF\xD8\xFF\xD9")

    with pytest.raises(ValueError, match="does not support format"):
        api._run_plugins(  # type: ignore[attr-defined]
            api.RunOptions(
                input_path=str(input_path),
                output_dir=str(tmp_path),
                mutate="add1",
                sample=1,
                seed=1,
                mutation_apply="independent",
                repeats=1,
                step=1,
                overflow_wrap=False,
                report_only=False,
                color="never",
                gif=None,
                gif_fps=10,
                gif_loop=0,
                gif_shuffle=False,
                ssim_chart=None,
                metrics="ssim",
                metrics_chart_prefix=None,
                jobs=None,
                analysis="dummy",
                wave_chart=None,
                sliding_wave_chart=None,
                wave_window=256,
                dc_heatmap=None,
                ac_energy_heatmap=None,
                debug=False,
            ),
            ["dummy"],
            0,
        )

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from jpeg_fault.core import api
from jpeg_fault.core.analysis_registry import clear_registry_for_tests, register
from jpeg_fault.core.analysis_types import AnalysisContext, AnalysisResult, AnalysisPlugin, PluginParamSpec
from jpeg_fault.core.mutation_registry import clear_registry_for_tests as clear_mutation_registry_for_tests, register as register_mutation
from jpeg_fault.core.mutation_types import MutationContext, MutationPlugin, MutationResult


@dataclass(frozen=True)
class DummyPlugin(AnalysisPlugin):
    id: str
    label: str
    supported_formats: set[str]
    requires_mutations: bool = False
    params_spec: tuple[PluginParamSpec, ...] = ()

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
            analysis_params=[],
            mutation_plugins="",
            mutation_plugin_params=[],
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
                analysis_params=[],
                mutation_plugins="",
                mutation_plugin_params=[],
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


def test_run_plugins_validates_analysis_params(tmp_path: Path) -> None:
    clear_registry_for_tests()

    @dataclass(frozen=True)
    class ParamPlugin(AnalysisPlugin):
        id: str
        label: str
        supported_formats: set[str]
        requires_mutations: bool = False
        params_spec: tuple[PluginParamSpec, ...] = (
            PluginParamSpec(name="window", label="Window", type="int", required=True),
        )

        def run(self, input_path: str, context: AnalysisContext) -> AnalysisResult:
            return AnalysisResult(self.id, [str(context.params["window"])])

    register(ParamPlugin("dummy", "Dummy", {"jpeg"}))
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
            analysis_params=["dummy.window=512"],
            mutation_plugins="",
            mutation_plugin_params=[],
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

    assert outputs["dummy"] == ["512"]


def test_run_plugins_rejects_bad_analysis_param(tmp_path: Path) -> None:
    clear_registry_for_tests()
    register(DummyPlugin("dummy", "Dummy", {"jpeg"}))
    input_path = tmp_path / "in.jpg"
    input_path.write_bytes(b"\xFF\xD8\xFF\xD9")

    with pytest.raises(ValueError, match="unselected plugin|does not accept params"):
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
                analysis_params=["dummy.window=512"],
                mutation_plugins="",
                mutation_plugin_params=[],
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


def test_run_plugins_provide_requested_context(tmp_path: Path) -> None:
    clear_registry_for_tests()

    @dataclass(frozen=True)
    class NeedsPlugin(AnalysisPlugin):
        id: str
        label: str
        supported_formats: set[str]
        requires_mutations: bool = False
        params_spec: tuple[PluginParamSpec, ...] = ()
        needs: frozenset[str] = frozenset({"source_bytes", "parsed_jpeg", "entropy_ranges"})

        def run(self, input_path: str, context: AnalysisContext) -> AnalysisResult:
            assert context.input_path == input_path
            assert context.format == "jpeg"
            assert context.source_bytes is not None
            assert context.segments is not None
            assert context.entropy_ranges is not None
            return AnalysisResult(self.id, [str(len(context.source_bytes))])

    register(NeedsPlugin("dummy", "Dummy", {"jpeg"}))
    input_path = tmp_path / "in.jpg"
    input_path.write_bytes(b"\xFF\xD8\xFF\xD9")
    data = input_path.read_bytes()
    segments, entropy_ranges = api.parse_jpeg(data)  # type: ignore[attr-defined]

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
            analysis_params=[],
            mutation_plugins="",
            mutation_plugin_params=[],
            wave_chart=None,
            sliding_wave_chart=None,
            wave_window=256,
            dc_heatmap=None,
            ac_energy_heatmap=None,
            debug=False,
        ),
        ["dummy"],
        0,
        data,
        segments,
        entropy_ranges,
        [],
    )

    assert outputs["dummy"] == [str(len(data))]


def test_run_dc_heatmap_phase_dispatches_via_plugin(tmp_path: Path, monkeypatch) -> None:
    input_path = tmp_path / "in.jpg"
    input_path.write_bytes(b"\xFF\xD8\xFF\xD9")

    captured = {}

    def fake_run_analysis_plugin(**kwargs):
        captured.update(kwargs)
        return AnalysisResult("dc_heatmap", [str(tmp_path / "dc.png")], {"block_rows": 4, "block_cols": 6})

    monkeypatch.setattr(api, "_run_analysis_plugin", fake_run_analysis_plugin)

    result = api.run_dc_heatmap_phase(
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
            analysis="",
            analysis_params=[],
            mutation_plugins="",
            mutation_plugin_params=[],
            wave_chart=None,
            sliding_wave_chart=None,
            wave_window=256,
            dc_heatmap=str(tmp_path / "dc.png"),
            ac_energy_heatmap=None,
            debug=False,
        )
    )

    assert result == (4, 6)
    assert captured["plugin_id"] == "dc_heatmap"
    assert captured["raw_param_map"] == {"dc_heatmap": {"out_path": str(tmp_path / "dc.png")}}


def test_run_ac_heatmap_phase_dispatches_via_plugin(tmp_path: Path, monkeypatch) -> None:
    input_path = tmp_path / "in.jpg"
    input_path.write_bytes(b"\xFF\xD8\xFF\xD9")

    captured = {}

    def fake_run_analysis_plugin(**kwargs):
        captured.update(kwargs)
        return AnalysisResult("ac_energy_heatmap", [str(tmp_path / "ac.png")], {"block_rows": 3, "block_cols": 5})

    monkeypatch.setattr(api, "_run_analysis_plugin", fake_run_analysis_plugin)

    result = api.run_ac_heatmap_phase(
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
            analysis="",
            analysis_params=[],
            mutation_plugins="",
            mutation_plugin_params=[],
            wave_chart=None,
            sliding_wave_chart=None,
            wave_window=256,
            dc_heatmap=None,
            ac_energy_heatmap=str(tmp_path / "ac.png"),
            debug=False,
        )
    )

    assert result == (3, 5)
    assert captured["plugin_id"] == "ac_energy_heatmap"
    assert captured["raw_param_map"] == {"ac_energy_heatmap": {"out_path": str(tmp_path / "ac.png")}}


def test_run_mutation_plugins_dispatch(tmp_path: Path) -> None:
    clear_mutation_registry_for_tests()

    @dataclass(frozen=True)
    class DummyMutationPlugin(MutationPlugin):
        id: str
        label: str
        supported_formats: set[str]
        params_spec: tuple[PluginParamSpec, ...] = (
            PluginParamSpec(name="suffix", label="Suffix", type="string", default="mut"),
        )
        needs: frozenset[str] = frozenset({"source_bytes", "parsed_jpeg", "entropy_ranges"})

        def run(self, input_path: str, context: MutationContext) -> MutationResult:
            assert context.source_bytes is not None
            assert context.segments is not None
            assert context.entropy_ranges is not None
            out_path = Path(context.output_dir) / f"{Path(input_path).stem}_{context.params['suffix']}.jpg"
            out_path.write_bytes(context.source_bytes)
            return MutationResult(self.id, [str(out_path)])

    register_mutation(DummyMutationPlugin("dummy_mut", "DummyMut", {"jpeg"}))
    input_path = tmp_path / "in.jpg"
    input_path.write_bytes(b"\xFF\xD8\xFF\xD9")
    data = input_path.read_bytes()
    segments, entropy_ranges = api.parse_jpeg(data)  # type: ignore[attr-defined]

    outputs = api._run_mutation_plugins(  # type: ignore[attr-defined]
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
            analysis="",
            analysis_params=[],
            mutation_plugins="dummy_mut",
            mutation_plugin_params=["dummy_mut.suffix=alt"],
            wave_chart=None,
            sliding_wave_chart=None,
            wave_window=256,
            dc_heatmap=None,
            ac_energy_heatmap=None,
            debug=False,
        ),
        ["dummy_mut"],
        data,
        segments,
        entropy_ranges,
    )

    assert outputs["dummy_mut"] == [str(tmp_path / "in_alt.jpg")]

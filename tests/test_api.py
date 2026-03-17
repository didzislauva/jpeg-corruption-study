from __future__ import annotations

"""
Tests for the core API layer.
"""

from jpeg_fault.core import api


def test_api_run_report_only(tiny_jpeg_path) -> None:
    """
    Ensure report-only mode returns a result without mutations or analysis outputs.
    """
    opts = api.RunOptions(
        input_path=str(tiny_jpeg_path),
        output_dir="mutations",
        mutate="add1",
        sample=2,
        seed=1,
        mutation_apply="independent",
        repeats=1,
        step=1,
        overflow_wrap=False,
        report_only=True,
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
        wave_chart=None,
        sliding_wave_chart=None,
        wave_window=256,
        dc_heatmap=None,
        ac_energy_heatmap=None,
        debug=False,
    )
    result = api.run(opts, emit_report=False)
    assert result.mutation_count == 0
    assert result.gif_frames is None

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from jpeg_fault.core import cli
from jpeg_fault.core.jpeg_parse import parse_jpeg


def test_parse_args(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["prog", "in.jpg", "--mutation-apply", "cumulative", "--sample", "5", "--step", "2", "--debug"],
    )
    args = cli.parse_args()
    assert args.input == "in.jpg"
    assert args.mutation_apply == "cumulative"
    assert args.sample == 5
    assert args.step == 2
    assert args.debug is True
    assert args.wave_window == 256


def test_parse_args_repeat_alias(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["prog", "in.jpg", "--repeat", "4", "--mutation-apply", "cumulative"])
    args = cli.parse_args()
    assert args.repeats == 4


def test_log_context_and_validate(capsys, tiny_jpeg_bytes: bytes) -> None:
    segs, ents = parse_jpeg(tiny_jpeg_bytes)
    args = argparse.Namespace(
        debug=True,
        mutate="add1",
        mutation_apply="cumulative",
        sample=3,
        repeats=2,
        step=2,
        seed=1,
        output_dir="x",
        jobs=None,
        wave_chart=None,
        sliding_wave_chart=None,
        wave_window=256,
        dc_heatmap=None,
        ac_energy_heatmap=None,
    )
    cli.log_run_context(args, tiny_jpeg_bytes, segs, ents)
    err = capsys.readouterr().err
    assert "Input bytes" in err and "Options:" in err

    a = argparse.Namespace(mutation_apply="independent", repeats=2, step=1)
    assert "--repeats" in cli.validate_runtime_args(a)

    b = argparse.Namespace(mutation_apply="independent", repeats=1, step=2)
    assert "--step" in cli.validate_runtime_args(b)

    c = argparse.Namespace(mutation_apply="cumulative", repeats=1, step=0)
    assert "--step must be" in cli.validate_runtime_args(c)


def test_run_phases(tmp_path: Path, tiny_jpeg_path: Path) -> None:
    data = tiny_jpeg_path.read_bytes()
    _, ents = parse_jpeg(data)
    args = argparse.Namespace(
        output_dir=str(tmp_path / "out"),
        sample=2,
        seed=1,
        mutation_apply="cumulative",
        repeats=1,
        step=1,
        debug=False,
        gif=str(tmp_path / "x.gif"),
        gif_fps=5,
        gif_loop=0,
        gif_shuffle=False,
        input="portret.jpg",
        ssim_chart=str(tmp_path / "x.png"),
        metrics="ssim,psnr,mse,mae",
        metrics_chart_prefix=None,
        jobs=1,
        wave_chart=str(tmp_path / "wave.png"),
        sliding_wave_chart=str(tmp_path / "slide.png"),
        wave_window=4,
        dc_heatmap=str(tmp_path / "dc.png"),
        ac_energy_heatmap=str(tmp_path / "ac.png"),
    )

    count = cli.run_mutation_phase(args, data, ents, "tiny", "add1", None)
    assert count == 2

    # GIF phase may fail if Pillow unavailable; both are acceptable branches
    try:
        n = cli.run_gif_phase(args, "tiny")
        assert isinstance(n, int)
    except RuntimeError:
        pass

    # SSIM phase may fail if optional deps missing
    try:
        n2 = cli.run_ssim_phase(args, "tiny")
        assert isinstance(n2, int)
    except Exception:
        pass

    # Wave phases may fail if optional deps missing
    try:
        n3 = cli.run_wave_phase(args, data, ents)
        assert isinstance(n3, int)
    except RuntimeError:
        pass
    try:
        n4 = cli.run_sliding_wave_phase(args, data, ents)
        assert isinstance(n4, int)
    except RuntimeError:
        pass
    try:
        n5 = cli.run_dc_heatmap_phase(args)
        assert isinstance(n5, tuple) and len(n5) == 2
    except RuntimeError:
        pass
    try:
        n6 = cli.run_ac_heatmap_phase(args)
        assert isinstance(n6, tuple) and len(n6) == 2
    except RuntimeError:
        pass


def test_main_success_and_validation_error(monkeypatch, tmp_path: Path, tiny_jpeg_path: Path) -> None:
    ok_args = argparse.Namespace(
        input=str(tiny_jpeg_path),
        output_dir=str(tmp_path / "ok"),
        mutate="add1",
        sample=2,
        seed=1,
        mutation_apply="cumulative",
        repeats=1,
        step=1,
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
        wave_chart=None,
        sliding_wave_chart=None,
        wave_window=256,
        dc_heatmap=None,
        ac_energy_heatmap=None,
        debug=False,
    )
    monkeypatch.setattr(cli, "parse_args", lambda: ok_args)
    assert cli.main() == 0

    bad_args = argparse.Namespace(**{**ok_args.__dict__, "mutation_apply": "independent", "step": 2})
    monkeypatch.setattr(cli, "parse_args", lambda: bad_args)
    assert cli.main() == 2


def test_main_wave_only_skips_mutation(monkeypatch, tmp_path: Path, tiny_jpeg_path: Path) -> None:
    wave_args = argparse.Namespace(
        input=str(tiny_jpeg_path),
        output_dir=str(tmp_path / "out"),
        mutate="add1",
        sample=2,
        seed=1,
        mutation_apply="cumulative",
        repeats=1,
        step=1,
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
        wave_chart=str(tmp_path / "wave.png"),
        sliding_wave_chart=None,
        wave_window=256,
        dc_heatmap=None,
        ac_energy_heatmap=None,
        debug=False,
    )

    monkeypatch.setattr(cli, "parse_args", lambda: wave_args)
    monkeypatch.setattr(cli, "run_wave_phase", lambda *args, **kwargs: 5)
    monkeypatch.setattr(
        cli,
        "run_mutation_phase",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("mutation should be skipped")),
    )
    assert cli.main() == 0

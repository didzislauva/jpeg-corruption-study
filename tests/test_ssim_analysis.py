from __future__ import annotations

"""
Tests for SSIM/metric analysis helpers and chart generation.
"""

from pathlib import Path

import pytest

from jpeg_fault.core import ssim_analysis as sa


def test_resolve_jobs_and_parse_grouping(capsys) -> None:
    """
    Validate job resolution, metric list parsing, and cumulative grouping.
    """
    jobs = sa.resolve_jobs(None, debug=True)
    assert jobs >= 1
    err = capsys.readouterr().err
    assert "Detected CPU cores" in err

    assert sa.resolve_jobs(1, debug=False) == 1
    with pytest.raises(ValueError):
        sa.resolve_jobs(0, debug=False)
    assert sa.parse_metrics_list("ssim,psnr,mse,mae") == ["ssim", "psnr", "mse", "mae"]
    with pytest.raises(ValueError):
        sa.parse_metrics_list("unknown")

    p1 = "/x/set_0002/img_set_0002_cum_000003_step_001_off_abc_mut_add1.jpg"
    p2 = "/x/img_cum_000004_step_001_off_abc_mut_add1.jpg"
    assert sa.parse_cumulative_ids(p1) == (2, 3, 1)
    assert sa.parse_cumulative_ids(p2) == (1, 4, 1)
    assert sa.parse_cumulative_ids("/x/nope.jpg") is None

    sets, steps, step_size, lookup = sa.group_cumulative_paths([p1, p2, "/x/nope.jpg"])
    assert sets == [1, 2]
    assert steps == [3, 4]
    assert step_size == 1
    assert len(lookup) == 2

    p3 = "/x/set_0001/img_set_0001_cum_000010_step_002_off_abc_mut_add1.jpg"
    assert sa.parse_cumulative_ids(p3) == (1, 10, 2)


def test_group_cumulative_paths_rejects_mixed_step_sizes() -> None:
    """
    Ensure mixed step sizes across files are rejected.
    """
    p1 = "/x/a_set_0001_cum_000001_step_001_off_x_mut_add1.jpg"
    p2 = "/x/a_set_0001_cum_000002_step_002_off_x_mut_add1.jpg"
    with pytest.raises(ValueError):
        sa.group_cumulative_paths([p1, p2])


def test_load_rgb_array_and_score_helpers(tmp_path: Path) -> None:
    """
    Validate image load and metric scoring helpers.
    """
    pil = pytest.importorskip("PIL.Image")
    np = pytest.importorskip("numpy")
    sk = pytest.importorskip("skimage.metrics")

    p = tmp_path / "x.jpg"
    pil.new("RGB", (8, 8), "red").save(p)

    arr = sa.load_rgb_array(str(p), (8, 8), np, pil)
    assert arr is not None and arr.shape == (8, 8, 3)

    bad = sa.load_rgb_array(str(tmp_path / "bad.jpg"), (8, 8), np, pil)
    assert bad is None

    score = sa.score_for_path(str(p), (8, 8), arr, np, sk.structural_similarity, pil, "ssim")
    assert isinstance(score, float)


def test_prepare_grid_and_quantiles() -> None:
    """
    Validate grid preparation and quantile computations.
    """
    np = pytest.importorskip("numpy")

    sets = [1, 2]
    steps = [1, 2]
    lookup = {(1, 1): "a", (2, 2): "b"}
    scores, present, tasks = sa.prepare_ssim_grid(sets, steps, lookup, np)
    assert scores.shape == (2, 2)
    assert present.sum() == 2
    assert len(tasks) == 2

    mat = np.array([[1.0, np.nan, 0.5], [0.8, 0.7, np.nan]])
    q = sa.column_quantile(mat, 0.5, np)
    assert q.shape[0] == 3


def test_fill_scores_sequential(tmp_path: Path) -> None:
    """
    Validate sequential scoring path fills score matrix.
    """
    pil = pytest.importorskip("PIL.Image")
    np = pytest.importorskip("numpy")
    sk = pytest.importorskip("skimage.metrics")

    p = tmp_path / "x.jpg"
    pil.new("RGB", (8, 8), "green").save(p)

    scores = np.full((1, 1), np.nan)
    sa.fill_scores_sequential(
        scores,
        [(0, 0, str(p))],
        str(p),
        np,
        sk.structural_similarity,
        pil,
        "ssim",
    )
    assert np.isfinite(scores[0, 0])


def test_worker_task_and_parallel_fill(monkeypatch) -> None:
    """
    Validate worker task behavior and parallel fill logic via monkeypatch.
    """
    np = pytest.importorskip("numpy")

    # worker globals path
    sa._SSIM_REF_SIZE = (1, 1)
    sa._SSIM_NP = np

    class _ImgMod:
        @staticmethod
        def open(_):
            raise OSError("bad")

    sa._SSIM_IMAGE = _ImgMod
    sa._SSIM_REF_ARR = np.zeros((1, 1, 3), dtype=np.uint8)

    def _fake_ssim(a, b, channel_axis, data_range):
        return 0.123

    sa._SSIM_STRUCTURAL_SIMILARITY = _fake_ssim

    i, j, score = sa.ssim_worker_task((0, 0, "missing.jpg"))
    assert (i, j, score) == (0, 0, None)

    # fill_scores_parallel via monkeypatched executor/as_completed
    class _Future:
        def __init__(self, val):
            self._val = val

        def result(self):
            return self._val

    class _Exec:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def submit(self, fn, task):
            return _Future((task[0], task[1], 0.5))

    monkeypatch.setattr(sa, "ProcessPoolExecutor", _Exec)
    monkeypatch.setattr(sa, "as_completed", lambda futures: futures)

    scores = np.full((1, 1), np.nan)
    sa.fill_scores_parallel(scores, [(0, 0, "x")], "in.jpg", 2, debug=False, metric="ssim")
    assert scores[0, 0] == 0.5


def test_build_matrices_and_plots_and_write(tmp_path: Path) -> None:
    """
    Validate matrix building, plot helpers, and chart writers.
    """
    pil = pytest.importorskip("PIL.Image")
    np = pytest.importorskip("numpy")
    sk = pytest.importorskip("skimage.metrics")
    mpl = pytest.importorskip("matplotlib")

    inp = tmp_path / "in.jpg"
    pil.new("RGB", (8, 8), "white").save(inp)
    out_dir = tmp_path / "set_0001"
    out_dir.mkdir()
    m1 = out_dir / "in_set_0001_cum_000001_step_001_off_00000000_orig_00_new_01_mut_add1.jpg"
    m2 = out_dir / "in_set_0001_cum_000002_step_001_off_00000001_orig_00_new_01_mut_add1.jpg"
    pil.new("RGB", (8, 8), "white").save(m1)
    pil.new("RGB", (8, 8), "black").save(m2)

    paths = [str(m1), str(m2)]
    sets, steps, affected_bytes, scores, present = sa.build_ssim_matrices(
        str(inp), paths, np, sk.structural_similarity, pil, jobs=1, debug=False, metric="ssim"
    )
    assert sets == [1]
    assert steps == [1, 2]
    assert affected_bytes == [1, 2]
    assert present.sum() == 2

    fig = mpl.pyplot.figure()
    ax1 = fig.add_subplot(311)
    ax2 = fig.add_subplot(312)
    ax3 = fig.add_subplot(313)
    sa.plot_panel_a(ax1, affected_bytes, sets, scores, "ssim")
    sa.plot_panel_b(ax2, affected_bytes, scores, np, "ssim")
    sa.plot_panel_c(ax3, affected_bytes, scores, present, np)
    mpl.pyplot.close(fig)

    out = tmp_path / "chart.png"
    n = sa.write_ssim_panels(str(inp), paths, str(out), jobs_arg=1, debug=True)
    assert n == 1
    assert out.exists()

    out_psnr = tmp_path / "chart_psnr.png"
    n2 = sa.write_metric_panels(str(inp), paths, str(out_psnr), jobs_arg=1, debug=False, metric="psnr")
    assert n2 == 1
    assert out_psnr.exists()


def test_analysis_deps_import_guard() -> None:
    """
    Ensure analysis_deps raises helpful errors when deps are missing.
    """
    try:
        deps = sa.analysis_deps("ssim")
    except RuntimeError as e:
        assert "SSIM charts require" in str(e)
        return
    assert len(deps) == 4

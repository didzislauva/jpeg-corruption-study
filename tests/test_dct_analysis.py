from __future__ import annotations

from pathlib import Path

import pytest

from jpeg_fault.core import dct_analysis as da


def test_crop_and_block_maps_basic() -> None:
    np = pytest.importorskip("numpy")

    y = np.arange(16 * 16, dtype=np.float64).reshape(16, 16)
    cropped = da.crop_to_block_grid(y, np)
    assert cropped.shape == (16, 16)

    dc, ac = da.block_maps(y, np)
    assert dc.shape == (2, 2)
    assert ac.shape == (2, 2)


def test_small_image_rejected() -> None:
    np = pytest.importorskip("numpy")
    y = np.zeros((7, 9), dtype=np.float64)
    with pytest.raises(RuntimeError):
        da.crop_to_block_grid(y, np)


def test_write_heatmaps(tmp_path: Path) -> None:
    pil = pytest.importorskip("PIL.Image")
    pytest.importorskip("numpy")
    pytest.importorskip("matplotlib")

    inp = tmp_path / "in.jpg"
    pil.new("RGB", (32, 24), "gray").save(inp)
    out_dc = tmp_path / "dc.png"
    out_ac = tmp_path / "ac.png"

    by, bx = da.write_dc_heatmap(str(inp), str(out_dc), debug=True)
    assert by > 0 and bx > 0
    assert out_dc.exists()

    by2, bx2 = da.write_ac_energy_heatmap(str(inp), str(out_ac), debug=False)
    assert (by2, bx2) == (by, bx)
    assert out_ac.exists()


def test_dct_deps_guard(monkeypatch) -> None:
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("PIL"):
            raise ImportError("no pillow")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    with pytest.raises(RuntimeError):
        da.dct_deps()

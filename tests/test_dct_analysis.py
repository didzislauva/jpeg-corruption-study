from __future__ import annotations

"""
Tests for DCT-based heatmap utilities.
"""

from pathlib import Path

import pytest

from jpeg_fault.core import dct_analysis as da


def test_crop_and_block_maps_basic() -> None:
    """
    Validate block cropping and map shapes for a simple grid.
    """
    np = pytest.importorskip("numpy")

    y = np.arange(16 * 16, dtype=np.float64).reshape(16, 16)
    cropped = da.crop_to_block_grid(y, np)
    assert cropped.shape == (16, 16)

    dc, ac = da.block_maps(y, np)
    assert dc.shape == (2, 2)
    assert ac.shape == (2, 2)

    cropped16 = da.crop_to_block_grid(y, np, block_size=16)
    assert cropped16.shape == (16, 16)
    dc16, ac16 = da.block_maps(y, np, block_size=16)
    assert dc16.shape == (1, 1)
    assert ac16.shape == (1, 1)


def test_small_image_rejected() -> None:
    """
    Ensure images too small for 8x8 DCT blocks are rejected.
    """
    np = pytest.importorskip("numpy")
    y = np.zeros((7, 9), dtype=np.float64)
    with pytest.raises(RuntimeError):
        da.crop_to_block_grid(y, np)


def test_load_plane_modes() -> None:
    np = pytest.importorskip("numpy")

    class FakeImage:
        def __init__(self, arr):
            self._arr = arr

        def convert(self, _mode: str):
            return self

        def __array__(self, dtype=None):
            return self._arr.astype(dtype) if dtype is not None else self._arr

    class FakeImageModule:
        @staticmethod
        def open(_path: str):
            arr = np.array([[[30, 60, 90]]], dtype=np.float64)
            return FakeImage(arr)

    bt601 = da.load_plane("ignored", np, FakeImageModule, mode="bt601")
    bt709 = da.load_plane("ignored", np, FakeImageModule, mode="bt709")
    average = da.load_plane("ignored", np, FakeImageModule, mode="average")
    lightness = da.load_plane("ignored", np, FakeImageModule, mode="lightness")
    red = da.load_plane("ignored", np, FakeImageModule, mode="red")
    green = da.load_plane("ignored", np, FakeImageModule, mode="green")
    blue = da.load_plane("ignored", np, FakeImageModule, mode="blue")
    max_plane = da.load_plane("ignored", np, FakeImageModule, mode="max")
    min_plane = da.load_plane("ignored", np, FakeImageModule, mode="min")

    assert bt601.shape == (1, 1)
    assert bt709[0, 0] == pytest.approx((0.2126 * 30.0) + (0.7152 * 60.0) + (0.0722 * 90.0))
    assert average[0, 0] == pytest.approx(60.0)
    assert lightness[0, 0] == pytest.approx(60.0)
    assert red[0, 0] == pytest.approx(30.0)
    assert green[0, 0] == pytest.approx(60.0)
    assert blue[0, 0] == pytest.approx(90.0)
    assert max_plane[0, 0] == pytest.approx(90.0)
    assert min_plane[0, 0] == pytest.approx(30.0)


def test_invalid_plane_mode_and_block_size() -> None:
    np = pytest.importorskip("numpy")

    class FakeImage:
        def convert(self, _mode: str):
            return self

        def __array__(self, dtype=None):
            arr = np.zeros((1, 1, 3), dtype=np.float64)
            return arr.astype(dtype) if dtype is not None else arr

    class FakeImageModule:
        @staticmethod
        def open(_path: str):
            return FakeImage()

    with pytest.raises(ValueError, match="Unsupported plane mode"):
        da.load_plane("ignored", np, FakeImageModule, mode="bad")
    with pytest.raises(ValueError, match="block_size must be >= 2"):
        da.crop_to_block_grid(np.zeros((8, 8), dtype=np.float64), np, block_size=1)


def test_write_heatmaps(tmp_path: Path) -> None:
    """
    Validate DC and AC heatmap outputs are written.
    """
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

    out_ac2 = tmp_path / "ac2.png"
    by3, bx3 = da.write_ac_energy_heatmap(
        str(inp),
        str(out_ac2),
        debug=False,
        cmap="viridis",
        plane_mode="green",
        block_size=16,
    )
    assert (by3, bx3) == (1, 2)
    assert out_ac2.exists()


def test_dct_deps_guard(monkeypatch) -> None:
    """
    Ensure dct_deps raises a helpful error when Pillow is missing.
    """
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("PIL"):
            raise ImportError("no pillow")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    with pytest.raises(RuntimeError):
        da.dct_deps()


def test_dct_deps_forces_agg_backend() -> None:
    pytest.importorskip("matplotlib")
    _np, plt, _image = da.dct_deps()
    assert plt.get_backend().lower() == "agg"

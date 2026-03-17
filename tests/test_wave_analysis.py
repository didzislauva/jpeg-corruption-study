from __future__ import annotations

"""
Tests for entropy stream wave analysis utilities.
"""

from pathlib import Path

import pytest

from jpeg_fault.core.models import EntropyRange
from jpeg_fault.core import wave_analysis as wa


def test_entropy_bytes_and_bit_array() -> None:
    """
    Validate entropy stream concatenation and bit array conversion.
    """
    np = pytest.importorskip("numpy")
    data = bytes([0, 1, 2, 3, 4, 5])
    ranges = [EntropyRange(1, 3, 0), EntropyRange(4, 6, 1)]
    stream = wa.entropy_bytes(data, ranges)
    assert stream == bytes([1, 2, 4, 5])

    bits = wa.bytes_to_bit_array(stream, np)
    assert bits.shape[0] == 32


def test_maybe_downsample_and_rolling_stats() -> None:
    """
    Validate downsampling and rolling statistics helpers.
    """
    np = pytest.importorskip("numpy")
    arr = np.arange(100)
    ds, stride = wa.maybe_downsample(arr, 20, np)
    assert stride >= 1
    assert len(ds) <= 20

    stream = bytes(range(32))
    mean, var = wa.rolling_mean_var(stream, 4, np)
    ent = wa.rolling_entropy(stream, 4, np)
    assert mean.shape == var.shape
    assert mean.shape[0] == len(stream) - 4 + 1
    assert ent.shape[0] == len(stream) - 4 + 1

    with pytest.raises(ValueError):
        wa.rolling_mean_var(stream, 0, np)
    with pytest.raises(ValueError):
        wa.rolling_entropy(stream, 0, np)


def test_write_wave_charts(tmp_path: Path, tiny_jpeg_bytes: bytes) -> None:
    """
    Validate wave chart writers with a tiny JPEG stream.
    """
    pytest.importorskip("numpy")
    pytest.importorskip("matplotlib")

    # Matches conftest tiny JPEG entropy range: bytes between SOS payload and EOI marker
    ranges = [EntropyRange(30, 39, 0)]
    out1 = tmp_path / "wave.png"
    out2 = tmp_path / "slide.png"

    n = wa.write_wave_chart(tiny_jpeg_bytes, ranges, str(out1), debug=True)
    assert n == 9
    assert out1.exists()

    n2 = wa.write_sliding_wave_chart(tiny_jpeg_bytes, ranges, str(out2), window=4, debug=False)
    assert n2 == 9
    assert out2.exists()

    with pytest.raises(RuntimeError):
        wa.write_sliding_wave_chart(tiny_jpeg_bytes, ranges, str(out2), window=50, debug=False)


def test_wave_deps_guard(monkeypatch) -> None:
    """
    Ensure wave_deps raises a helpful error when matplotlib is missing.
    """
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("matplotlib"):
            raise ImportError("no mpl")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    with pytest.raises(RuntimeError):
        wa.wave_deps()


def test_wave_deps_forces_agg_backend() -> None:
    pytest.importorskip("matplotlib")
    _np, plt = wa.wave_deps()
    assert plt.get_backend().lower() == "agg"

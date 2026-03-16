"""
Entropy stream visualization utilities.

This module generates wave charts over the raw entropy-coded byte stream,
including byte and bit plots as well as sliding-window statistics.
"""

import time
from typing import Any, List, Sequence, Tuple

from .debug import debug_log
from .models import EntropyRange


def wave_deps() -> Tuple[Any, Any]:
    """
    Load optional dependencies for wave chart generation.
    """
    try:
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError as e:
        raise RuntimeError(
            "Wave charts require matplotlib and numpy. Install with: python3 -m pip install matplotlib numpy"
        ) from e
    return np, plt


def entropy_bytes(data: bytes, entropy_ranges: Sequence[EntropyRange]) -> bytes:
    """
    Concatenate entropy-coded data from all scan ranges.
    """
    chunks: List[bytes] = []
    for r in entropy_ranges:
        chunks.append(data[r.start:r.end])
    return b"".join(chunks)


def bytes_to_bit_array(stream: bytes, np: Any) -> Any:
    """
    Unpack a byte stream into a 0/1 bit array.
    """
    if not stream:
        return np.array([], dtype=np.uint8)
    arr = np.frombuffer(stream, dtype=np.uint8)
    return np.unpackbits(arr)


def maybe_downsample(series: Any, max_points: int, np: Any) -> Tuple[Any, int]:
    """
    Downsample a series to at most max_points, returning (series, stride).
    """
    n = int(series.shape[0])
    if n <= max_points:
        return series, 1
    stride = max(1, n // max_points)
    return series[::stride], stride


def rolling_mean_var(stream: bytes, window: int, np: Any) -> Tuple[Any, Any]:
    """
    Compute rolling mean and variance over a byte stream.
    """
    if window < 1:
        raise ValueError(f"--wave-window must be >= 1, got {window}")
    arr = np.frombuffer(stream, dtype=np.uint8).astype(np.float64)
    if arr.size < window:
        return np.array([], dtype=float), np.array([], dtype=float)
    kernel = np.ones(window, dtype=np.float64) / float(window)
    mean = np.convolve(arr, kernel, mode="valid")
    sq_mean = np.convolve(arr * arr, kernel, mode="valid")
    var = np.maximum(0.0, sq_mean - (mean * mean))
    return mean, var


def rolling_entropy(stream: bytes, window: int, np: Any) -> Any:
    """
    Compute rolling Shannon entropy over a byte stream.
    """
    if window < 1:
        raise ValueError(f"--wave-window must be >= 1, got {window}")
    arr = np.frombuffer(stream, dtype=np.uint8)
    n = int(arr.size)
    if n < window:
        return np.array([], dtype=float)
    hist = np.zeros(256, dtype=np.int64)
    for b in arr[:window]:
        hist[int(b)] += 1
    out = np.empty(n - window + 1, dtype=np.float64)

    def current_entropy() -> float:
        probs = hist[hist > 0] / float(window)
        return float(-(probs * np.log2(probs)).sum())

    out[0] = current_entropy()
    for i in range(window, n):
        hist[int(arr[i - window])] -= 1
        hist[int(arr[i])] += 1
        out[i - window + 1] = current_entropy()
    return out


def write_wave_chart(
    data: bytes,
    entropy_ranges: Sequence[EntropyRange],
    out_path: str,
    debug: bool,
) -> int:
    """
    Write a 2-panel chart of byte values and bit values over entropy stream.
    """
    np, plt = wave_deps()
    stream = entropy_bytes(data, entropy_ranges)
    if not stream:
        raise RuntimeError("No entropy-coded bytes found for wave chart.")

    byte_vals = np.frombuffer(stream, dtype=np.uint8)
    bits = bytes_to_bit_array(stream, np)
    byte_vals_plot, byte_stride = maybe_downsample(byte_vals, 25000, np)
    bits_plot, bit_stride = maybe_downsample(bits, 50000, np)

    debug_log(debug, f"Wave chart stream bytes={len(stream)}, bits={len(bits)}")
    debug_log(debug, f"Wave chart downsample: bytes stride={byte_stride}, bits stride={bit_stride}")

    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=False)
    axes[0].plot(byte_vals_plot, linewidth=0.7, color="tab:blue")
    axes[0].set_title("Byte Wave (Entropy Stream)")
    axes[0].set_xlabel(f"Byte Index (downsample stride={byte_stride})")
    axes[0].set_ylabel("Byte Value")
    axes[0].set_ylim(0, 255)
    axes[0].grid(True, alpha=0.2)

    axes[1].plot(bits_plot, linewidth=0.6, color="tab:orange")
    axes[1].set_title("Bit Wave (Entropy Stream)")
    axes[1].set_xlabel(f"Bit Index (downsample stride={bit_stride})")
    axes[1].set_ylabel("Bit")
    axes[1].set_ylim(-0.1, 1.1)
    axes[1].grid(True, alpha=0.2)

    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    return len(stream)


def write_sliding_wave_chart(
    data: bytes,
    entropy_ranges: Sequence[EntropyRange],
    out_path: str,
    window: int,
    debug: bool,
) -> int:
    """
    Write a 3-panel sliding window chart of mean, variance, and entropy.
    """
    np, plt = wave_deps()
    stream = entropy_bytes(data, entropy_ranges)
    if not stream:
        raise RuntimeError("No entropy-coded bytes found for sliding wave chart.")
    if len(stream) < window:
        raise RuntimeError(
            f"Sliding wave window ({window}) exceeds entropy stream length ({len(stream)})."
        )

    t0 = time.perf_counter()
    mean, var = rolling_mean_var(stream, window, np)
    ent = rolling_entropy(stream, window, np)
    debug_log(debug, f"Sliding wave compute time: {time.perf_counter() - t0:.2f}s")

    mean_plot, mean_stride = maybe_downsample(mean, 25000, np)
    var_plot, var_stride = maybe_downsample(var, 25000, np)
    ent_plot, ent_stride = maybe_downsample(ent, 25000, np)
    debug_log(debug, f"Sliding wave points: mean={len(mean)}, var={len(var)}, entropy={len(ent)}")

    fig, axes = plt.subplots(3, 1, figsize=(12, 12), sharex=False)
    axes[0].plot(mean_plot, linewidth=0.9, color="tab:green")
    axes[0].set_title(f"Rolling Mean (window={window})")
    axes[0].set_xlabel(f"Window Index (downsample stride={mean_stride})")
    axes[0].set_ylabel("Mean")
    axes[0].grid(True, alpha=0.2)

    axes[1].plot(var_plot, linewidth=0.9, color="tab:red")
    axes[1].set_title(f"Rolling Variance (window={window})")
    axes[1].set_xlabel(f"Window Index (downsample stride={var_stride})")
    axes[1].set_ylabel("Variance")
    axes[1].grid(True, alpha=0.2)

    axes[2].plot(ent_plot, linewidth=0.9, color="tab:purple")
    axes[2].set_title(f"Rolling Entropy (window={window})")
    axes[2].set_xlabel(f"Window Index (downsample stride={ent_stride})")
    axes[2].set_ylabel("Entropy (bits)")
    axes[2].set_ylim(0, 8.2)
    axes[2].grid(True, alpha=0.2)

    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    return len(stream)

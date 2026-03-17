"""
Entropy stream visualization utilities.

This module generates wave charts over the raw entropy-coded byte stream,
including byte and bit plots as well as sliding-window statistics.
"""

import csv
import time
from typing import Any, Dict, List, Literal, Sequence, Tuple

from .debug import debug_log
from .models import EntropyRange


WaveMode = Literal["byte", "bit", "both"]
WaveTransform = Literal["raw", "diff1", "diff2"]
SlidingStat = Literal["mean", "variance", "std", "entropy", "min", "max", "range", "energy"]


def wave_deps() -> Tuple[Any, Any]:
    """
    Load optional dependencies for wave chart generation.
    """
    try:
        import matplotlib
        matplotlib.use("Agg", force=True)
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


def _as_numeric_array(source: bytes | Any, np: Any) -> Any:
    if isinstance(source, (bytes, bytearray, memoryview)):
        return np.frombuffer(source, dtype=np.uint8).astype(np.float64)
    return np.asarray(source, dtype=np.float64)


def _as_integer_array(source: bytes | Any, np: Any) -> Any:
    if isinstance(source, (bytes, bytearray, memoryview)):
        return np.frombuffer(source, dtype=np.uint8).astype(np.int64)
    return np.asarray(source, dtype=np.int64)


def maybe_downsample(series: Any, max_points: int, np: Any) -> Tuple[Any, int]:
    """
    Downsample a series to at most max_points, returning (series, stride).
    """
    n = int(series.shape[0])
    if n <= max_points:
        return series, 1
    stride = max(1, n // max_points)
    return series[::stride], stride


def validate_wave_mode(mode: str) -> WaveMode:
    """
    Validate a wave chart mode string.
    """
    normalized = mode.strip().lower()
    if normalized not in {"byte", "bit", "both"}:
        raise ValueError(f"Unsupported wave mode: {mode}. Use one of: byte, bit, both")
    return normalized  # type: ignore[return-value]


def validate_wave_transform(transform: str) -> WaveTransform:
    """
    Validate a wave transform string.
    """
    normalized = transform.strip().lower()
    if normalized not in {"raw", "diff1", "diff2"}:
        raise ValueError(f"Unsupported wave transform: {transform}. Use one of: raw, diff1, diff2")
    return normalized  # type: ignore[return-value]


def transform_byte_series(stream: bytes | Any, transform: WaveTransform, np: Any) -> Any:
    """
    Convert a byte stream to the selected transformed byte-domain series.
    """
    values = _as_integer_array(stream, np)
    if transform == "raw":
        return values
    if values.size < 2:
        return np.array([], dtype=np.int64)
    diff1 = np.diff(values)
    if transform == "diff1":
        return diff1.astype(np.int64)
    if diff1.size < 2:
        return np.array([], dtype=np.int64)
    return np.diff(diff1).astype(np.int64)


def write_wave_csv(
    stream: bytes,
    out_path: str,
    mode: WaveMode,
    transform: WaveTransform,
    np: Any,
) -> None:
    """
    Write selected wave stream values to CSV.
    """
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        if mode == "byte":
            label = "byte_value" if transform == "raw" else transform
            writer.writerow(["byte_index", label])
            values = transform_byte_series(stream, transform, np)
            for idx, value in enumerate(values):
                writer.writerow([idx, int(value)])
            return
        bits = bytes_to_bit_array(stream, np)
        if mode == "bit":
            writer.writerow(["bit_index", "bit_value"])
            for idx, value in enumerate(bits):
                writer.writerow([idx, int(value)])
            return
        writer.writerow(["byte_index", "byte_value", "bit_index", "bit_value"])
        byte_vals = np.frombuffer(stream, dtype=np.uint8)
        bit_count = int(bits.shape[0])
        row_count = max(int(byte_vals.shape[0]), bit_count)
        for idx in range(row_count):
            byte_value = int(byte_vals[idx]) if idx < int(byte_vals.shape[0]) else ""
            bit_value = int(bits[idx]) if idx < bit_count else ""
            writer.writerow([idx, byte_value, idx, bit_value])


def rolling_mean_var(stream: bytes | Any, window: int, np: Any) -> Tuple[Any, Any]:
    """
    Compute rolling mean and variance over a byte stream.
    """
    if window < 1:
        raise ValueError(f"--wave-window must be >= 1, got {window}")
    arr = _as_numeric_array(stream, np)
    if arr.size < window:
        return np.array([], dtype=float), np.array([], dtype=float)
    kernel = np.ones(window, dtype=np.float64) / float(window)
    mean = np.convolve(arr, kernel, mode="valid")
    sq_mean = np.convolve(arr * arr, kernel, mode="valid")
    var = np.maximum(0.0, sq_mean - (mean * mean))
    return mean, var


def rolling_entropy(stream: bytes | Any, window: int, np: Any) -> Any:
    """
    Compute rolling Shannon entropy over a byte stream.
    """
    if window < 1:
        raise ValueError(f"--wave-window must be >= 1, got {window}")
    arr = _as_integer_array(stream, np)
    n = int(arr.size)
    if n < window:
        return np.array([], dtype=float)
    min_val = int(arr.min())
    max_val = int(arr.max())
    hist = np.zeros(max_val - min_val + 1, dtype=np.int64)
    for b in arr[:window]:
        hist[int(b) - min_val] += 1
    out = np.empty(n - window + 1, dtype=np.float64)

    def current_entropy() -> float:
        probs = hist[hist > 0] / float(window)
        return float(-(probs * np.log2(probs)).sum())

    out[0] = current_entropy()
    for i in range(window, n):
        hist[int(arr[i - window]) - min_val] -= 1
        hist[int(arr[i]) - min_val] += 1
        out[i - window + 1] = current_entropy()
    return out


def validate_sliding_stats(spec: str | Sequence[str]) -> List[SlidingStat]:
    """
    Validate and normalize the selected sliding-window stats.
    """
    allowed = ["mean", "variance", "std", "entropy", "min", "max", "range", "energy"]
    if isinstance(spec, str):
        parts = [part.strip().lower() for part in spec.split(",")]
    else:
        parts = [str(part).strip().lower() for part in spec]
    stats = [part for part in parts if part]
    if not stats:
        raise ValueError("At least one sliding-wave stat is required.")
    unknown = sorted({part for part in stats if part not in allowed})
    if unknown:
        raise ValueError(
            f"Unsupported sliding-wave stat(s): {', '.join(unknown)}. "
            f"Use one or more of: {', '.join(allowed)}"
        )
    out: List[SlidingStat] = []
    for stat in stats:
        if stat not in out:
            out.append(stat)  # type: ignore[arg-type]
    return out


def rolling_min_max(stream: bytes | Any, window: int, np: Any) -> Tuple[Any, Any]:
    """
    Compute rolling minimum and maximum over a byte stream.
    """
    if window < 1:
        raise ValueError(f"--wave-window must be >= 1, got {window}")
    arr = _as_numeric_array(stream, np)
    if arr.size < window:
        return np.array([], dtype=float), np.array([], dtype=float)
    mins = np.empty(arr.size - window + 1, dtype=np.float64)
    maxs = np.empty(arr.size - window + 1, dtype=np.float64)
    for idx in range(arr.size - window + 1):
        view = arr[idx:idx + window]
        mins[idx] = float(np.min(view))
        maxs[idx] = float(np.max(view))
    return mins, maxs


def rolling_energy(stream: bytes | Any, window: int, np: Any) -> Any:
    """
    Compute rolling mean squared value over a byte stream.
    """
    if window < 1:
        raise ValueError(f"--wave-window must be >= 1, got {window}")
    arr = _as_numeric_array(stream, np)
    if arr.size < window:
        return np.array([], dtype=float)
    kernel = np.ones(window, dtype=np.float64) / float(window)
    return np.convolve(arr * arr, kernel, mode="valid")


def sliding_stats(stream: bytes, window: int, stats: Sequence[SlidingStat], np: Any) -> Dict[str, Any]:
    """
    Compute the selected sliding-window statistics over a byte stream.
    """
    selected = validate_sliding_stats(stats)
    result: Dict[str, Any] = {}
    need_mean = any(stat in {"mean", "variance", "std"} for stat in selected)
    mean = var = None
    if need_mean:
        mean, var = rolling_mean_var(stream, window, np)
        if "mean" in selected:
            result["mean"] = mean
        if "variance" in selected:
            result["variance"] = var
        if "std" in selected:
            result["std"] = np.sqrt(var)
    if "entropy" in selected:
        result["entropy"] = rolling_entropy(stream, window, np)
    if any(stat in {"min", "max", "range"} for stat in selected):
        mins, maxs = rolling_min_max(stream, window, np)
        if "min" in selected:
            result["min"] = mins
        if "max" in selected:
            result["max"] = maxs
        if "range" in selected:
            result["range"] = maxs - mins
    if "energy" in selected:
        result["energy"] = rolling_energy(stream, window, np)
    return result


def write_sliding_wave_csv(out_path: str, stat_map: Dict[str, Any]) -> None:
    """
    Write sliding-window stats to CSV.
    """
    names = list(stat_map.keys())
    if not names:
        raise ValueError("No sliding-wave stats available for CSV export.")
    row_count = int(next(iter(stat_map.values())).shape[0])
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["window_index", *names])
        for idx in range(row_count):
            row = [idx]
            for name in names:
                row.append(float(stat_map[name][idx]))
            writer.writerow(row)


def write_wave_chart(
    data: bytes,
    entropy_ranges: Sequence[EntropyRange],
    out_path: str,
    debug: bool,
    mode: WaveMode = "both",
    transform: WaveTransform = "raw",
    csv_path: str | None = None,
) -> int:
    """
    Write a wave chart of the selected entropy stream views.
    """
    np, plt = wave_deps()
    mode = validate_wave_mode(mode)
    transform = validate_wave_transform(transform)
    stream = entropy_bytes(data, entropy_ranges)
    if not stream:
        raise RuntimeError("No entropy-coded bytes found for wave chart.")
    if transform != "raw" and mode != "byte":
        raise ValueError("Wave transform is only supported for byte mode.")

    if csv_path:
        write_wave_csv(stream, csv_path, mode, transform, np)

    panels: list[tuple[Any, str, str, str, tuple[float, float] | None, int, str]] = []
    if mode in {"byte", "both"}:
        byte_vals = transform_byte_series(stream, transform, np)
        byte_vals_plot, byte_stride = maybe_downsample(byte_vals, 25000, np)
        if transform == "raw":
            title = "Byte Wave (Entropy Stream)"
            ylabel = "Byte Value"
            ylim = (0, 255)
        elif transform == "diff1":
            title = "Byte First Derivative Wave"
            ylabel = "d1(Byte)"
            ylim = None
        else:
            title = "Byte Second Derivative Wave"
            ylabel = "d2(Byte)"
            ylim = None
        panels.append(
            (
                byte_vals_plot,
                title,
                f"Byte Index (downsample stride={byte_stride})",
                ylabel,
                ylim,
                byte_stride,
                "tab:blue",
            )
        )
    if mode in {"bit", "both"}:
        bits = bytes_to_bit_array(stream, np)
        bits_plot, bit_stride = maybe_downsample(bits, 50000, np)
        panels.append(
            (
                bits_plot,
                "Bit Wave (Entropy Stream)",
                f"Bit Index (downsample stride={bit_stride})",
                "Bit",
                (-0.1, 1.1),
                bit_stride,
                "tab:orange",
            )
        )

    debug_log(debug, f"Wave chart mode={mode}, transform={transform}, stream bytes={len(stream)}")
    fig, axes = plt.subplots(len(panels), 1, figsize=(12, 4 * len(panels)), sharex=False)
    if len(panels) == 1:
        axes = [axes]
    for ax, panel in zip(axes, panels):
        series, title, xlabel, ylabel, ylim, _stride, color = panel
        ax.plot(series, linewidth=0.7, color=color)
        ax.set_title(title)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        if ylim is not None:
            ax.set_ylim(*ylim)
        ax.grid(True, alpha=0.2)
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
    stats: Sequence[SlidingStat] | str = ("mean", "variance", "entropy"),
    transform: WaveTransform = "raw",
    csv_path: str | None = None,
) -> int:
    """
    Write a sliding-window chart for the selected stats.
    """
    np, plt = wave_deps()
    transform = validate_wave_transform(transform)
    stream = entropy_bytes(data, entropy_ranges)
    if not stream:
        raise RuntimeError("No entropy-coded bytes found for sliding wave chart.")
    transformed = transform_byte_series(stream, transform, np)
    if len(transformed) < window:
        raise RuntimeError(
            f"Sliding wave window ({window}) exceeds transformed stream length ({len(transformed)})."
        )
    selected = validate_sliding_stats(stats)

    t0 = time.perf_counter()
    stat_map = sliding_stats(transformed, window, selected, np)
    debug_log(debug, f"Sliding wave compute time: {time.perf_counter() - t0:.2f}s")
    if csv_path:
        write_sliding_wave_csv(csv_path, stat_map)

    panel_defs = {
        "mean": ("Rolling Mean", "Mean", "tab:green", None),
        "variance": ("Rolling Variance", "Variance", "tab:red", None),
        "std": ("Rolling Std Dev", "Std Dev", "tab:olive", None),
        "entropy": ("Rolling Entropy", "Entropy (bits)", "tab:purple", None),
        "min": ("Rolling Minimum", "Min", "tab:blue", None),
        "max": ("Rolling Maximum", "Max", "tab:orange", None),
        "range": ("Rolling Range", "Range", "tab:brown", None),
        "energy": ("Rolling Energy", "Mean(x^2)", "tab:cyan", None),
    }
    plotted: list[tuple[str, Any, int]] = []
    for name in selected:
        series = stat_map[name]
        plot_series, stride = maybe_downsample(series, 25000, np)
        plotted.append((name, plot_series, stride))
    debug_log(
        debug,
        "Sliding wave transform="
        + transform
        + ", points: "
        + ", ".join(f"{name}={len(stat_map[name])}" for name in selected),
    )

    fig, axes = plt.subplots(len(plotted), 1, figsize=(12, 4 * len(plotted)), sharex=False)
    if len(plotted) == 1:
        axes = [axes]
    for ax, (name, series, stride) in zip(axes, plotted):
        title, ylabel, color, ylim = panel_defs[name]
        ax.plot(series, linewidth=0.9, color=color)
        transform_suffix = "" if transform == "raw" else f", transform={transform}"
        ax.set_title(f"{title} (window={window}{transform_suffix})")
        ax.set_xlabel(f"Window Index (downsample stride={stride})")
        ax.set_ylabel(ylabel)
        if ylim is not None:
            ax.set_ylim(*ylim)
        ax.grid(True, alpha=0.2)

    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    return len(stream)

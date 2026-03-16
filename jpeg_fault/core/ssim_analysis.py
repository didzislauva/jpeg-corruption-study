"""
Metric computation and chart generation for mutation outputs.

Supports SSIM, PSNR, MSE, and MAE. Charts are 3-panel outputs that show:
- per-repetition lines
- quantile summaries
- decode success rate
"""

import os
import re
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Set, Tuple

from .debug import debug_log


def analysis_deps(metric: str) -> Tuple[Any, Any, Any, Any]:
    """
    Load optional analysis dependencies for the requested metric.
    """
    try:
        from PIL import Image
        import matplotlib.pyplot as plt
        import numpy as np
        structural_similarity = None
        if metric == "ssim":
            from skimage.metrics import structural_similarity as _ssim
            structural_similarity = _ssim
    except ImportError as e:
        if metric == "ssim":
            raise RuntimeError(
                "SSIM charts require Pillow, matplotlib, numpy, and scikit-image. "
                "Install with: python3 -m pip install pillow matplotlib numpy scikit-image"
            ) from e
        raise RuntimeError(
            "Metric charts require Pillow, matplotlib, and numpy. "
            "Install with: python3 -m pip install pillow matplotlib numpy"
        ) from e
    return np, plt, structural_similarity, Image


def parse_metrics_list(spec: str) -> List[str]:
    """
    Parse a comma-separated metrics list.
    """
    allowed = {"ssim", "psnr", "mse", "mae"}
    metrics: List[str] = []
    for part in spec.split(","):
        m = part.strip().lower()
        if not m:
            continue
        if m not in allowed:
            raise ValueError(f"Unsupported metric: {m}. Use one of: {', '.join(sorted(allowed))}")
        metrics.append(m)
    if not metrics:
        raise ValueError("At least one metric is required.")
    return sorted(set(metrics), key=metrics.index)


def resolve_jobs(jobs_arg: Optional[int], debug: bool) -> int:
    """
    Resolve process worker count from a CLI argument.
    """
    detected = os.cpu_count() or 1
    if jobs_arg is None:
        jobs = detected
    else:
        if jobs_arg < 1:
            raise ValueError(f"--jobs must be >= 1, got {jobs_arg}")
        jobs = min(jobs_arg, detected)
    debug_log(debug, f"Detected CPU cores: {detected}, using jobs: {jobs}")
    return jobs


def parse_cumulative_ids(path: str) -> Optional[Tuple[int, int, int]]:
    """
    Parse set id, step index, and step size from a cumulative output filename.
    """
    name = os.path.basename(path)
    step_match = re.search(r"_cum_(\d+)_", name)
    if not step_match:
        return None
    step = int(step_match.group(1))
    step_size_match = re.search(r"_step_(\d+)_", name)
    step_size = int(step_size_match.group(1)) if step_size_match else 1
    set_match = re.search(r"_set_(\d+)_cum_", name)
    if set_match:
        return int(set_match.group(1)), step, step_size
    parent = os.path.basename(os.path.dirname(path))
    parent_match = re.fullmatch(r"set_(\d+)", parent)
    set_id = int(parent_match.group(1)) if parent_match else 1
    return set_id, step, step_size


def group_cumulative_paths(paths: List[str]) -> Tuple[List[int], List[int], int, Dict[Tuple[int, int], str]]:
    """
    Group cumulative file paths by set and step and validate step size consistency.
    """
    set_ids: Set[int] = set()
    steps: Set[int] = set()
    step_sizes: Set[int] = set()
    lookup: Dict[Tuple[int, int], str] = {}
    for path in paths:
        ids = parse_cumulative_ids(path)
        if ids is None:
            continue
        set_id, step, step_size = ids
        set_ids.add(set_id)
        steps.add(step)
        step_sizes.add(step_size)
        lookup[(set_id, step)] = path
    if len(step_sizes) > 1:
        raise ValueError(f"Found mixed cumulative --step sizes in files: {sorted(step_sizes)}")
    resolved_step_size = next(iter(step_sizes), 1)
    return sorted(set_ids), sorted(steps), resolved_step_size, lookup


def load_rgb_array(path: str, ref_size: Tuple[int, int], np: Any, image_module: Any) -> Optional[Any]:
    """
    Load an image into an RGB numpy array, resizing to reference size.
    """
    try:
        img = image_module.open(path).convert("RGB")
        if img.size != ref_size:
            img = img.resize(ref_size)
        return np.asarray(img, dtype=np.uint8)
    except Exception:
        return None


def score_for_path(
    path: str,
    ref_size: Tuple[int, int],
    ref_arr: Any,
    np: Any,
    structural_similarity: Any,
    image_module: Any,
    metric: str,
) -> Optional[float]:
    """
    Compute a metric score for a single path; returns None if decode fails.
    """
    arr = load_rgb_array(path, ref_size, np, image_module)
    if arr is None:
        return None
    if metric == "ssim":
        return float(structural_similarity(ref_arr, arr, channel_axis=2, data_range=255))
    diff = ref_arr.astype(np.float32) - arr.astype(np.float32)
    if metric == "mse":
        return float(np.mean(diff * diff))
    if metric == "mae":
        return float(np.mean(np.abs(diff)))
    if metric == "psnr":
        mse = float(np.mean(diff * diff))
        if mse <= 0:
            return float("inf")
        return float(20.0 * np.log10(255.0) - 10.0 * np.log10(mse))
    raise ValueError(f"Unsupported metric: {metric}")


_SSIM_REF_ARR: Any = None
_SSIM_REF_SIZE: Optional[Tuple[int, int]] = None
_SSIM_NP: Any = None
_SSIM_STRUCTURAL_SIMILARITY: Any = None
_SSIM_IMAGE: Any = None
_SSIM_METRIC: str = "ssim"


def ssim_worker_init(input_path: str, metric: str) -> None:
    """
    Worker initializer for multiprocessing metric computation.
    """
    global _SSIM_REF_ARR, _SSIM_REF_SIZE, _SSIM_NP, _SSIM_STRUCTURAL_SIMILARITY, _SSIM_IMAGE, _SSIM_METRIC
    from PIL import Image
    import numpy as np

    structural_similarity = None
    if metric == "ssim":
        from skimage.metrics import structural_similarity as _ssim
        structural_similarity = _ssim
    ref_img = Image.open(input_path).convert("RGB")
    _SSIM_REF_SIZE = ref_img.size
    _SSIM_REF_ARR = np.asarray(ref_img, dtype=np.uint8)
    _SSIM_NP = np
    _SSIM_STRUCTURAL_SIMILARITY = structural_similarity
    _SSIM_IMAGE = Image
    _SSIM_METRIC = metric


def ssim_worker_task(task: Tuple[int, int, str]) -> Tuple[int, int, Optional[float]]:
    """
    Worker task: compute score for a single (set, step, path).
    """
    i, j, path = task
    if _SSIM_REF_SIZE is None:
        return i, j, None
    arr = load_rgb_array(path, _SSIM_REF_SIZE, _SSIM_NP, _SSIM_IMAGE)
    if arr is None:
        return i, j, None
    if _SSIM_METRIC == "ssim":
        score = _SSIM_STRUCTURAL_SIMILARITY(_SSIM_REF_ARR, arr, channel_axis=2, data_range=255)
        return i, j, float(score)
    diff = _SSIM_REF_ARR.astype(_SSIM_NP.float32) - arr.astype(_SSIM_NP.float32)
    if _SSIM_METRIC == "mse":
        return i, j, float(_SSIM_NP.mean(diff * diff))
    if _SSIM_METRIC == "mae":
        return i, j, float(_SSIM_NP.mean(_SSIM_NP.abs(diff)))
    if _SSIM_METRIC == "psnr":
        mse = float(_SSIM_NP.mean(diff * diff))
        if mse <= 0:
            return i, j, float("inf")
        psnr = float(20.0 * _SSIM_NP.log10(255.0) - 10.0 * _SSIM_NP.log10(mse))
        return i, j, psnr
    return i, j, None


def prepare_ssim_grid(
    set_ids: List[int],
    steps: List[int],
    lookup: Dict[Tuple[int, int], str],
    np: Any,
) -> Tuple[Any, Any, List[Tuple[int, int, str]]]:
    """
    Create empty score/presence matrices and a task list for scoring.
    """
    scores = np.full((len(set_ids), len(steps)), np.nan, dtype=float)
    present = np.zeros((len(set_ids), len(steps)), dtype=bool)
    tasks: List[Tuple[int, int, str]] = []
    for i, set_id in enumerate(set_ids):
        for j, step in enumerate(steps):
            path = lookup.get((set_id, step))
            if path is None:
                continue
            present[i, j] = True
            tasks.append((i, j, path))
    return scores, present, tasks


def fill_scores_sequential(
    scores: Any,
    tasks: List[Tuple[int, int, str]],
    input_path: str,
    np: Any,
    structural_similarity: Any,
    image_module: Any,
    metric: str,
) -> None:
    """
    Fill the score matrix sequentially in a single process.
    """
    ref_img = image_module.open(input_path).convert("RGB")
    ref_size = ref_img.size
    ref_arr = np.asarray(ref_img, dtype=np.uint8)
    for i, j, path in tasks:
        score = score_for_path(
            path, ref_size, ref_arr, np, structural_similarity, image_module, metric
        )
        if score is not None:
            scores[i, j] = score


def fill_scores_parallel(
    scores: Any,
    tasks: List[Tuple[int, int, str]],
    input_path: str,
    jobs: int,
    debug: bool,
    metric: str,
) -> None:
    """
    Fill the score matrix using multiprocessing.
    """
    with ProcessPoolExecutor(
        max_workers=jobs, initializer=ssim_worker_init, initargs=(input_path, metric)
    ) as executor:
        futures = [executor.submit(ssim_worker_task, task) for task in tasks]
        for fut in as_completed(futures):
            try:
                i, j, score = fut.result()
            except Exception as e:
                debug_log(debug, f"Worker task failed: {e}")
                continue
            if score is not None:
                scores[i, j] = score


def column_quantile(scores: Any, q: float, np: Any) -> Any:
    """
    Compute column-wise quantiles, ignoring NaN values.
    """
    vals: List[float] = []
    for col in range(scores.shape[1]):
        col_vals = scores[:, col]
        valid = col_vals[np.isfinite(col_vals)]
        if valid.size == 0:
            vals.append(np.nan)
            continue
        vals.append(float(np.quantile(valid, q)))
    return np.asarray(vals, dtype=float)


def build_ssim_matrices(
    input_path: str,
    paths: List[str],
    np: Any,
    structural_similarity: Any,
    image_module: Any,
    jobs: int,
    debug: bool,
    metric: str,
) -> Tuple[List[int], List[int], List[int], Any, Any]:
    """
    Build the x-axis, score matrix, and presence matrix for charting.
    """
    set_ids, steps, step_size, lookup = group_cumulative_paths(paths)
    debug_log(debug, f"{metric.upper()} input files: {len(paths)}")
    debug_log(debug, f"Cumulative files matched: {len(lookup)}")
    debug_log(debug, f"Detected sets: {len(set_ids)}, steps: {len(steps)}, step_size={step_size}")
    if not set_ids or not steps:
        raise RuntimeError("No cumulative mutation files found for SSIM analysis.")
    affected_bytes = [s * step_size for s in steps]
    scores, present, tasks = prepare_ssim_grid(set_ids, steps, lookup, np)
    t0 = time.perf_counter()
    if jobs == 1:
        fill_scores_sequential(
            scores, tasks, input_path, np, structural_similarity, image_module, metric
        )
    else:
        fill_scores_parallel(scores, tasks, input_path, jobs, debug, metric)
    debug_log(debug, f"{metric.upper()} compute time: {time.perf_counter() - t0:.2f}s")
    present_count = int(present.sum())
    decoded_count = int(np.isfinite(scores).sum())
    debug_log(debug, f"Pairs present: {present_count}, decodable: {decoded_count}")
    if present_count > 0:
        debug_log(debug, f"Overall decode rate: {decoded_count / present_count:.4f}")
    return set_ids, steps, affected_bytes, scores, present


def plot_panel_a(ax: Any, x_values: List[int], set_ids: List[int], scores: Any, metric: str) -> None:
    """
    Panel A: plot each repetition line.
    """
    for i, set_id in enumerate(set_ids):
        ax.plot(x_values, scores[i], linewidth=1.0, alpha=0.45, label=f"set {set_id:04d}")
    ax.set_title(f"A: {metric.upper()} Per Repetition")
    ax.set_xlabel("Affected Bytes")
    ax.set_ylabel(metric.upper())
    if metric == "ssim":
        ax.set_ylim(0, 1.02)
    ax.grid(True, alpha=0.2)
    if len(set_ids) <= 12:
        ax.legend(loc="lower left", fontsize=8, ncol=2)


def plot_panel_b(ax: Any, x_values: List[int], scores: Any, np: Any, metric: str) -> None:
    """
    Panel B: plot quantile summary lines.
    """
    q10 = column_quantile(scores, 0.10, np)
    q25 = column_quantile(scores, 0.25, np)
    q50 = column_quantile(scores, 0.50, np)
    q75 = column_quantile(scores, 0.75, np)
    q90 = column_quantile(scores, 0.90, np)
    ax.plot(x_values, q50, color="black", linewidth=2.0, label="median")
    ax.plot(x_values, q25, color="tab:blue", linewidth=1.2, linestyle="--", label="q25/q75")
    ax.plot(x_values, q75, color="tab:blue", linewidth=1.2, linestyle="--")
    ax.plot(x_values, q10, color="tab:gray", linewidth=1.0, linestyle=":", label="q10/q90")
    ax.plot(x_values, q90, color="tab:gray", linewidth=1.0, linestyle=":")
    ax.set_title(f"B: {metric.upper()} Quantile Summary")
    ax.set_xlabel("Affected Bytes")
    ax.set_ylabel(metric.upper())
    if metric == "ssim":
        ax.set_ylim(0, 1.02)
    ax.grid(True, alpha=0.2)
    ax.legend(loc="lower left", fontsize=8)


def plot_panel_c(ax: Any, x_values: List[int], scores: Any, present: Any, np: Any) -> None:
    """
    Panel C: plot decode success rate for each x position.
    """
    available = present.sum(axis=0)
    decoded = np.isfinite(scores).sum(axis=0)
    rate = np.full(len(x_values), np.nan, dtype=float)
    mask = available > 0
    rate[mask] = decoded[mask] / available[mask]
    ax.plot(x_values, rate, color="tab:red", linewidth=2.0)
    ax.set_title("C: Decode Success Rate")
    ax.set_xlabel("Affected Bytes")
    ax.set_ylabel("Decode Success")
    ax.set_ylim(0, 1.02)
    ax.grid(True, alpha=0.2)


def write_metric_panels(
    input_path: str,
    paths: List[str],
    out_path: str,
    jobs_arg: Optional[int],
    debug: bool,
    metric: str,
) -> int:
    """
    Write a 3-panel metric chart and return the number of sets plotted.
    """
    jobs = resolve_jobs(jobs_arg, debug)
    np, plt, structural_similarity, image_module = analysis_deps(metric)
    set_ids, steps, affected_bytes, scores, present = build_ssim_matrices(
        input_path, paths, np, structural_similarity, image_module, jobs, debug, metric
    )
    if debug:
        sample_steps = min(8, len(steps))
        decoded = np.isfinite(scores).sum(axis=0)
        available = present.sum(axis=0)
        for idx in range(sample_steps):
            step = steps[idx]
            bytes_affected = affected_bytes[idx]
            debug_log(
                True,
                f"{metric} step {step} (bytes={bytes_affected}): decoded {int(decoded[idx])}/{int(available[idx])}",
            )
    fig, axes = plt.subplots(3, 1, figsize=(12, 14), sharex=True)
    plot_panel_a(axes[0], affected_bytes, set_ids, scores, metric)
    plot_panel_b(axes[1], affected_bytes, scores, np, metric)
    plot_panel_c(axes[2], affected_bytes, scores, present, np)
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    return len(set_ids)


def write_ssim_panels(
    input_path: str,
    paths: List[str],
    out_path: str,
    jobs_arg: Optional[int],
    debug: bool,
) -> int:
    """
    SSIM-specific convenience wrapper for write_metric_panels.
    """
    return write_metric_panels(input_path, paths, out_path, jobs_arg, debug, "ssim")

"""
DCT-based heatmaps computed from the decoded image.

These heatmaps are computed on a decoded single-channel projection and are not
equivalent to JPEG coefficient extraction from the compressed bitstream.
"""

import math
import time
from typing import Any, Tuple

from ...debug import debug_log


def dct_deps() -> Tuple[Any, Any, Any]:
    """
    Load optional dependencies for DCT heatmap generation.
    """
    try:
        from PIL import Image
        import matplotlib
        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError as e:
        raise RuntimeError(
            "DCT heatmaps require Pillow, matplotlib, numpy. Install with: python3 -m pip install pillow matplotlib numpy"
        ) from e
    return np, plt, Image


def load_plane(path: str, np: Any, image_module: Any, mode: str = "bt601") -> Any:
    """
    Load an image and project it to a single-channel analysis plane.
    """
    img = image_module.open(path).convert("RGB")
    arr = np.asarray(img, dtype=np.float64)
    if mode == "bt601":
        return (0.299 * arr[:, :, 0]) + (0.587 * arr[:, :, 1]) + (0.114 * arr[:, :, 2])
    if mode == "bt709":
        return (0.2126 * arr[:, :, 0]) + (0.7152 * arr[:, :, 1]) + (0.0722 * arr[:, :, 2])
    if mode == "average":
        return (arr[:, :, 0] + arr[:, :, 1] + arr[:, :, 2]) / 3.0
    if mode == "lightness":
        hi = np.maximum(np.maximum(arr[:, :, 0], arr[:, :, 1]), arr[:, :, 2])
        lo = np.minimum(np.minimum(arr[:, :, 0], arr[:, :, 1]), arr[:, :, 2])
        return (hi + lo) / 2.0
    if mode == "max":
        return np.maximum(np.maximum(arr[:, :, 0], arr[:, :, 1]), arr[:, :, 2])
    if mode == "min":
        return np.minimum(np.minimum(arr[:, :, 0], arr[:, :, 1]), arr[:, :, 2])
    if mode == "red":
        return arr[:, :, 0]
    if mode == "green":
        return arr[:, :, 1]
    if mode == "blue":
        return arr[:, :, 2]
    raise ValueError(f"Unsupported plane mode: {mode}")


def crop_to_block_grid(y_plane: Any, np: Any, block_size: int = 8) -> Any:
    """
    Crop a luminance plane to the largest block-aligned rectangle.
    """
    _validate_block_size(block_size)
    h, w = y_plane.shape
    h_aligned = (h // block_size) * block_size
    w_aligned = (w // block_size) * block_size
    if h_aligned < block_size or w_aligned < block_size:
        raise RuntimeError(f"Image is too small for {block_size}x{block_size} DCT heatmaps.")
    return y_plane[:h_aligned, :w_aligned]


def dct_basis(np: Any, block_size: int = 8) -> Any:
    """
    Construct the NxN DCT basis matrix for the selected block size.
    """
    _validate_block_size(block_size)
    c = np.zeros((block_size, block_size), dtype=np.float64)
    for u in range(block_size):
        alpha = math.sqrt(1.0 / block_size) if u == 0 else math.sqrt(2.0 / block_size)
        for x in range(block_size):
            c[u, x] = alpha * math.cos(((2 * x + 1) * u * math.pi) / (2.0 * block_size))
    return c


def block_maps(y_plane: Any, np: Any, block_size: int = 8) -> Tuple[Any, Any]:
    """
    Compute per-block DC coefficients and AC energy from the luminance plane.
    """
    y = crop_to_block_grid(y_plane, np, block_size=block_size)
    h, w = y.shape
    by, bx = h // block_size, w // block_size
    dc = np.zeros((by, bx), dtype=np.float64)
    ac = np.zeros((by, bx), dtype=np.float64)
    c = dct_basis(np, block_size=block_size)
    ct = c.T

    for iy in range(by):
        for ix in range(bx):
            blk = y[
                iy * block_size:(iy + 1) * block_size,
                ix * block_size:(ix + 1) * block_size,
            ] - 128.0
            coeff = c @ blk @ ct
            dc_val = coeff[0, 0]
            dc[iy, ix] = dc_val
            ac[iy, ix] = float(np.sum(np.abs(coeff)) - abs(dc_val))
    return dc, ac


def plot_heatmap(ax: Any, data: Any, title: str, cmap: str) -> None:
    """
    Render a heatmap with colorbar and axis labels.
    """
    im = ax.imshow(data, cmap=cmap, aspect="auto")
    ax.set_title(title)
    ax.set_xlabel("Block X")
    ax.set_ylabel("Block Y")
    ax.figure.colorbar(im, ax=ax, fraction=0.046, pad=0.04)


def _validate_block_size(block_size: int) -> None:
    if block_size < 2:
        raise ValueError("block_size must be >= 2")


def write_dc_heatmap(
    input_path: str,
    out_path: str,
    debug: bool,
    cmap: str = "coolwarm",
    plane_mode: str = "bt601",
    block_size: int = 8,
) -> Tuple[int, int]:
    """
    Write a DC coefficient heatmap and return block grid dimensions.
    """
    np, plt, image_module = dct_deps()
    t0 = time.perf_counter()
    y = load_plane(input_path, np, image_module, mode=plane_mode)
    dc, _ = block_maps(y, np, block_size=block_size)
    debug_log(debug, f"DC heatmap blocks: {dc.shape[0]}x{dc.shape[1]}")

    fig, ax = plt.subplots(1, 1, figsize=(10, 7))
    plot_heatmap(ax, dc, f"DC Coefficient Heatmap ({block_size}x{block_size} blocks)", cmap)
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    debug_log(debug, f"DC heatmap generation time: {time.perf_counter() - t0:.2f}s")
    return int(dc.shape[0]), int(dc.shape[1])


def write_ac_energy_heatmap(
    input_path: str,
    out_path: str,
    debug: bool,
    cmap: str = "magma",
    plane_mode: str = "bt601",
    block_size: int = 8,
) -> Tuple[int, int]:
    """
    Write an AC energy heatmap and return block grid dimensions.
    """
    np, plt, image_module = dct_deps()
    t0 = time.perf_counter()
    y = load_plane(input_path, np, image_module, mode=plane_mode)
    _, ac = block_maps(y, np, block_size=block_size)
    debug_log(debug, f"AC energy heatmap blocks: {ac.shape[0]}x{ac.shape[1]}")

    fig, ax = plt.subplots(1, 1, figsize=(10, 7))
    plot_heatmap(ax, ac, f"AC Energy Heatmap ({block_size}x{block_size} blocks)", cmap)
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    debug_log(debug, f"AC heatmap generation time: {time.perf_counter() - t0:.2f}s")
    return int(ac.shape[0]), int(ac.shape[1])

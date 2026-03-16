"""
DCT-based heatmaps computed from the decoded image.

These heatmaps are computed on the decoded luminance channel and are not
equivalent to JPEG coefficient extraction from the compressed bitstream.
"""

import math
import time
from typing import Any, Tuple

from .debug import debug_log


def dct_deps() -> Tuple[Any, Any, Any]:
    """
    Load optional dependencies for DCT heatmap generation.
    """
    try:
        from PIL import Image
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError as e:
        raise RuntimeError(
            "DCT heatmaps require Pillow, matplotlib, numpy. Install with: python3 -m pip install pillow matplotlib numpy"
        ) from e
    return np, plt, Image


def load_luma(path: str, np: Any, image_module: Any) -> Any:
    """
    Load an image and convert it to a luminance array.
    """
    img = image_module.open(path).convert("RGB")
    arr = np.asarray(img, dtype=np.float64)
    return (0.299 * arr[:, :, 0]) + (0.587 * arr[:, :, 1]) + (0.114 * arr[:, :, 2])


def crop_to_block_grid(y_plane: Any, np: Any) -> Any:
    """
    Crop a luminance plane to the largest 8x8-aligned rectangle.
    """
    h, w = y_plane.shape
    h8 = (h // 8) * 8
    w8 = (w // 8) * 8
    if h8 < 8 or w8 < 8:
        raise RuntimeError("Image is too small for 8x8 DCT heatmaps.")
    return y_plane[:h8, :w8]


def dct_basis_8(np: Any) -> Any:
    """
    Construct the 8x8 DCT basis matrix.
    """
    c = np.zeros((8, 8), dtype=np.float64)
    for u in range(8):
        alpha = math.sqrt(1.0 / 8.0) if u == 0 else math.sqrt(2.0 / 8.0)
        for x in range(8):
            c[u, x] = alpha * math.cos(((2 * x + 1) * u * math.pi) / 16.0)
    return c


def block_maps(y_plane: Any, np: Any) -> Tuple[Any, Any]:
    """
    Compute per-block DC coefficients and AC energy from the luminance plane.
    """
    y = crop_to_block_grid(y_plane, np)
    h, w = y.shape
    by, bx = h // 8, w // 8
    dc = np.zeros((by, bx), dtype=np.float64)
    ac = np.zeros((by, bx), dtype=np.float64)
    c = dct_basis_8(np)
    ct = c.T

    for iy in range(by):
        for ix in range(bx):
            blk = y[iy * 8:(iy + 1) * 8, ix * 8:(ix + 1) * 8] - 128.0
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


def write_dc_heatmap(input_path: str, out_path: str, debug: bool) -> Tuple[int, int]:
    """
    Write a DC coefficient heatmap and return block grid dimensions.
    """
    np, plt, image_module = dct_deps()
    t0 = time.perf_counter()
    y = load_luma(input_path, np, image_module)
    dc, _ = block_maps(y, np)
    debug_log(debug, f"DC heatmap blocks: {dc.shape[0]}x{dc.shape[1]}")

    fig, ax = plt.subplots(1, 1, figsize=(10, 7))
    plot_heatmap(ax, dc, "DC Coefficient Heatmap (8x8 blocks)", "coolwarm")
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    debug_log(debug, f"DC heatmap generation time: {time.perf_counter() - t0:.2f}s")
    return int(dc.shape[0]), int(dc.shape[1])


def write_ac_energy_heatmap(input_path: str, out_path: str, debug: bool) -> Tuple[int, int]:
    """
    Write an AC energy heatmap and return block grid dimensions.
    """
    np, plt, image_module = dct_deps()
    t0 = time.perf_counter()
    y = load_luma(input_path, np, image_module)
    _, ac = block_maps(y, np)
    debug_log(debug, f"AC energy heatmap blocks: {ac.shape[0]}x{ac.shape[1]}")

    fig, ax = plt.subplots(1, 1, figsize=(10, 7))
    plot_heatmap(ax, ac, "AC Energy Heatmap (8x8 blocks)", "magma")
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    debug_log(debug, f"AC heatmap generation time: {time.perf_counter() - t0:.2f}s")
    return int(ac.shape[0]), int(ac.shape[1])

"""
GIF generation utilities for mutation outputs.
"""

import random
from typing import Any, List


def load_frames(paths: List[str], image_module: Any) -> List[Any]:
    """
    Load image frames from disk, converting each to RGB.
    """
    frames: List[Any] = []
    for p in paths:
        try:
            img = image_module.open(p)
            frames.append(img.convert("RGB"))
        except Exception:
            continue
    return frames


def write_gif(paths: List[str], out_path: str, fps: int, loop: int, seed: int, shuffle: bool) -> int:
    """
    Write a GIF from a list of image paths.

    Returns the number of frames written. If no frames decode, returns 0.
    """
    try:
        from PIL import Image
    except ImportError as e:
        raise RuntimeError(
            "Pillow is required for --gif. Install it with: python3 -m pip install pillow"
        ) from e

    if shuffle:
        rng = random.Random(seed)
        rng.shuffle(paths)
    frames = load_frames(paths, Image)
    if not frames:
        return 0
    duration_ms = max(1, int(1000 / max(1, fps)))
    frames[0].save(
        out_path,
        save_all=True,
        append_images=frames[1:],
        duration=duration_ms,
        loop=loop,
    )
    return len(frames)

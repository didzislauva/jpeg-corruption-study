"""
Tests for GIF generation utilities.
"""

from pathlib import Path

import pytest

from jpeg_fault.core import media


class _FakeLoaded:
    """
    Fake image object to emulate a Pillow Image instance.
    """
    def __init__(self, p: str) -> None:
        self.path = p

    def convert(self, mode: str):
        return (self.path, mode)


class _FakeImageModule:
    """
    Fake image module to simulate PIL.Image for load_frames testing.
    """
    @staticmethod
    def open(path: str):
        if path.endswith("bad.jpg"):
            raise OSError("bad")
        return _FakeLoaded(path)


def test_load_frames_skips_bad_entries() -> None:
    """
    Ensure load_frames skips unreadable files.
    """
    frames = media.load_frames(["ok.jpg", "bad.jpg", "ok2.jpg"], _FakeImageModule)
    assert len(frames) == 2


def test_write_gif_import_error_or_success(tmp_path: Path) -> None:
    """
    Verify write_gif behavior with and without Pillow.
    """
    try:
        from PIL import Image
    except Exception:
        with pytest.raises(RuntimeError):
            media.write_gif([], str(tmp_path / "x.gif"), fps=10, loop=0, seed=1, shuffle=False)
        return

    p1 = tmp_path / "a.jpg"
    p2 = tmp_path / "b.jpg"
    Image.new("RGB", (4, 4), "red").save(p1)
    Image.new("RGB", (4, 4), "blue").save(p2)

    out = tmp_path / "out.gif"
    n = media.write_gif([str(p1), str(p2)], str(out), fps=5, loop=0, seed=3, shuffle=True)
    assert n == 2
    assert out.exists()

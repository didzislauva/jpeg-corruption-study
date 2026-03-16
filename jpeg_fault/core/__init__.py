"""
Core package for the JPEG fault tolerance tool.

Exports the CLI `main()` for convenience so callers can run:
`python -m jpeg_fault.core` or import `jpeg_fault.core.main`.
"""

from .cli import main

__all__ = ["main"]

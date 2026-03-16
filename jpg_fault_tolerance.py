#!/usr/bin/env python3
"""
CLI entrypoint wrapper.

This script exists to provide a simple executable for running the JPEG fault
tolerance tool from the repository root. It delegates all behavior to the
core CLI module.
"""

from jpeg_fault.core.cli import main


if __name__ == "__main__":
    raise SystemExit(main())

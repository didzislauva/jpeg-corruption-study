"""
Debug logging utilities.
"""

import sys

def debug_log(enabled: bool, msg: str) -> None:
    """
    Print a debug message to stderr if enabled.
    """
    if enabled:
        print(f"[DEBUG] {msg}", file=sys.stderr)

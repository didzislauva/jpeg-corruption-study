"""
Debug logging utilities and optional function instrumentation.
"""

import sys
import time
from functools import wraps
from typing import Any, Callable, Dict, Optional, Set

_DEBUG_ENABLED = False

def debug_log(enabled: bool, msg: str) -> None:
    """
    Print a debug message to stderr if enabled.
    """
    if enabled:
        print(f"[DEBUG] {msg}", file=sys.stderr)


def set_debug(enabled: bool) -> None:
    """
    Enable or disable global debug instrumentation.
    """
    global _DEBUG_ENABLED
    _DEBUG_ENABLED = enabled


def is_debug() -> bool:
    """
    Return the current global debug instrumentation state.
    """
    return _DEBUG_ENABLED


def _short_value(v: Any) -> str:
    """
    Compact, type-aware string representation for logging.
    """
    if isinstance(v, bytes):
        return f"bytes(len={len(v)})"
    if isinstance(v, bytearray):
        return f"bytearray(len={len(v)})"
    if isinstance(v, str):
        return repr(v if len(v) <= 32 else v[:29] + "...")
    if isinstance(v, (list, tuple, set, dict)):
        return f"{type(v).__name__}(len={len(v)})"
    return f"{type(v).__name__}({repr(v)[:40]})"


def _summarize_call(args: tuple[Any, ...], kwargs: Dict[str, Any]) -> str:
    """
    Summarize positional and keyword arguments for debug logs.
    """
    parts = [_short_value(a) for a in args[:4]]
    if len(args) > 4:
        parts.append(f"...+{len(args) - 4} args")
    for k in list(kwargs.keys())[:4]:
        parts.append(f"{k}={_short_value(kwargs[k])}")
    if len(kwargs) > 4:
        parts.append(f"...+{len(kwargs) - 4} kwargs")
    return ", ".join(parts)


def instrument_module_functions(
    namespace: Dict[str, Any],
    *,
    module_name: Optional[str] = None,
    exclude: Optional[Set[str]] = None,
) -> None:
    """
    Wrap functions in a module namespace with debug entry/exit logging.

    This is an opt-in instrumentation helper, controlled by the global
    debug flag via set_debug().
    """
    excludes = set(exclude or set())
    mod = module_name or namespace.get("__name__", "")
    for name, obj in list(namespace.items()):
        if name in excludes or name.startswith("_"):
            continue
        if not callable(obj):
            continue
        if getattr(obj, "__module__", None) != mod:
            continue
        if getattr(obj, "__wrapped_by_debug__", False):
            continue

        @wraps(obj)
        def wrapper(*args: Any, __fn: Callable[..., Any] = obj, __name: str = name, **kwargs: Any) -> Any:
            if not is_debug():
                return __fn(*args, **kwargs)
            call = _summarize_call(args, kwargs)
            debug_log(True, f"ENTER {mod}.{__name}({call})")
            t0 = time.perf_counter()
            try:
                result = __fn(*args, **kwargs)
            except Exception as e:
                dt = time.perf_counter() - t0
                debug_log(True, f"RAISE {mod}.{__name} after {dt:.4f}s: {type(e).__name__}: {e}")
                raise
            dt = time.perf_counter() - t0
            debug_log(True, f"EXIT {mod}.{__name} after {dt:.4f}s -> {_short_value(result)}")
            return result

        setattr(wrapper, "__wrapped_by_debug__", True)
        namespace[name] = wrapper

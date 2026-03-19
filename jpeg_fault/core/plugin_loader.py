from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable, MutableMapping
from typing import TypeVar

from .debug import debug_log


PluginT = TypeVar("PluginT")
ModuleFilter = Callable[[str, bool], str | None]


def load_plugins_into(
    registry: MutableMapping[str, PluginT],
    *,
    force: bool,
    debug: bool,
    missing_package_message: str,
    module_error_label: str,
    module_filter: ModuleFilter,
) -> None:
    try:
        from . import plugins as plugins_pkg
    except ModuleNotFoundError:
        debug_log(debug, missing_package_message)
        return

    if force:
        registry.clear()

    if not force and registry:
        return

    prefix = plugins_pkg.__name__ + "."
    for module_info in pkgutil.iter_modules(plugins_pkg.__path__, prefix):
        target = module_filter(module_info.name.rsplit(".", 1)[-1], module_info.ispkg)
        if target is None:
            continue
        full_target = f"{module_info.name}.plugin" if module_info.ispkg else module_info.name
        if target == "module":
            full_target = module_info.name
        try:
            module = importlib.import_module(full_target)
            if force:
                importlib.reload(module)
        except ModuleNotFoundError as e:
            debug_log(debug, f"Skipping {module_error_label} {full_target}: {e}")
        except Exception as e:
            debug_log(debug, f"Failed to load {module_error_label} {full_target}: {e}")

from __future__ import annotations

from typing import Iterable
import importlib
import pkgutil

from .analysis_types import AnalysisPlugin
from .debug import debug_log


_PLUGINS: dict[str, AnalysisPlugin] = {}


def register(plugin: AnalysisPlugin) -> None:
    if plugin.id in _PLUGINS:
        raise ValueError(f"Plugin id already registered: {plugin.id}")
    _PLUGINS[plugin.id] = plugin


def get_plugins_for_format(fmt: str) -> list[AnalysisPlugin]:
    return sorted(
        [plugin for plugin in _PLUGINS.values() if fmt in plugin.supported_formats],
        key=lambda p: p.id,
    )


def get_plugin(plugin_id: str) -> AnalysisPlugin | None:
    return _PLUGINS.get(plugin_id)


def all_plugins() -> Iterable[AnalysisPlugin]:
    return _PLUGINS.values()


def clear_registry_for_tests() -> None:
    _PLUGINS.clear()


def load_plugins(force: bool = False, debug: bool = False) -> None:
    # Import built-in plugins to populate the registry.
    try:
        from . import plugins as plugins_pkg
    except ModuleNotFoundError:
        debug_log(debug, "Plugins package not found; skipping plugin load.")
        return

    if force:
        _PLUGINS.clear()

    if not force and _PLUGINS:
        return

    prefix = plugins_pkg.__name__ + "."
    for module_info in pkgutil.iter_modules(plugins_pkg.__path__, prefix):
        name = module_info.name
        if module_info.ispkg:
            target = f"{name}.plugin"
        else:
            target = name
        try:
            module = importlib.import_module(target)
            if force:
                importlib.reload(module)
        except ModuleNotFoundError as e:
            debug_log(debug, f"Skipping plugin {target}: {e}")
        except Exception as e:
            debug_log(debug, f"Failed to load plugin {target}: {e}")

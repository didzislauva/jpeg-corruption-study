from __future__ import annotations

from typing import Iterable

from .analysis_types import AnalysisPlugin
from .plugin_loader import load_plugins_into


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
    def module_filter(name: str, ispkg: bool) -> str | None:
        if name.startswith("_") or name.startswith("mutation_"):
            return None
        return "package" if ispkg else "module"

    load_plugins_into(
        _PLUGINS,
        force=force,
        debug=debug,
        missing_package_message="Plugins package not found; skipping plugin load.",
        module_error_label="plugin",
        module_filter=module_filter,
    )

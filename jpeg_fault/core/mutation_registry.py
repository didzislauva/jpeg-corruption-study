from __future__ import annotations

from typing import Iterable

from .mutation_types import MutationPlugin
from .plugin_loader import load_plugins_into


_MUTATION_PLUGINS: dict[str, MutationPlugin] = {}


def register(plugin: MutationPlugin) -> None:
    if plugin.id in _MUTATION_PLUGINS:
        raise ValueError(f"Mutation plugin id already registered: {plugin.id}")
    _MUTATION_PLUGINS[plugin.id] = plugin


def get_plugin(plugin_id: str) -> MutationPlugin | None:
    return _MUTATION_PLUGINS.get(plugin_id)


def all_plugins() -> Iterable[MutationPlugin]:
    return _MUTATION_PLUGINS.values()


def get_plugins_for_format(fmt: str) -> list[MutationPlugin]:
    return sorted(
        [plugin for plugin in _MUTATION_PLUGINS.values() if fmt in plugin.supported_formats],
        key=lambda p: p.id,
    )


def clear_registry_for_tests() -> None:
    _MUTATION_PLUGINS.clear()


def load_plugins(force: bool = False, debug: bool = False) -> None:
    def module_filter(name: str, ispkg: bool) -> str | None:
        if not name.startswith("mutation_"):
            return None
        return "package" if ispkg else "module"

    load_plugins_into(
        _MUTATION_PLUGINS,
        force=force,
        debug=debug,
        missing_package_message="Mutation plugins package not found; skipping mutation plugin load.",
        module_error_label="mutation plugin",
        module_filter=module_filter,
    )

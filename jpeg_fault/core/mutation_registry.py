from __future__ import annotations

from typing import Iterable
import importlib
import pkgutil

from .debug import debug_log
from .mutation_types import MutationPlugin


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
    try:
        from . import mutation_plugins as plugins_pkg
    except ModuleNotFoundError:
        debug_log(debug, "Mutation plugins package not found; skipping mutation plugin load.")
        return

    if force:
        _MUTATION_PLUGINS.clear()

    if not force and _MUTATION_PLUGINS:
        return

    prefix = plugins_pkg.__name__ + "."
    for module_info in pkgutil.iter_modules(plugins_pkg.__path__, prefix):
        name = module_info.name
        target = f"{name}.plugin" if module_info.ispkg else name
        try:
            module = importlib.import_module(target)
            if force:
                importlib.reload(module)
        except ModuleNotFoundError as e:
            debug_log(debug, f"Skipping mutation plugin {target}: {e}")
        except Exception as e:
            debug_log(debug, f"Failed to load mutation plugin {target}: {e}")

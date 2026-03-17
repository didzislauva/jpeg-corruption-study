from __future__ import annotations

from typing import Iterable

from .tui_plugin_types import TuiPluginSpec


_TUI_PLUGINS: dict[str, TuiPluginSpec] = {}


def register_tui_plugin(spec: TuiPluginSpec) -> None:
    if spec.id in _TUI_PLUGINS:
        raise ValueError(f"TUI plugin id already registered: {spec.id}")
    _TUI_PLUGINS[spec.id] = spec


def all_tui_plugins() -> Iterable[TuiPluginSpec]:
    return _TUI_PLUGINS.values()


def clear_tui_plugins_for_tests() -> None:
    _TUI_PLUGINS.clear()

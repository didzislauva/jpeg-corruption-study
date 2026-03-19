from __future__ import annotations

from ...mutation_registry import register
from ...tui_plugin_registry import register_tui_plugin
from ...tui_plugin_types import TuiPluginSpec
from ...mutation_plugin_helpers import FixedByteMutationPlugin


plugin = FixedByteMutationPlugin(id="aa", label="AA Mutation", target_byte=0xAA, tag="aa")
register(plugin)

register_tui_plugin(
    TuiPluginSpec(
        id="aa",
        label="AA Mutation",
        panel_id="mutation-output",
        panel_label="Plugin Mutations",
        tab_label="AA Mutation",
        mutation_plugin_id="aa",
    )
)

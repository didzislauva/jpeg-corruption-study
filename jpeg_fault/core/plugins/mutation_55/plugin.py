from __future__ import annotations

from ...mutation_registry import register
from ...tui_plugin_registry import register_tui_plugin
from ...tui_plugin_types import TuiPluginSpec
from ...mutation_plugin_helpers import FixedByteMutationPlugin


plugin = FixedByteMutationPlugin(id="55", label="55 Mutation", target_byte=0x55, tag="55")
register(plugin)

register_tui_plugin(
    TuiPluginSpec(
        id="55",
        label="55 Mutation",
        panel_id="mutation-output",
        panel_label="Plugin Mutations",
        tab_label="55 Mutation",
        mutation_plugin_id="55",
    )
)

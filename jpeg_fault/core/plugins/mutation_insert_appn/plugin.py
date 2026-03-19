from __future__ import annotations

from pathlib import Path

from ...analysis_types import PluginParamSpec
from ...mutation_registry import register
from ...mutation_types import MutationContext, MutationPlugin, MutationResult
from ...tools import insert_custom_appn, mutation_output_path_for, resolve_appn_payload
from ...tui_plugin_registry import register_tui_plugin
from ...tui_plugin_types import TuiPluginSpec


class InsertAppnMutationPlugin(MutationPlugin):
    id = "insert_appn"
    label = "Insert APPn"
    supported_formats = {"jpeg"}
    params_spec = (
        PluginParamSpec(name="appn", label="APPn index", type="int", required=True, default=15),
        PluginParamSpec(name="identifier", label="Identifier prefix", default="", help="Optional ASCII prefix."),
        PluginParamSpec(name="payload_hex", label="Payload hex", default="", help="Whitespace is allowed."),
        PluginParamSpec(name="payload_file", label="Payload file", type="path", default="", help="Use instead of payload hex."),
        PluginParamSpec(name="output_path", label="Output path", type="path", default="", help="Blank writes to output_dir/<stem>_appNN.jpg."),
    )
    needs = frozenset({"source_bytes"})

    def run(self, input_path: str, context: MutationContext) -> MutationResult:
        if context.source_bytes is None:
            raise ValueError("Insert APPn mutation plugin requires source bytes.")
        params = dict(context.params or {})
        appn = int(params.get("appn", 15))
        payload = resolve_appn_payload(
            str(params.get("payload_hex", "")).strip(),
            str(params.get("payload_file", "")).strip(),
            str(params.get("identifier", "")),
        )
        out_data = insert_custom_appn(context.source_bytes, appn, payload)
        out_path = mutation_output_path_for(
            input_path,
            context.output_dir,
            appn,
            str(params.get("output_path", "")).strip() or None,
        )
        Path(out_path).write_bytes(out_data)
        return MutationResult(self.id, [out_path], {"appn": appn, "payload_len": len(payload)})


plugin = InsertAppnMutationPlugin()
register(plugin)

register_tui_plugin(
    TuiPluginSpec(
        id="insert_appn",
        label="Insert APPn",
        panel_id="tools",
        panel_label="Tools",
        tab_label="Insert APPn",
        mutation_plugin_id="insert_appn",
    )
)

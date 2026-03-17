from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Optional, Protocol


ParamType = Literal["string", "int", "bool", "path", "choice"]
PluginNeed = Literal["source_bytes", "parsed_jpeg", "entropy_ranges", "decoded_image", "mutation_outputs"]


@dataclass(frozen=True)
class PluginParamSpec:
    name: str
    label: str
    type: ParamType = "string"
    required: bool = False
    default: Any = None
    help: str = ""
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class AnalysisContext:
    input_path: str = ""
    format: str = "unknown"
    output_dir: str = ""
    debug: bool = False
    params: dict[str, Any] | None = None
    source_bytes: Optional[bytes] = None
    segments: Optional[list[Any]] = None
    entropy_ranges: Optional[list[Any]] = None
    decoded_image: Any = None
    mutation_paths: Optional[list[str]] = None


@dataclass(frozen=True)
class AnalysisResult:
    plugin_id: str
    outputs: list[str]
    details: dict[str, Any] | None = None


class AnalysisPlugin(Protocol):
    id: str
    label: str
    supported_formats: set[str]
    requires_mutations: bool
    params_spec: tuple[PluginParamSpec, ...]
    needs: frozenset[PluginNeed]

    def run(self, input_path: str, context: AnalysisContext) -> AnalysisResult:
        ...


def validate_plugin_params(plugin: AnalysisPlugin, raw_params: Mapping[str, str] | None) -> dict[str, Any]:
    """
    Validate and coerce raw plugin params against the plugin's declared spec.
    """
    raw = dict(raw_params or {})
    specs = tuple(getattr(plugin, "params_spec", ()) or ())
    spec_by_name = {spec.name: spec for spec in specs}
    unknown = sorted(name for name in raw if name not in spec_by_name)
    if unknown:
        raise ValueError(f"Plugin {plugin.id} does not accept params: {', '.join(unknown)}")

    resolved: dict[str, Any] = {}
    for spec in specs:
        if spec.name in raw:
            resolved[spec.name] = _coerce_plugin_param(plugin.id, spec, raw[spec.name])
            continue
        if spec.required and spec.default is None:
            raise ValueError(f"Plugin {plugin.id} requires param: {spec.name}")
        if spec.default is not None:
            resolved[spec.name] = spec.default
    return resolved


def _coerce_plugin_param(plugin_id: str, spec: PluginParamSpec, raw: str) -> Any:
    value = raw.strip()
    if spec.type in {"string", "path"}:
        return value
    if spec.type == "int":
        try:
            return int(value)
        except ValueError as e:
            raise ValueError(f"Plugin {plugin_id} param {spec.name} must be an integer.") from e
    if spec.type == "bool":
        lowered = value.lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"Plugin {plugin_id} param {spec.name} must be a boolean.")
    if spec.type == "choice":
        if spec.choices and value not in spec.choices:
            choices = ", ".join(spec.choices)
            raise ValueError(f"Plugin {plugin_id} param {spec.name} must be one of: {choices}")
        return value
    raise ValueError(f"Plugin {plugin_id} param {spec.name} has unsupported type: {spec.type}")

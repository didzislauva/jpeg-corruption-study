from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol

from .analysis_types import PluginNeed, PluginParamSpec


@dataclass(frozen=True)
class MutationContext:
    input_path: str = ""
    format: str = "unknown"
    output_dir: str = ""
    debug: bool = False
    mutation_apply: str = "independent"
    repeats: int = 1
    step: int = 1
    params: dict[str, Any] | None = None
    source_bytes: Optional[bytes] = None
    segments: Optional[list[Any]] = None
    entropy_ranges: Optional[list[Any]] = None


@dataclass(frozen=True)
class MutationResult:
    plugin_id: str
    outputs: list[str]
    details: dict[str, Any] | None = None


class MutationPlugin(Protocol):
    id: str
    label: str
    supported_formats: set[str]
    params_spec: tuple[PluginParamSpec, ...]
    needs: frozenset[PluginNeed]

    def run(self, input_path: str, context: MutationContext) -> MutationResult:
        ...

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class AnalysisContext:
    output_dir: str
    debug: bool = False
    params: dict[str, Any] | None = None


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

    def run(self, input_path: str, context: AnalysisContext) -> AnalysisResult:
        ...

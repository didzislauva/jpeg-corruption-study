from __future__ import annotations

from dataclasses import dataclass

from jpeg_fault.core import analysis_registry as reg
from jpeg_fault.core.analysis_types import AnalysisContext, AnalysisResult, AnalysisPlugin, PluginParamSpec


@dataclass(frozen=True)
class DummyPlugin(AnalysisPlugin):
    id: str
    label: str
    supported_formats: set[str]
    requires_mutations: bool = False
    params_spec: tuple[PluginParamSpec, ...] = ()

    def run(self, input_path: str, context: AnalysisContext) -> AnalysisResult:
        return AnalysisResult(self.id, [])


def test_registry_filters_by_format() -> None:
    reg.clear_registry_for_tests()
    reg.register(DummyPlugin("a", "A", {"jpeg"}))
    reg.register(DummyPlugin("b", "B", {"png"}))
    reg.register(DummyPlugin("c", "C", {"jpeg", "png"}))

    jpeg = [p.id for p in reg.get_plugins_for_format("jpeg")]
    png = [p.id for p in reg.get_plugins_for_format("png")]

    assert jpeg == ["a", "c"]
    assert png == ["b", "c"]

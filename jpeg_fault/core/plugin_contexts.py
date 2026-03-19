from __future__ import annotations

from typing import Any

from .analysis_types import AnalysisContext
from .models import EntropyRange, Segment
from .mutation_types import MutationContext


def build_analysis_context(
    *,
    plugin: Any,
    input_path: str,
    fmt: str,
    output_dir: str,
    debug: bool,
    params: dict[str, object],
    data: bytes,
    segments: list[Segment],
    entropy_ranges: list[EntropyRange],
    mutation_paths: list[str],
    decoded_image: Any = None,
) -> AnalysisContext:
    needs = set(getattr(plugin, "needs", frozenset()))
    return AnalysisContext(
        input_path=input_path,
        format=fmt,
        output_dir=output_dir,
        debug=debug,
        params=params,
        source_bytes=data if "source_bytes" in needs else None,
        segments=segments if "parsed_jpeg" in needs else None,
        entropy_ranges=entropy_ranges if "entropy_ranges" in needs else None,
        decoded_image=decoded_image if "decoded_image" in needs else None,
        mutation_paths=mutation_paths if "mutation_outputs" in needs else None,
    )


def build_mutation_context(
    *,
    plugin: Any,
    input_path: str,
    fmt: str,
    output_dir: str,
    debug: bool,
    mutation_apply: str = "independent",
    repeats: int = 1,
    step: int = 1,
    params: dict[str, object],
    data: bytes,
    segments: list[Segment],
    entropy_ranges: list[EntropyRange],
) -> MutationContext:
    needs = set(getattr(plugin, "needs", frozenset()))
    return MutationContext(
        input_path=input_path,
        format=fmt,
        output_dir=output_dir,
        debug=debug,
        mutation_apply=mutation_apply,
        repeats=repeats,
        step=step,
        params=params,
        source_bytes=data if "source_bytes" in needs else None,
        segments=segments if "parsed_jpeg" in needs else None,
        entropy_ranges=entropy_ranges if "entropy_ranges" in needs else None,
    )

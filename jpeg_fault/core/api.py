from __future__ import annotations

"""
Core API for programmatic use by CLI, future TUI, or GUI frontends.

This module centralizes the orchestration of:
- JPEG parsing and reporting
- Mutation generation and post-processing
- Source-only analysis (wave charts and heatmaps)
"""

import os
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from .analysis_registry import get_plugin, load_plugins
from .analysis_types import AnalysisContext, AnalysisResult, validate_plugin_params
from .debug import debug_log
from .format_detect import detect_format
from .jpeg_parse import parse_jpeg
from .media import write_gif
from .models import EntropyRange, Segment
from .mutate import list_mutation_files, parse_mutation_mode, total_entropy_length, write_mutations
from .plugin_contexts import build_analysis_context, build_mutation_context
from .mutation_registry import get_plugin as get_mutation_plugin, load_plugins as load_mutation_plugins
from .mutation_types import MutationContext
from .report import print_report
from .ssim_analysis import parse_metrics_list, write_metric_panels, write_ssim_panels
from .wave_analysis import write_sliding_wave_chart, write_wave_chart


@dataclass(frozen=True)
class RunOptions:
    """
    Immutable configuration for a full execution.

    This mirrors CLI flags and is intended to be used by external frontends.
    """
    input_path: str
    output_dir: str
    mutate: str
    sample: int
    seed: int
    mutation_apply: str
    repeats: int
    step: int
    overflow_wrap: bool
    report_only: bool
    color: str
    gif: Optional[str]
    gif_fps: int
    gif_loop: int
    gif_shuffle: bool
    ssim_chart: Optional[str]
    metrics: str
    metrics_chart_prefix: Optional[str]
    jobs: Optional[int]
    analysis: str
    analysis_params: List[str]
    mutation_plugins: str
    mutation_plugin_params: List[str]
    wave_chart: Optional[str]
    sliding_wave_chart: Optional[str]
    wave_window: int
    dc_heatmap: Optional[str]
    ac_energy_heatmap: Optional[str]
    debug: bool


@dataclass(frozen=True)
class RunResult:
    """
    Summary of outputs produced by a run.
    """
    mutation_count: int
    gif_frames: Optional[int]
    ssim_sets: Optional[int]
    metric_sets: Dict[str, int]
    plugin_results: Dict[str, List[str]]
    mutation_plugin_results: Dict[str, List[str]]
    wave_len: Optional[int]
    sliding_len: Optional[int]
    dc_blocks: Optional[Tuple[int, int]]
    ac_blocks: Optional[Tuple[int, int]]
    source_only_mode: bool


def log_run_context(args: RunOptions, data: bytes, segments: List[Segment], entropy_ranges: List[EntropyRange]) -> None:
    """
    Emit a concise debug summary of the run context.
    """
    debug_log(
        args.debug,
        (
            f"Input bytes={len(data)}, segments={len(segments)}, scans={len(entropy_ranges)}, "
            f"entropy_total={total_entropy_length(entropy_ranges)}"
        ),
    )
    debug_log(
        args.debug,
        (
            f"Options: mode={args.mutate}, apply={args.mutation_apply}, sample={args.sample}, "
            f"repeats={args.repeats}, step={args.step}, seed={args.seed}, "
            f"overflow_wrap={args.overflow_wrap}, output={args.output_dir}, jobs={args.jobs}"
        ),
    )


def validate_runtime_args(args: RunOptions) -> Optional[str]:
    """
    Validate run options that are contextual to mutation strategy.
    """
    if args.mutation_apply not in {"cumulative", "sequential"} and args.repeats != 1:
        return "--repeats is only supported with --mutation-apply cumulative or sequential."
    if args.mutation_apply not in {"cumulative", "sequential"} and args.step != 1:
        return "--step is only supported with --mutation-apply cumulative or sequential."
    if args.step < 1:
        return f"--step must be >= 1, got {args.step}"
    if args.wave_window < 1:
        return f"--wave-window must be >= 1, got {args.wave_window}"
    return None


def new_mutation_paths(output_dir: str, base_name: str, before: Set[str]) -> List[str]:
    """
    Compute newly created mutation file paths from before/after snapshots.
    """
    after = set(list_mutation_files(output_dir, base_name))
    return sorted(after - before)


def run_mutation_phase(
    args: RunOptions,
    data: bytes,
    entropy_ranges: List[EntropyRange],
    base_name: str,
    mode: str,
    bits: Optional[List[int]],
) -> int:
    """
    Generate mutation files according to the selected strategy and mode.
    """
    t_mut = time.perf_counter()
    count = write_mutations(
        data,
        entropy_ranges,
        args.output_dir,
        base_name,
        mode,
        bits,
        args.overflow_wrap,
        args.sample,
        args.seed,
        args.mutation_apply,
        args.repeats,
        args.step,
        args.debug,
    )
    debug_log(args.debug, f"Mutation generation time: {time.perf_counter() - t_mut:.2f}s")
    return count


def run_gif_phase(args: RunOptions, base_name: str) -> int:
    """
    Build a GIF from all matching mutation files in output_dir.
    """
    paths = list_mutation_files(args.output_dir, base_name)
    debug_log(args.debug, f"GIF input files matched: {len(paths)}")
    return write_gif(paths, args.gif, args.gif_fps, args.gif_loop, args.seed, args.gif_shuffle)


def run_gif_phase_for_paths(args: RunOptions, paths: List[str]) -> int:
    """
    Build a GIF from a specific list of mutation paths.
    """
    debug_log(args.debug, f"GIF input files (current run): {len(paths)}")
    return write_gif(paths, args.gif, args.gif_fps, args.gif_loop, args.seed, args.gif_shuffle)


def run_ssim_phase(args: RunOptions, base_name: str) -> int:
    """
    Generate SSIM panels from all matching mutation files in output_dir.
    """
    paths = list_mutation_files(args.output_dir, base_name)
    debug_log(args.debug, f"SSIM input files matched: {len(paths)}")
    t_ssim = time.perf_counter()
    set_count = write_ssim_panels(args.input_path, paths, args.ssim_chart, args.jobs, args.debug)
    debug_log(args.debug, f"SSIM panel generation time: {time.perf_counter() - t_ssim:.2f}s")
    return set_count


def run_ssim_phase_for_paths(args: RunOptions, paths: List[str]) -> int:
    """
    Generate SSIM panels from a specific list of mutation paths.
    """
    debug_log(args.debug, f"SSIM input files (current run): {len(paths)}")
    t_ssim = time.perf_counter()
    set_count = write_ssim_panels(args.input_path, paths, args.ssim_chart, args.jobs, args.debug)
    debug_log(args.debug, f"SSIM panel generation time: {time.perf_counter() - t_ssim:.2f}s")
    return set_count


def run_metrics_phase_for_paths(args: RunOptions, paths: List[str]) -> Dict[str, int]:
    """
    Generate metric panels (SSIM/PSNR/MSE/MAE) for a specific list of paths.
    """
    metrics = parse_metrics_list(args.metrics)
    debug_log(args.debug, f"Metrics selected: {metrics}")
    results: Dict[str, int] = {}
    for metric in metrics:
        out_path = f"{args.metrics_chart_prefix}_{metric}.png"
        t0 = time.perf_counter()
        set_count = write_metric_panels(args.input_path, paths, out_path, args.jobs, args.debug, metric)
        debug_log(args.debug, f"{metric.upper()} panel generation time: {time.perf_counter() - t0:.2f}s")
        results[out_path] = set_count
    return results


def run_wave_phase(args: RunOptions, data: bytes, entropy_ranges: List[EntropyRange]) -> int:
    """
    Write a 2-panel wave chart of the entropy stream.
    """
    t0 = time.perf_counter()
    result = _run_analysis_plugin(
        args=args,
        plugin_id="entropy_wave",
        mutation_count=0,
        raw_param_map={"entropy_wave": {"out_path": str(args.wave_chart), "mode": "both"}},
        data=data,
        segments=[],
        entropy_ranges=entropy_ranges,
        mutation_paths=[],
        fmt="jpeg",
    )
    stream_len = int((result.details or {}).get("stream_len", total_entropy_length(entropy_ranges)))
    debug_log(args.debug, f"Wave chart generation time: {time.perf_counter() - t0:.2f}s")
    return stream_len


def run_sliding_wave_phase(args: RunOptions, data: bytes, entropy_ranges: List[EntropyRange]) -> int:
    """
    Write a 3-panel sliding window chart over the entropy stream.
    """
    t0 = time.perf_counter()
    result = _run_analysis_plugin(
        args=args,
        plugin_id="sliding_wave",
        mutation_count=0,
        raw_param_map={
            "sliding_wave": {
                "out_path": str(args.sliding_wave_chart),
                "window": str(args.wave_window),
                "stats": "mean,variance,entropy",
            }
        },
        data=data,
        segments=[],
        entropy_ranges=entropy_ranges,
        mutation_paths=[],
        fmt="jpeg",
    )
    stream_len = int((result.details or {}).get("stream_len", total_entropy_length(entropy_ranges)))
    debug_log(args.debug, f"Sliding wave chart generation time: {time.perf_counter() - t0:.2f}s")
    return stream_len


def run_dc_heatmap_phase(args: RunOptions) -> Tuple[int, int]:
    """
    Write a DC heatmap and return block grid dimensions.
    """
    t0 = time.perf_counter()
    result = _run_analysis_plugin(
        args=args,
        plugin_id="dc_heatmap",
        mutation_count=0,
        raw_param_map={"dc_heatmap": {"out_path": str(args.dc_heatmap)}},
        data=b"",
        segments=[],
        entropy_ranges=[],
        mutation_paths=[],
        fmt="jpeg",
    )
    details = result.details or {}
    block_rows = int(details.get("block_rows", 0))
    block_cols = int(details.get("block_cols", 0))
    debug_log(args.debug, f"DC heatmap generation time: {time.perf_counter() - t0:.2f}s")
    return block_rows, block_cols


def run_ac_heatmap_phase(args: RunOptions) -> Tuple[int, int]:
    """
    Write an AC energy heatmap and return block grid dimensions.
    """
    t0 = time.perf_counter()
    result = _run_analysis_plugin(
        args=args,
        plugin_id="ac_energy_heatmap",
        mutation_count=0,
        raw_param_map={"ac_energy_heatmap": {"out_path": str(args.ac_energy_heatmap)}},
        data=b"",
        segments=[],
        entropy_ranges=[],
        mutation_paths=[],
        fmt="jpeg",
    )
    details = result.details or {}
    block_rows = int(details.get("block_rows", 0))
    block_cols = int(details.get("block_cols", 0))
    debug_log(args.debug, f"AC heatmap generation time: {time.perf_counter() - t0:.2f}s")
    return block_rows, block_cols


def run(args: RunOptions, emit_report: bool = True) -> RunResult:
    """
    Run the full pipeline and return a structured result summary.
    """
    t_start = time.perf_counter()
    data, segments, entropy_ranges = _load_and_parse(args)
    if emit_report:
        print_report(args.input_path, data, segments, entropy_ranges, args.color)

    plugin_ids = _parse_plugin_list(args.analysis)
    mutation_plugin_ids = _parse_plugin_list(args.mutation_plugins)
    if args.report_only and not plugin_ids and not mutation_plugin_ids:
        return _empty_result()

    _validate_args_or_raise(args)
    source_only_mode = _is_source_only_mode(args)

    mutation_count, created_paths, mutation_plugin_results, gif_frames, ssim_sets, metric_sets = _maybe_run_mutations(
        args, data, segments, entropy_ranges, source_only_mode, mutation_plugin_ids
    )
    wave_len, sliding_len, dc_blocks, ac_blocks = _run_source_only(args, data, entropy_ranges)
    plugin_results = _run_plugins(args, plugin_ids, mutation_count, data, segments, entropy_ranges, created_paths)

    debug_log(args.debug, f"Total runtime: {time.perf_counter() - t_start:.2f}s")
    return RunResult(
        mutation_count=mutation_count,
        gif_frames=gif_frames,
        ssim_sets=ssim_sets,
        metric_sets=metric_sets,
        plugin_results=plugin_results,
        mutation_plugin_results=mutation_plugin_results,
        wave_len=wave_len,
        sliding_len=sliding_len,
        dc_blocks=dc_blocks,
        ac_blocks=ac_blocks,
        source_only_mode=source_only_mode,
    )


def _load_and_parse(args: RunOptions) -> Tuple[bytes, List[Segment], List[EntropyRange]]:
    """
    Load input bytes and parse JPEG segments and entropy ranges.
    """
    with open(args.input_path, "rb") as f:
        data = f.read()
    segments, entropy_ranges = parse_jpeg(data)
    log_run_context(args, data, segments, entropy_ranges)
    return data, segments, entropy_ranges


def _empty_result() -> RunResult:
    """
    Build an empty result for report-only mode.
    """
    return RunResult(
        mutation_count=0,
        gif_frames=None,
        ssim_sets=None,
        metric_sets={},
        plugin_results={},
        mutation_plugin_results={},
        wave_len=None,
        sliding_len=None,
        dc_blocks=None,
        ac_blocks=None,
        source_only_mode=False,
    )


def _validate_args_or_raise(args: RunOptions) -> None:
    """
    Validate arguments and raise ValueError if invalid.
    """
    err = validate_runtime_args(args)
    if err:
        raise ValueError(err)


def _is_source_only_mode(args: RunOptions) -> bool:
    """
    Determine if only source-only outputs are requested.
    """
    mutation_dependent_outputs = bool(
        args.gif or args.ssim_chart or args.metrics_chart_prefix or args.mutation_plugins
    )
    source_only_outputs = bool(
        args.wave_chart or args.sliding_wave_chart or args.dc_heatmap or args.ac_energy_heatmap
    )
    return source_only_outputs and not mutation_dependent_outputs


def _parse_plugin_list(spec: str) -> List[str]:
    if not spec:
        return []
    parts = [part.strip() for part in spec.split(",")]
    return [part for part in parts if part]


def _run_plugins(
    args: RunOptions,
    plugin_ids: List[str],
    mutation_count: int,
    data: Optional[bytes] = None,
    segments: Optional[List[Segment]] = None,
    entropy_ranges: Optional[List[EntropyRange]] = None,
    mutation_paths: Optional[List[str]] = None,
) -> Dict[str, List[str]]:
    if not plugin_ids:
        return {}
    load_plugins(debug=args.debug)
    fmt = detect_format(args.input_path)
    if data is None:
        with open(args.input_path, "rb") as f:
            data = f.read()
    if fmt == "jpeg" and (segments is None or entropy_ranges is None):
        segments, entropy_ranges = parse_jpeg(data)
    if segments is None:
        segments = []
    if entropy_ranges is None:
        entropy_ranges = []
    if mutation_paths is None:
        mutation_paths = []
    raw_param_map = _parse_analysis_params(args.analysis_params)
    extra = sorted(pid for pid in raw_param_map if pid not in plugin_ids)
    if extra:
        raise ValueError(f"Analysis params provided for unselected plugin(s): {', '.join(extra)}")
    results: Dict[str, List[str]] = {}
    for plugin_id in plugin_ids:
        result = _run_analysis_plugin(
            args=args,
            plugin_id=plugin_id,
            mutation_count=mutation_count,
            raw_param_map=raw_param_map,
            data=data,
            segments=segments,
            entropy_ranges=entropy_ranges,
            mutation_paths=mutation_paths,
            fmt=fmt,
        )
        results[plugin_id] = result.outputs
    return results


def _run_analysis_plugin(
    *,
    args: RunOptions,
    plugin_id: str,
    mutation_count: int,
    raw_param_map: Dict[str, Dict[str, str]],
    data: bytes,
    segments: List[Segment],
    entropy_ranges: List[EntropyRange],
    mutation_paths: List[str],
    fmt: Optional[str] = None,
) -> AnalysisResult:
    load_plugins(debug=args.debug)
    resolved_fmt = fmt or detect_format(args.input_path)
    plugin = get_plugin(plugin_id)
    if plugin is None:
        load_plugins(force=True, debug=args.debug)
        plugin = get_plugin(plugin_id)
    if plugin is None:
        raise ValueError(f"Unknown analysis plugin: {plugin_id}")
    if resolved_fmt not in plugin.supported_formats:
        raise ValueError(f"Plugin {plugin_id} does not support format {resolved_fmt}")
    if plugin.requires_mutations and mutation_count == 0:
        raise ValueError(f"Plugin {plugin_id} requires mutations, but none were generated.")
    params = validate_plugin_params(plugin, raw_param_map.get(plugin_id))
    context = build_analysis_context(
        plugin=plugin,
        input_path=args.input_path,
        fmt=resolved_fmt,
        output_dir=args.output_dir,
        debug=args.debug,
        params=params,
        data=data,
        segments=segments,
        entropy_ranges=entropy_ranges,
        mutation_paths=mutation_paths,
        decoded_image=_decode_image(args.input_path) if "decoded_image" in getattr(plugin, "needs", frozenset()) else None,
    )
    return plugin.run(args.input_path, context)


def _parse_analysis_params(entries: List[str]) -> Dict[str, Dict[str, str]]:
    params: Dict[str, Dict[str, str]] = {}
    for entry in entries:
        plugin_key, sep, raw_value = entry.partition("=")
        if not sep:
            raise ValueError(f"Invalid analysis param {entry!r}; expected plugin.param=value")
        plugin_id, dot, param_name = plugin_key.partition(".")
        if not dot or not plugin_id or not param_name:
            raise ValueError(f"Invalid analysis param {entry!r}; expected plugin.param=value")
        plugin_params = params.setdefault(plugin_id, {})
        if param_name in plugin_params:
            raise ValueError(f"Duplicate analysis param for {plugin_id}.{param_name}")
        plugin_params[param_name] = raw_value
    return params

def _decode_image(input_path: str):
    try:
        from PIL import Image
    except ImportError as e:
        raise RuntimeError(
            "Plugin requires decoded_image but Pillow is not installed. "
            "Install with: python3 -m pip install pillow"
        ) from e
    return Image.open(input_path).convert("RGB")


def _run_mutation_plugins(
    args: RunOptions,
    plugin_ids: List[str],
    data: bytes,
    segments: List[Segment],
    entropy_ranges: List[EntropyRange],
) -> Dict[str, List[str]]:
    if not plugin_ids:
        return {}
    load_mutation_plugins(debug=args.debug)
    fmt = detect_format(args.input_path)
    raw_param_map = _parse_analysis_params(args.mutation_plugin_params)
    extra = sorted(pid for pid in raw_param_map if pid not in plugin_ids)
    if extra:
        raise ValueError(f"Mutation plugin params provided for unselected plugin(s): {', '.join(extra)}")
    results: Dict[str, List[str]] = {}
    for plugin_id in plugin_ids:
        plugin = get_mutation_plugin(plugin_id)
        if plugin is None:
            raise ValueError(f"Unknown mutation plugin: {plugin_id}")
        if fmt not in plugin.supported_formats:
            raise ValueError(f"Mutation plugin {plugin_id} does not support format {fmt}")
        params = validate_plugin_params(plugin, raw_param_map.get(plugin_id))
        context = build_mutation_context(
            plugin=plugin,
            input_path=args.input_path,
            fmt=fmt,
            output_dir=args.output_dir,
            debug=args.debug,
            mutation_apply=args.mutation_apply,
            repeats=args.repeats,
            step=args.step,
            params=params,
            data=data,
            segments=segments,
            entropy_ranges=entropy_ranges,
        )
        result = plugin.run(args.input_path, context)
        results[plugin_id] = result.outputs
    return results


def _maybe_run_mutations(
    args: RunOptions,
    data: bytes,
    segments: List[Segment],
    entropy_ranges: List[EntropyRange],
    source_only_mode: bool,
    mutation_plugin_ids: List[str],
) -> Tuple[int, List[str], Dict[str, List[str]], Optional[int], Optional[int], Dict[str, int]]:
    """
    Run mutations and mutation-dependent analyses if needed.
    """
    if source_only_mode:
        debug_log(args.debug, "Source-only analysis mode: skipping mutation generation.")
        return 0, [], {}, None, None, {}

    mode, bits = parse_mutation_mode(args.mutate)
    base_name = os.path.splitext(os.path.basename(args.input_path))[0]
    before_paths = set(list_mutation_files(args.output_dir, base_name))
    builtin_mutation_count = run_mutation_phase(args, data, entropy_ranges, base_name, mode, bits)
    created_paths = new_mutation_paths(args.output_dir, base_name, before_paths)
    if not created_paths:
        created_paths = list_mutation_files(args.output_dir, base_name)
    mutation_plugin_results = _run_mutation_plugins(args, mutation_plugin_ids, data, segments, entropy_ranges)
    plugin_paths = sorted({path for outputs in mutation_plugin_results.values() for path in outputs})
    created_paths = sorted(set(created_paths) | set(plugin_paths))
    debug_log(args.debug, f"Mutation files considered for post-processing: {len(created_paths)}")

    gif_frames = run_gif_phase_for_paths(args, created_paths) if args.gif else None
    ssim_sets = run_ssim_phase_for_paths(args, created_paths) if args.ssim_chart else None
    metric_sets = run_metrics_phase_for_paths(args, created_paths) if args.metrics_chart_prefix else {}
    return builtin_mutation_count + len(plugin_paths), created_paths, mutation_plugin_results, gif_frames, ssim_sets, metric_sets


def _run_source_only(
    args: RunOptions, data: bytes, entropy_ranges: List[EntropyRange]
) -> Tuple[Optional[int], Optional[int], Optional[Tuple[int, int]], Optional[Tuple[int, int]]]:
    """
    Run source-only analyses (wave charts and heatmaps).
    """
    wave_len = run_wave_phase(args, data, entropy_ranges) if args.wave_chart else None
    sliding_len = run_sliding_wave_phase(args, data, entropy_ranges) if args.sliding_wave_chart else None
    dc_blocks = run_dc_heatmap_phase(args) if args.dc_heatmap else None
    ac_blocks = run_ac_heatmap_phase(args) if args.ac_energy_heatmap else None
    return wave_len, sliding_len, dc_blocks, ac_blocks

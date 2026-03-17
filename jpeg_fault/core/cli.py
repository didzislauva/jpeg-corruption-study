"""
Command-line interface for the JPEG fault tolerance tool.

This module parses CLI arguments and delegates all behavior to the core API.
It preserves user-facing output formatting and exit codes.
"""

import argparse
import os
from typing import Dict, List, Optional, Tuple

from . import api
from .api import RunOptions, RunResult
from .models import EntropyRange, Segment


def parse_args() -> argparse.Namespace:
    """
    Parse CLI arguments into an argparse Namespace.
    """
    parser = argparse.ArgumentParser(description="JPEG fault tolerance mutator and reporter")
    parser.add_argument("input", nargs="?", help="Input JPEG file (omit when using --tui)")
    _add_mutation_args(parser)
    _add_output_args(parser)
    _add_analysis_args(parser)
    _add_misc_args(parser)
    return parser.parse_args()


def to_run_options(args: argparse.Namespace) -> RunOptions:
    """
    Convert CLI args into a RunOptions object for the API layer.
    """
    return RunOptions(
        input_path=args.input,
        output_dir=args.output_dir,
        mutate=args.mutate,
        sample=args.sample,
        seed=args.seed,
        mutation_apply=args.mutation_apply,
        repeats=args.repeats,
        step=args.step,
        overflow_wrap=args.overflow_wrap,
        report_only=args.report_only,
        color=args.color,
        gif=args.gif,
        gif_fps=args.gif_fps,
        gif_loop=args.gif_loop,
        gif_shuffle=args.gif_shuffle,
        ssim_chart=args.ssim_chart,
        metrics=args.metrics,
        metrics_chart_prefix=args.metrics_chart_prefix,
        jobs=args.jobs,
        analysis=args.analysis,
        analysis_params=args.analysis_param or [],
        mutation_plugins=args.mutation_plugin,
        mutation_plugin_params=args.mutation_plugin_param or [],
        wave_chart=args.wave_chart,
        sliding_wave_chart=args.sliding_wave_chart,
        wave_window=args.wave_window,
        dc_heatmap=args.dc_heatmap,
        ac_energy_heatmap=args.ac_energy_heatmap,
        debug=args.debug,
    )


def log_run_context(args: argparse.Namespace, data: bytes, segments: List[Segment], entropy_ranges: List[EntropyRange]) -> None:
    """
    Wrapper for API log_run_context to keep CLI tests stable.
    """
    return api.log_run_context(to_run_options(args), data, segments, entropy_ranges)


def validate_runtime_args(args: argparse.Namespace) -> Optional[str]:
    """
    Wrapper for API validate_runtime_args to keep CLI tests stable.
    """
    return api.validate_runtime_args(to_run_options(args))


def run_mutation_phase(
    args: argparse.Namespace,
    data: bytes,
    entropy_ranges: List[EntropyRange],
    base_name: str,
    mode: str,
    bits: Optional[List[int]],
) -> int:
    """
    Wrapper for API run_mutation_phase to keep CLI tests stable.
    """
    return api.run_mutation_phase(to_run_options(args), data, entropy_ranges, base_name, mode, bits)


def run_gif_phase(args: argparse.Namespace, base_name: str) -> int:
    """
    Wrapper for API run_gif_phase to keep CLI tests stable.
    """
    return api.run_gif_phase(to_run_options(args), base_name)


def run_ssim_phase(args: argparse.Namespace, base_name: str) -> int:
    """
    Wrapper for API run_ssim_phase to keep CLI tests stable.
    """
    return api.run_ssim_phase(to_run_options(args), base_name)


def run_gif_phase_for_paths(args: argparse.Namespace, paths: List[str]) -> int:
    """
    Wrapper for API run_gif_phase_for_paths to keep CLI tests stable.
    """
    return api.run_gif_phase_for_paths(to_run_options(args), paths)


def run_ssim_phase_for_paths(args: argparse.Namespace, paths: List[str]) -> int:
    """
    Wrapper for API run_ssim_phase_for_paths to keep CLI tests stable.
    """
    return api.run_ssim_phase_for_paths(to_run_options(args), paths)


def run_metrics_phase_for_paths(args: argparse.Namespace, paths: List[str]) -> Dict[str, int]:
    """
    Wrapper for API run_metrics_phase_for_paths to keep CLI tests stable.
    """
    return api.run_metrics_phase_for_paths(to_run_options(args), paths)


def run_wave_phase(args: argparse.Namespace, data: bytes, entropy_ranges: List[EntropyRange]) -> int:
    """
    Wrapper for API run_wave_phase to keep CLI tests stable.
    """
    return api.run_wave_phase(to_run_options(args), data, entropy_ranges)


def run_sliding_wave_phase(args: argparse.Namespace, data: bytes, entropy_ranges: List[EntropyRange]) -> int:
    """
    Wrapper for API run_sliding_wave_phase to keep CLI tests stable.
    """
    return api.run_sliding_wave_phase(to_run_options(args), data, entropy_ranges)


def run_dc_heatmap_phase(args: argparse.Namespace) -> Tuple[int, int]:
    """
    Wrapper for API run_dc_heatmap_phase to keep CLI tests stable.
    """
    return api.run_dc_heatmap_phase(to_run_options(args))


def run_ac_heatmap_phase(args: argparse.Namespace) -> Tuple[int, int]:
    """
    Wrapper for API run_ac_heatmap_phase to keep CLI tests stable.
    """
    return api.run_ac_heatmap_phase(to_run_options(args))


def main() -> int:
    """
    CLI entrypoint. Returns a process exit code (0 on success).
    """
    args = parse_args()
    if args.tui:
        return _run_tui(args)

    if not args.input:
        print("Error: input JPEG path is required unless using --tui.", file=os.sys.stderr)
        return 2

    options = to_run_options(args)
    try:
        result = api.run(options, emit_report=True)
    except (RuntimeError, ValueError) as e:
        print(f"Error: {e}", file=os.sys.stderr)
        return 2

    if options.report_only:
        return 0

    if not result.source_only_mode:
        print("")
        print(f"Generated {result.mutation_count} mutated files in {options.output_dir}")
        if options.gif and result.gif_frames is not None:
            print(f"GIF: wrote {result.gif_frames} frames to {options.gif}")
        if options.ssim_chart and result.ssim_sets is not None:
            print(f"SSIM chart: wrote panels for {result.ssim_sets} set(s) to {options.ssim_chart}")
        if options.metrics_chart_prefix and result.metric_sets:
            for out_path, set_count in result.metric_sets.items():
                print(f"Metric chart: wrote panels for {set_count} set(s) to {out_path}")
        if result.mutation_plugin_results:
            for plugin_id, outputs in result.mutation_plugin_results.items():
                print(f"Mutation plugin {plugin_id}: wrote {len(outputs)} file(s)")

    if options.wave_chart and result.wave_len is not None:
        print(f"Wave chart: wrote 2 panels for {result.wave_len} entropy bytes to {options.wave_chart}")
    if options.sliding_wave_chart and result.sliding_len is not None:
        print(
            "Sliding wave chart: wrote 3 panels "
            f"(window={options.wave_window}) for {result.sliding_len} entropy bytes to {options.sliding_wave_chart}"
        )
    if options.dc_heatmap and result.dc_blocks is not None:
        by, bx = result.dc_blocks
        print(f"DC heatmap: wrote {by}x{bx} block map to {options.dc_heatmap}")
    if options.ac_energy_heatmap and result.ac_blocks is not None:
        by, bx = result.ac_blocks
        print(f"AC energy heatmap: wrote {by}x{bx} block map to {options.ac_energy_heatmap}")

    return 0


def _add_mutation_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-o", "--output-dir", default="mutations", help="Output directory for mutated files")
    parser.add_argument(
        "--mutate",
        default="add1",
        help="Mutation mode: add1, sub1, flipall, ff, 00, bitflip:<bits> (e.g., bitflip:0,1,3 or bitflip:msb)",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=100,
        help=(
            "Independent: Monte Carlo sample size (number of byte offsets), 0 means all offsets. "
            "Cumulative/Sequential: number of output steps/images, 0 means all entropy-byte offsets."
        ),
    )
    parser.add_argument("--seed", type=int, default=3, help="Random seed for sampling")
    parser.add_argument(
        "--mutation-apply",
        choices=["independent", "cumulative", "sequential"],
        default="independent",
        help="Mutation application strategy: independent (default), cumulative, or sequential.",
    )
    parser.add_argument(
        "--repeats",
        "--repeat",
        type=int,
        default=1,
        help="Cumulative only: number of repeated cumulative sets to generate (default 1).",
    )
    parser.add_argument(
        "--step",
        type=int,
        default=1,
        help="Cumulative/Sequential: number of new entropy bytes added per image (default 1).",
    )
    parser.add_argument(
        "--overflow-wrap",
        action="store_true",
        help="If set, add1 wraps 0xFF->0x00 and sub1 wraps 0x00->0xFF.",
    )
    parser.add_argument("--report-only", action="store_true", help="Only print report, no mutations")
    parser.add_argument("--color", choices=["auto", "always", "never"], default="auto", help="Color output mode")
    parser.add_argument(
        "--mutation-plugin",
        default="",
        help="Comma-separated mutation plugin ids to run.",
    )
    parser.add_argument(
        "--mutation-plugin-param",
        action="append",
        default=[],
        help="Mutation plugin param in plugin.param=value form. Repeat as needed.",
    )


def _add_output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--gif", help="If set, write a GIF from the mutated outputs to this path")
    parser.add_argument("--gif-fps", type=int, default=10, help="GIF frames per second (default 10)")
    parser.add_argument("--gif-loop", type=int, default=0, help="GIF loop count (0 = infinite)")
    parser.add_argument("--gif-shuffle", action="store_true", help="Shuffle GIF frame order (uses --seed)")
    parser.add_argument(
        "--ssim-chart",
        help="If set, write a 3-panel SSIM chart (A lines by set, B quantile lines, C decode success).",
    )
    parser.add_argument(
        "--metrics",
        default="ssim",
        help="Comma-separated metrics for --metrics-chart-prefix. Supported: ssim,psnr,mse,mae.",
    )
    parser.add_argument(
        "--metrics-chart-prefix",
        help="If set, writes one 3-panel chart per selected metric using this prefix, e.g. prefix_ssim.png.",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=None,
        help="SSIM only: worker processes to use (default: all detected CPU cores).",
    )


def _add_analysis_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--analysis",
        default="",
        help="Comma-separated analysis plugin ids to run (e.g. entropy_wave).",
    )
    parser.add_argument(
        "--analysis-param",
        action="append",
        default=[],
        help="Plugin param in plugin.param=value form. Repeat as needed.",
    )
    parser.add_argument("--wave-chart", help="If set, write a 2-panel entropy stream wave chart (byte + bit).")
    parser.add_argument(
        "--sliding-wave-chart",
        help="If set, write a 3-panel sliding-wave chart (rolling mean, variance, entropy).",
    )
    parser.add_argument(
        "--wave-window",
        type=int,
        default=256,
        help="Window size for --sliding-wave-chart (default 256).",
    )
    parser.add_argument("--dc-heatmap", help="If set, write DC coefficient heatmap from decoded 8x8 blocks.")
    parser.add_argument("--ac-energy-heatmap", help="If set, write AC energy heatmap from decoded 8x8 blocks.")


def _add_misc_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--debug", action="store_true", help="Print debug information to stderr.")
    parser.add_argument(
        "--tui",
        "--gui",
        dest="tui",
        action="store_true",
        help="Launch the Textual fullscreen TUI (alias: --gui).",
    )


def _run_tui(args: argparse.Namespace) -> int:
    try:
        from .tui import TuiDefaults, run_tui
    except Exception as e:
        print(f"Error: Textual TUI unavailable ({e})", file=os.sys.stderr)
        return 2
    defaults = TuiDefaults(
        input_path=args.input or "",
        output_dir=args.output_dir,
        mutate=args.mutate,
        sample=args.sample,
        seed=args.seed,
        mutation_apply=args.mutation_apply,
        repeats=args.repeats,
        step=args.step,
        overflow_wrap=args.overflow_wrap,
        report_only=args.report_only,
        color=args.color,
        gif=args.gif or "",
        gif_fps=args.gif_fps,
        gif_loop=args.gif_loop,
        gif_shuffle=args.gif_shuffle,
        ssim_chart=args.ssim_chart or "",
        metrics=args.metrics,
        metrics_chart_prefix=args.metrics_chart_prefix or "",
        jobs="" if args.jobs is None else str(args.jobs),
        analysis=args.analysis or "",
        mutation_plugins=args.mutation_plugin or "",
        debug=args.debug,
    )
    run_tui(defaults=defaults)
    return 0

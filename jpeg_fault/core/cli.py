import argparse
import os
import time
from typing import Dict, List, Optional, Set, Tuple

from .debug import debug_log
from .jpeg_parse import parse_jpeg
from .media import write_gif
from .models import EntropyRange, Segment
from .mutate import (
    list_mutation_files,
    parse_mutation_mode,
    total_entropy_length,
    write_mutations,
)
from .report import print_report
from .ssim_analysis import parse_metrics_list, write_metric_panels, write_ssim_panels
from .wave_analysis import write_sliding_wave_chart, write_wave_chart
from .dct_analysis import write_ac_energy_heatmap, write_dc_heatmap


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="JPEG fault tolerance mutator and reporter")
    parser.add_argument("input", help="Input JPEG file")
    parser.add_argument("-o", "--output-dir", default="mutations", help="Output directory for mutated files")
    parser.add_argument(
        "--mutate",
        default="add1",
        help="Mutation mode: add1, sub1, flipall, bitflip:<bits> (e.g., bitflip:0,1,3 or bitflip:msb)",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=100,
        help=(
            "Independent: Monte Carlo sample size (number of byte offsets), 0 means all offsets. "
            "Cumulative: number of output steps/images, 0 means all entropy-byte offsets."
        ),
    )
    parser.add_argument("--seed", type=int, default=3, help="Random seed for sampling")
    parser.add_argument(
        "--mutation-apply",
        choices=["independent", "cumulative"],
        default="independent",
        help="Mutation application strategy: independent (default) or cumulative.",
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
        help="Cumulative only: number of new entropy bytes added per cumulative image (default 1).",
    )
    parser.add_argument("--report-only", action="store_true", help="Only print report, no mutations")
    parser.add_argument("--color", choices=["auto", "always", "never"], default="auto", help="Color output mode")
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
    parser.add_argument("--debug", action="store_true", help="Print debug information to stderr.")
    return parser.parse_args()


def log_run_context(args: argparse.Namespace, data: bytes, segments: List[Segment], entropy_ranges: List[EntropyRange]) -> None:
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
            f"repeats={args.repeats}, step={args.step}, seed={args.seed}, output={args.output_dir}, jobs={args.jobs}"
        ),
    )


def validate_runtime_args(args: argparse.Namespace) -> Optional[str]:
    if args.mutation_apply != "cumulative" and args.repeats != 1:
        return "--repeats is only supported with --mutation-apply cumulative."
    if args.mutation_apply != "cumulative" and args.step != 1:
        return "--step is only supported with --mutation-apply cumulative."
    if args.step < 1:
        return f"--step must be >= 1, got {args.step}"
    if args.wave_window < 1:
        return f"--wave-window must be >= 1, got {args.wave_window}"
    return None


def run_mutation_phase(
    args: argparse.Namespace,
    data: bytes,
    entropy_ranges: List[EntropyRange],
    base_name: str,
    mode: str,
    bits: Optional[List[int]],
) -> int:
    t_mut = time.perf_counter()
    count = write_mutations(
        data,
        entropy_ranges,
        args.output_dir,
        base_name,
        mode,
        bits,
        args.sample,
        args.seed,
        args.mutation_apply,
        args.repeats,
        args.step,
        args.debug,
    )
    debug_log(args.debug, f"Mutation generation time: {time.perf_counter() - t_mut:.2f}s")
    return count


def run_gif_phase(args: argparse.Namespace, base_name: str) -> int:
    paths = list_mutation_files(args.output_dir, base_name)
    debug_log(args.debug, f"GIF input files matched: {len(paths)}")
    return write_gif(paths, args.gif, args.gif_fps, args.gif_loop, args.seed, args.gif_shuffle)


def run_ssim_phase(args: argparse.Namespace, base_name: str) -> int:
    paths = list_mutation_files(args.output_dir, base_name)
    debug_log(args.debug, f"SSIM input files matched: {len(paths)}")
    t_ssim = time.perf_counter()
    set_count = write_ssim_panels(args.input, paths, args.ssim_chart, args.jobs, args.debug)
    debug_log(args.debug, f"SSIM panel generation time: {time.perf_counter() - t_ssim:.2f}s")
    return set_count


def new_mutation_paths(output_dir: str, base_name: str, before: Set[str]) -> List[str]:
    after = set(list_mutation_files(output_dir, base_name))
    return sorted(after - before)


def run_gif_phase_for_paths(args: argparse.Namespace, paths: List[str]) -> int:
    debug_log(args.debug, f"GIF input files (current run): {len(paths)}")
    return write_gif(paths, args.gif, args.gif_fps, args.gif_loop, args.seed, args.gif_shuffle)


def run_ssim_phase_for_paths(args: argparse.Namespace, paths: List[str]) -> int:
    debug_log(args.debug, f"SSIM input files (current run): {len(paths)}")
    t_ssim = time.perf_counter()
    set_count = write_ssim_panels(args.input, paths, args.ssim_chart, args.jobs, args.debug)
    debug_log(args.debug, f"SSIM panel generation time: {time.perf_counter() - t_ssim:.2f}s")
    return set_count


def run_metrics_phase_for_paths(args: argparse.Namespace, paths: List[str]) -> Dict[str, int]:
    metrics = parse_metrics_list(args.metrics)
    debug_log(args.debug, f"Metrics selected: {metrics}")
    results: Dict[str, int] = {}
    for metric in metrics:
        out_path = f"{args.metrics_chart_prefix}_{metric}.png"
        t0 = time.perf_counter()
        set_count = write_metric_panels(args.input, paths, out_path, args.jobs, args.debug, metric)
        debug_log(args.debug, f"{metric.upper()} panel generation time: {time.perf_counter() - t0:.2f}s")
        results[out_path] = set_count
    return results


def run_wave_phase(args: argparse.Namespace, data: bytes, entropy_ranges: List[EntropyRange]) -> int:
    t0 = time.perf_counter()
    stream_len = write_wave_chart(data, entropy_ranges, args.wave_chart, args.debug)
    debug_log(args.debug, f"Wave chart generation time: {time.perf_counter() - t0:.2f}s")
    return stream_len


def run_sliding_wave_phase(args: argparse.Namespace, data: bytes, entropy_ranges: List[EntropyRange]) -> int:
    t0 = time.perf_counter()
    stream_len = write_sliding_wave_chart(
        data, entropy_ranges, args.sliding_wave_chart, args.wave_window, args.debug
    )
    debug_log(args.debug, f"Sliding wave chart generation time: {time.perf_counter() - t0:.2f}s")
    return stream_len


def run_dc_heatmap_phase(args: argparse.Namespace) -> Tuple[int, int]:
    return write_dc_heatmap(args.input, args.dc_heatmap, args.debug)


def run_ac_heatmap_phase(args: argparse.Namespace) -> Tuple[int, int]:
    return write_ac_energy_heatmap(args.input, args.ac_energy_heatmap, args.debug)


def main() -> int:
    args = parse_args()
    t_start = time.perf_counter()

    with open(args.input, "rb") as f:
        data = f.read()

    segments, entropy_ranges = parse_jpeg(data)
    log_run_context(args, data, segments, entropy_ranges)
    print_report(args.input, data, segments, entropy_ranges, args.color)

    if args.report_only:
        return 0

    err = validate_runtime_args(args)
    if err:
        print(f"Error: {err}", file=os.sys.stderr)
        return 2

    mutation_dependent_outputs = bool(args.gif or args.ssim_chart or args.metrics_chart_prefix)
    source_only_outputs = bool(
        args.wave_chart or args.sliding_wave_chart or args.dc_heatmap or args.ac_energy_heatmap
    )
    source_only_mode = source_only_outputs and not mutation_dependent_outputs

    if not source_only_mode:
        mode, bits = parse_mutation_mode(args.mutate)
        base_name = os.path.splitext(os.path.basename(args.input))[0]
        before_paths = set(list_mutation_files(args.output_dir, base_name))
        try:
            count = run_mutation_phase(args, data, entropy_ranges, base_name, mode, bits)
        except ValueError as e:
            print(f"Error: {e}", file=os.sys.stderr)
            return 2
        created_paths = new_mutation_paths(args.output_dir, base_name, before_paths)
        if not created_paths:
            created_paths = list_mutation_files(args.output_dir, base_name)
        debug_log(args.debug, f"Mutation files considered for post-processing: {len(created_paths)}")

        print("")
        print(f"Generated {count} mutated files in {args.output_dir}")
        if args.gif:
            try:
                frame_count = run_gif_phase_for_paths(args, created_paths)
            except RuntimeError as e:
                print(f"Error: {e}", file=os.sys.stderr)
                return 2
            print(f"GIF: wrote {frame_count} frames to {args.gif}")

        if args.ssim_chart:
            try:
                set_count = run_ssim_phase_for_paths(args, created_paths)
            except (RuntimeError, ValueError) as e:
                print(f"Error: {e}", file=os.sys.stderr)
                return 2
            print(f"SSIM chart: wrote panels for {set_count} set(s) to {args.ssim_chart}")

        if args.metrics_chart_prefix:
            try:
                out_counts = run_metrics_phase_for_paths(args, created_paths)
            except (RuntimeError, ValueError) as e:
                print(f"Error: {e}", file=os.sys.stderr)
                return 2
            for out_path, set_count in out_counts.items():
                print(f"Metric chart: wrote panels for {set_count} set(s) to {out_path}")
    else:
        debug_log(args.debug, "Source-only analysis mode: skipping mutation generation.")

    if args.wave_chart:
        try:
            stream_len = run_wave_phase(args, data, entropy_ranges)
        except (RuntimeError, ValueError) as e:
            print(f"Error: {e}", file=os.sys.stderr)
            return 2
        print(f"Wave chart: wrote 2 panels for {stream_len} entropy bytes to {args.wave_chart}")

    if args.sliding_wave_chart:
        try:
            stream_len = run_sliding_wave_phase(args, data, entropy_ranges)
        except (RuntimeError, ValueError) as e:
            print(f"Error: {e}", file=os.sys.stderr)
            return 2
        print(
            "Sliding wave chart: wrote 3 panels "
            f"(window={args.wave_window}) for {stream_len} entropy bytes to {args.sliding_wave_chart}"
        )

    if args.dc_heatmap:
        try:
            by, bx = run_dc_heatmap_phase(args)
        except (RuntimeError, ValueError) as e:
            print(f"Error: {e}", file=os.sys.stderr)
            return 2
        print(f"DC heatmap: wrote {by}x{bx} block map to {args.dc_heatmap}")

    if args.ac_energy_heatmap:
        try:
            by, bx = run_ac_heatmap_phase(args)
        except (RuntimeError, ValueError) as e:
            print(f"Error: {e}", file=os.sys.stderr)
            return 2
        print(f"AC energy heatmap: wrote {by}x{bx} block map to {args.ac_energy_heatmap}")

    debug_log(args.debug, f"Total runtime: {time.perf_counter() - t_start:.2f}s")
    return 0

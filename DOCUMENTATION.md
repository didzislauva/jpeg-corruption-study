# jpeg_corruption_study — Code Reference

This document is an extended, file-by-file reference for all Python classes and functions in this repo, plus how they are tied together after the API refactor.

## Summary Of Work So Far
- Added a third mutation strategy: `sequential` (contiguous mutable bytes starting from a seed).
- Added two mutation modes: `ff` and `00` (direct replacement).
- Added `--overflow-wrap` to wrap `add1`/`sub1` at byte boundaries.
- Refactored the CLI to call a new core API layer (`jpeg_fault/core/api.py`).
- Split the large TUI into `tui_app.py`, `tui_segments_basic.py`, `tui_segments_tables.py`, `tui_segments_appn.py`, and `tui_hex.py`.
- Added plugin registries for core analysis plugins and TUI plugin panels.
- Added a separate mutation-plugin family and registry.
- Strengthened plugin isolation with typed plugin params, declared plugin needs, and richer host-prepared plugin contexts.
- Added a built-in `sliding_wave` analysis plugin with typed params and CSV export.
- Fixed TUI plugin panel initialization to respect Textual's real widget lifecycle.
- Forced chart/heatmap modules onto the matplotlib `Agg` backend to avoid TUI worker thread crashes.
- Updated tests and docs.
- Current test baseline: `94 passed`.

## Dependency Model
- Python 3.8+ is the baseline runtime.
- The base parser/report/mutation flow is standard-library only.
- This repository currently has no pinned dependency manifest file such as `requirements.txt` or `pyproject.toml`; optional imports are resolved at runtime by feature.

Optional third-party dependencies inferred from the code:
- `pillow`: required for GIF output in `media.py`, metric charts in `ssim_analysis.py`, and DCT heatmaps in `dct_analysis.py`.
- `matplotlib`: required for metric charts, wave charts, and DCT heatmaps. These code paths force the `Agg` backend.
- `numpy`: required for metric charts, wave charts, and DCT heatmaps.
- `scikit-image`: required only when SSIM is requested (`--ssim-chart` or `--metrics-chart-prefix` with `ssim`).
- `textual`: required for the fullscreen TUI (`--tui` / `--gui`) and related tests.
- `piexif`: optional TUI-only dependency for APP1/EXIF editing. If missing, the EXIF editor is disabled but the rest of the TUI remains usable.
- `pytest`: required to run the automated test suite.

Dependency mapping by user-facing feature:
- Basic report and mutation generation: no third-party packages required.
- `--gif`: `pillow`
- `--ssim-chart`: `pillow`, `matplotlib`, `numpy`, `scikit-image`
- `--metrics-chart-prefix` with only `psnr`, `mse`, and/or `mae`: `pillow`, `matplotlib`, `numpy`
- `--metrics-chart-prefix` when `ssim` is included: `pillow`, `matplotlib`, `numpy`, `scikit-image`
- `--wave-chart` / `--sliding-wave-chart`: `matplotlib`, `numpy`
- `--dc-heatmap` / `--ac-energy-heatmap`: `pillow`, `matplotlib`, `numpy`
- `--tui` / `--gui`: `textual`
- TUI APP1/EXIF editing: `textual`, `piexif`

## Plugin Architecture

The plugin system is now split into two families:

- analysis plugins: produce derived outputs such as charts, reports, and inspections
- mutation plugins: produce additional mutated files as part of the run pipeline

Analysis plugin contract:

- declared in `jpeg_fault/core/analysis_types.py`
- plugins declare:
  - `id`
  - `label`
  - `supported_formats`
  - `requires_mutations`
  - `params_spec`
  - `needs`
- the host validates and coerces plugin params before `run()`
- the host prepares `AnalysisContext` based on the plugin's declared `needs`

Mutation plugin contract:

- declared in `jpeg_fault/core/mutation_types.py`
- plugins declare:
  - `id`
  - `label`
  - `supported_formats`
  - `params_spec`
  - `needs`
- the host validates and coerces plugin params before `run()`
- the host prepares `MutationContext` based on the plugin's declared `needs`

Currently supported plugin needs:

- `source_bytes`
- `parsed_jpeg`
- `entropy_ranges`
- `decoded_image`
- `mutation_outputs`

Current host-prepared context model:

- plugins no longer need to rediscover everything from scratch by default
- the API can provide format, input path, output directory, debug flag, typed params, and selected optional artifacts
- this is the current isolation boundary that future built-in plugins should target

Current built-in plugin example:

- `jpeg_fault/core/plugins/entropy_wave/plugin.py`
  - declares typed params for `out_path`, `mode`, `transform`, and optional `csv_path`
  - currently requests `source_bytes` and `entropy_ranges`
  - can render byte-only, bit-only, or combined wave output
  - supports first- and second-order derivative transforms for byte-mode output
  - can optionally export the selected stream data to CSV
- `jpeg_fault/core/plugins/sliding_wave/plugin.py`
  - declares typed params for `out_path`, `csv_path`, `window`, `stats`, and `transform`
  - currently requests `source_bytes` and `entropy_ranges`
  - can render configurable sliding-window stats over raw or transformed byte streams
  - can optionally export the selected stat series to CSV
- `jpeg_fault/core/plugins/dc_heatmap/plugin.py`
  - declares typed params for `out_path`, `cmap`, `plane_mode`, and `block_size`
  - currently keeps the existing decoded-image heatmap implementation in `dct_analysis.py` as the reusable library layer
  - defaults unnamed outputs to a descriptive filename in the current working directory using the selected plane mode and block size
  - returns block-grid dimensions via plugin result details for compatibility with the legacy CLI summary
- `jpeg_fault/core/plugins/ac_energy_heatmap/plugin.py`
  - declares typed params for `out_path`, `cmap`, `plane_mode`, and `block_size`
  - currently keeps the existing decoded-image heatmap implementation in `dct_analysis.py` as the reusable library layer
  - defaults unnamed outputs to a descriptive filename in the current working directory using the selected plane mode and block size
  - returns block-grid dimensions via plugin result details for compatibility with the legacy CLI summary

Built-in compatibility routing:

- `--wave-chart` now dispatches internally through the `entropy_wave` analysis plugin
- `--sliding-wave-chart` now dispatches internally through the `sliding_wave` analysis plugin
- `--dc-heatmap` now dispatches internally through the `dc_heatmap` analysis plugin
- `--ac-energy-heatmap` now dispatches internally through the `ac_energy_heatmap` analysis plugin
- the old CLI flags are preserved as compatibility frontends, but the plugin path is now the execution path underneath

Current plugin registries:

- `jpeg_fault/core/analysis_registry.py`
- `jpeg_fault/core/mutation_registry.py`
- `jpeg_fault/core/tui_plugin_registry.py`

## End-To-End Wiring (How It All Connects)
- `jpg_fault_tolerance.py` is the executable entrypoint and calls `jpeg_fault.core.cli.main()`.
- `jpeg_fault/core/cli.py` parses CLI args and converts them to `RunOptions` (from the API layer).
- `jpeg_fault/core/api.py` orchestrates the full run: parse JPEG, print report, run built-in mutations, run mutation plugins, post-process outputs, run source-only analyses, and run analysis plugins.
- Built-in wave phases now route through analysis-plugin execution instead of calling wave-analysis helpers directly.
- `jpeg_fault/core/jpeg_parse.py` parses JPEG structure and finds entropy ranges.
- `jpeg_fault/core/report.py` renders the human-readable, colorized JPEG report.
- `jpeg_fault/core/mutate.py` owns all mutation logic, sampling, and file output.
- `jpeg_fault/core/media.py` builds GIFs from mutation outputs.
- `jpeg_fault/core/ssim_analysis.py` computes metrics and writes charts.
- `jpeg_fault/core/wave_analysis.py` writes entropy stream wave charts.
- `jpeg_fault/core/dct_analysis.py` writes DC/AC energy heatmaps.
- `jpeg_fault/core/analysis_types.py` defines analysis plugin param specs, needs, contexts, and results.
- `jpeg_fault/core/mutation_types.py` defines mutation plugin contexts and results.
- `jpeg_fault/core/debug.py` provides lightweight debug logging and optional function instrumentation.
- `jpeg_fault/core/tui_app.py` owns the main Textual app shell and orchestration for the TUI.
- `jpeg_fault/core/tui_segments_basic.py` owns APP0/SOF0/DRI TUI workspaces.
- `jpeg_fault/core/tui_segments_tables.py` owns DHT/DQT TUI workspaces.
- `jpeg_fault/core/tui_segments_appn.py` owns APP1/APP2 and generic APPn TUI workspaces.
- `jpeg_fault/core/tui_hex.py` owns the full-file hex pane.
- `jpeg_fault/core/analysis_registry.py`, `jpeg_fault/core/mutation_registry.py`, and `jpeg_fault/core/tui_plugin_registry.py` support pluggable analysis, mutation, and TUI plugin surfaces.

## File: `jpg_fault_tolerance.py`
**Purpose:** Thin entrypoint script.

Functions:
- `main` import usage: It imports `jpeg_fault.core.cli.main` and calls it under `__main__`.

## File: `jpeg_fault/__init__.py`
**Purpose:** Package marker and export surface.

Objects:
- `__all__`: Exposes `core` as the public module.

## File: `jpeg_fault/core/__init__.py`
**Purpose:** Public API export for CLI users.

Objects:
- `main`: Re-exported from `jpeg_fault.core.cli.main`.
- `__all__`: Exposes `main`.

## File: `jpeg_fault/core/models.py`
**Purpose:** Shared dataclasses used across parser/report/mutation logic.

Classes:
- `Segment`: Represents a JPEG marker segment.
  - Fields: `marker`, `offset`, `name`, `length_field`, `payload_offset`, `payload_length`, `total_length`.
  - Used by: `jpeg_parse.py`, `report.py`, `api.py`, `cli.py`.
- `EntropyRange`: Represents one contiguous entropy-coded range.
  - Fields: `start`, `end` (exclusive), `scan_index`.
  - Used by: `jpeg_parse.py`, `report.py`, `mutate.py`, `wave_analysis.py`, `api.py`, `cli.py`.

## File: `jpeg_fault/core/jpeg_parse.py`
**Purpose:** Low-level JPEG parsing, marker decoding, and entropy range detection.

Top-level constants:
- `MARKER_NAMES`: Mapping of marker byte to friendly name.
- `NO_LENGTH_MARKERS`: Markers without a length field (`SOI`, `EOI`).

Functions:
- `read_u16(be: bytes) -> int`: Big-endian 16-bit decode for length fields.
- `marker_name(marker: int) -> str`: Map marker byte to name.
- `format_bytes(data: bytes, start: int, count: int) -> str`: Hex preview formatting.
- `next_marker_offset(data: bytes, start: int) -> int`: Scans for the next real marker, skipping stuffed and restart markers.
- `parse_segment(data: bytes, i: int) -> Tuple[Segment, int, Optional[EntropyRange]]`: Parses one segment and, if `SOS`, returns an entropy range and the next offset.
- `parse_jpeg(data: bytes) -> Tuple[List[Segment], List[EntropyRange]]`: Parses full JPEG, returning ordered segments and entropy ranges.
- `decode_app0(payload: bytes) -> Optional[Dict[str, str]]`: Decodes JFIF/JFXX headers.
- `decode_dqt(payload: bytes) -> List[Dict[str, str]]`: Parses quantization tables.
- `decode_dqt_tables(payload: bytes) -> List[Dict[str, object]]`: Parses full quantization tables (id, precision, values).
- `decode_dht(payload: bytes) -> List[Dict[str, str]]`: Parses Huffman tables.
- `decode_sof0(payload: bytes) -> Optional[Dict[str, str]]`: Parses baseline frame header.
- `decode_sos(payload: bytes) -> Optional[Dict[str, str]]`: Parses scan header parameters.
- `decode_dri(payload: bytes) -> Optional[Dict[str, str]]`: Parses restart interval.

Tie-in:
- Used by `api.run()` to parse input JPEG and by `report.py` to decode descriptive details.

## File: `jpeg_fault/core/report.py`
**Purpose:** Human-readable, colorized JPEG structure report.

Functions:
- `segment_details(seg: Segment, data: bytes) -> List[str]`: Per-segment decoded details (APP0, DQT, DHT, SOF0, SOS, DRI, COM).
- `explain_common(seg: Segment, actual: List[str]) -> List[str]`: Shared explanation text for segments.
- `segment_intro_lines(seg_name: str) -> List[str]`: Plain-English introduction to segment types.
- `explain_segment(seg: Segment, data: bytes) -> List[str]`: Combines intro + common explanation + actual details.
- `use_color(mode: str) -> bool`: Color decision based on `auto|always|never`.
- `colorize(text: str, color: str, enabled: bool) -> str`: ANSI color wrapper.
- `classify_head_bytes(segments: List[Segment], head_len: int) -> List[str]`: Labels first bytes as marker/length/payload/other.
- `format_head_colored(data: bytes, labels: List[str], colors: bool) -> str`: Colored hex preview of the file head.
- `segment_hex_parts(seg: Segment, data: bytes, preview: int) -> Tuple[str, str, str, bool]`: Marker/length/payload hex slices.
- `print_segment_header(seg: Segment, idx: int, colors: bool) -> None`: Prints one segment summary line.
- `print_segment_hex(seg: Segment, data: bytes, colors: bool) -> None`: Prints hex preview for a segment.
- `print_entropy_ranges(entropy_ranges: List[EntropyRange], colors: bool) -> None`: Prints entropy scan ranges.
- `print_report(path: str, data: bytes, segments: List[Segment], entropy_ranges: List[EntropyRange], color_mode: str) -> None`: Full report output.

Tie-in:
- Called by `api.run()` (and therefore by CLI) unless `emit_report=False`.

## File: `jpeg_fault/core/mutate.py`
**Purpose:** All mutation selection, application, and file output logic.

Parsing helpers:
- `parse_bits_list(spec: str) -> List[int]`: Parses `bitflip` bits including `msb`/`lsb`.
- `parse_mutation_mode(spec: str) -> Tuple[str, Optional[List[int]]]`: Parses mode and bits, supports `add1`, `sub1`, `flipall`, `ff`, `00`, `bitflip:<bits>`.

Mutation primitives:
- `mutate_byte(orig: int, mode: str, bits: Optional[List[int]], overflow_wrap: bool) -> List[Tuple[int, str]]`: Single-byte mutation for independent mode.
- `mutate_byte_cumulative(orig: int, mode: str, bits: Optional[List[int]], overflow_wrap: bool) -> Optional[Tuple[int, str]]`: Single-byte mutation for cumulative/sequential.

Entropy indexing:
- `total_entropy_length(ranges: List[EntropyRange]) -> int`: Sum of entropy lengths.
- `build_cumulative(ranges: List[EntropyRange]) -> List[int]`: Cumulative ends for logical indexing.
- `index_to_offset(idx: int, ranges: List[EntropyRange], ends: List[int]) -> int`: Logical index to file offset.

Sampling:
- `select_offsets_from_ranges(ranges: List[EntropyRange], sample_n: int, seed: int) -> List[int]`: Random offsets for independent mode.
- `select_offsets_cumulative(ranges: List[EntropyRange], sample_n: int, seed: int) -> List[int]`: Random logical offsets for cumulative mode.

Mutability and grouping:
- `offset_mutable(byte_val: int, mode: str, overflow_wrap: bool) -> bool`: Determines if a byte can be modified for the mode.
- `mutable_offsets_in_ranges(data: bytes, ranges: List[EntropyRange], mode: str, overflow_wrap: bool) -> List[int]`: Collects mutable offsets in order.
- `split_offsets_by_step(offsets: List[int], step_size: int) -> List[List[int]]`: Groups offsets into step-sized chunks.
- `select_cumulative_step_offsets(...) -> List[List[int]]`: Random mutable offsets grouped by step for cumulative.
- `select_sequential_step_offsets(...) -> List[List[int]]`: Sequential mutable offsets grouped by step for sequential.

Repeat control:
- `derive_set_seeds(master_seed: int, repeats: int) -> List[int]`: Deterministic per-set seeds.

Output naming:
- `cumulative_output_dir(output_dir: str, set_index: int, repeats: int) -> str`: Per-set output directory.
- `cumulative_out_name(...) -> str`: Output filename for cumulative/sequential outputs.

Mutation writers:
- `write_cumulative_set(...) -> int`: Applies step-wise cumulative changes and writes each step as a file.
- `write_mutations_independent(...) -> int`: Writes independent outputs (reset per offset).
- `write_mutations_cumulative(...) -> int`: Writes cumulative sets using random offsets.
- `write_mutations_sequential(...) -> int`: Writes sequential sets using contiguous offsets.
- `write_mutations(...) -> int`: Dispatches to strategy.

File discovery:
- `list_mutation_files(output_dir: str, base_name: str) -> List[str]`: Glob for mutation files for analysis.

Tie-in:
- Called by `api.run_mutation_phase()` which is called by `api.run()`.

## File: `jpeg_fault/core/media.py`
**Purpose:** GIF generation from mutation outputs.

Functions:
- `load_frames(paths: List[str], image_module: Any) -> List[Any]`: Loads and converts frames to RGB, skipping failures.
- `write_gif(paths: List[str], out_path: str, fps: int, loop: int, seed: int, shuffle: bool) -> int`: Writes GIF with optional shuffle.

Tie-in:
- Used by `api.run_gif_phase*()` and CLI.

## File: `jpeg_fault/core/ssim_analysis.py`
**Purpose:** Metric computation (SSIM/PSNR/MSE/MAE) and chart generation.

Dependency helpers:
- `analysis_deps(metric: str) -> Tuple[Any, Any, Any, Any]`: Imports Pillow/matplotlib/numpy/scikit-image as needed and forces matplotlib to use `Agg`.

Parsing and validation:
- `parse_metrics_list(spec: str) -> List[str]`: Parses `--metrics`.
- `resolve_jobs(jobs_arg: Optional[int], debug: bool) -> int`: Worker resolution with bounds.
- `parse_cumulative_ids(path: str) -> Optional[Tuple[int, int, int]]`: Extracts set/step/step_size from filename or parent dir.
- `group_cumulative_paths(paths: List[str]) -> Tuple[List[int], List[int], int, Dict[Tuple[int, int], str]]`: Groups cumulative paths and checks step size consistency.

Image and scoring:
- `load_rgb_array(path: str, ref_size: Tuple[int, int], np: Any, image_module: Any) -> Optional[Any]`: Reads and resizes to reference.
- `score_for_path(...) -> Optional[float]`: Computes metric for a path.

Parallel worker globals:
- `_SSIM_*` globals: Shared state for `ProcessPoolExecutor`.
- `ssim_worker_init(input_path: str, metric: str) -> None`: Initializes reference image in workers.
- `ssim_worker_task(task: Tuple[int, int, str]) -> Tuple[int, int, Optional[float]]`: Computes score for a path.

Matrix prep and fill:
- `prepare_ssim_grid(...) -> Tuple[Any, Any, List[Tuple[int, int, str]]]`: Initializes score matrix and tasks.
- `fill_scores_sequential(...) -> None`: Sequential scoring path.
- `fill_scores_parallel(...) -> None`: Parallel scoring path.

Stats and plotting:
- `column_quantile(scores: Any, q: float, np: Any) -> Any`: Column-wise quantiles ignoring NaNs.
- `build_ssim_matrices(...) -> Tuple[List[int], List[int], List[int], Any, Any]`: Main compute pipeline.
- `plot_panel_a(...) -> None`: Per-set score lines.
- `plot_panel_b(...) -> None`: Quantile summaries.
- `plot_panel_c(...) -> None`: Decode success rate.

Public chart writers:
- `write_metric_panels(...) -> int`: Writes a 3-panel chart for the selected metric.
- `write_ssim_panels(...) -> int`: SSIM-specific wrapper.

Tie-in:
- Called by `api.run_metrics_phase_for_paths()` and `api.run_ssim_phase_for_paths()`.

## File: `jpeg_fault/core/wave_analysis.py`
**Purpose:** Entropy stream wave and sliding-wave charts.

Functions:
- `wave_deps() -> Tuple[Any, Any]`: Imports numpy/matplotlib with helpful error and forces matplotlib to use `Agg`.
- `entropy_bytes(data: bytes, entropy_ranges: Sequence[EntropyRange]) -> bytes`: Concatenates entropy stream.
- `bytes_to_bit_array(stream: bytes, np: Any) -> Any`: Converts to bit array.
- `maybe_downsample(series: Any, max_points: int, np: Any) -> Tuple[Any, int]`: Downsampling helper.
- `rolling_mean_var(stream: bytes, window: int, np: Any) -> Tuple[Any, Any]`: Rolling mean/variance over bytes.
- `rolling_entropy(stream: bytes, window: int, np: Any) -> Any`: Rolling Shannon entropy over bytes.
- `write_wave_chart(...) -> int`: Writes byte-wave + bit-wave panels.
- `write_sliding_wave_chart(...) -> int`: Writes rolling mean/var/entropy panels.

Tie-in:
- Called by `api.run_wave_phase()` and `api.run_sliding_wave_phase()`.

## File: `jpeg_fault/core/dct_analysis.py`
**Purpose:** 8x8 DCT-based heatmaps computed from decoded image luminance.

Functions:
- `dct_deps() -> Tuple[Any, Any, Any]`: Imports Pillow/matplotlib/numpy with error and forces matplotlib to use `Agg`.
- `load_luma(path: str, np: Any, image_module: Any) -> Any`: Converts RGB to luma.
- `crop_to_block_grid(y_plane: Any, np: Any) -> Any`: Crops to multiples of 8.
- `dct_basis_8(np: Any) -> Any`: Precomputes 8x8 DCT basis.
- `block_maps(y_plane: Any, np: Any) -> Tuple[Any, Any]`: Computes DC and AC energy grids.
- `plot_heatmap(ax: Any, data: Any, title: str, cmap: str) -> None`: Shared heatmap renderer.
- `write_dc_heatmap(input_path: str, out_path: str, debug: bool) -> Tuple[int, int]`: DC heatmap writer.
- `write_ac_energy_heatmap(input_path: str, out_path: str, debug: bool) -> Tuple[int, int]`: AC energy heatmap writer.

Tie-in:
- Called by `api.run_dc_heatmap_phase()` and `api.run_ac_heatmap_phase()`.

## File: `jpeg_fault/core/debug.py`
**Purpose:** Debug logging and optional function instrumentation.

Functions:
- `debug_log(enabled: bool, msg: str) -> None`: Print debug message to stderr.
- `set_debug(enabled: bool) -> None`: Set global debug flag.
- `is_debug() -> bool`: Read global debug flag.
- `_short_value(v: Any) -> str`: Compact type-aware value summary.
- `_summarize_call(args: tuple[Any, ...], kwargs: Dict[str, Any]) -> str`: Summarizes call arguments.
- `instrument_module_functions(...) -> None`: Wraps functions in a module namespace with debug logging.

Tie-in:
- Used by most modules for structured debug output.

## File: `jpeg_fault/core/tools.py`
**Purpose:** Custom APPn insertion utilities.

Functions:
- `build_appn_segment(appn, payload) -> bytes`: Build raw APPn segment bytes.
- `_default_insertion_offset(segments) -> int`: Determine insertion position (after last APPn).
- `insert_custom_appn(data, appn, payload) -> bytes`: Insert APPn into JPEG data.
- `read_payload_hex(text) -> bytes`: Parse hex payload text into bytes.
- `output_path_for(input_path, appn, out_path) -> str`: Default output filename builder.

## File: `jpg_fault_tools.py`
**Purpose:** CLI helper for tools (custom APPn insertion).

Commands:
- `insert-appn`: Insert a custom APPn segment with payload hex/file and optional identifier.

## Current TUI / Plugin State

- Dynamic plugin panels are created in the main TUI shell and populated only after the widget tree is ready.
- This fixed the earlier `TabbedContent.add_pane()` / `NoMatches(ContentTabs)` startup failure.
- TUI plugin menu insertion now uses the real `ListView` append-style path, with compatibility fallback only for test doubles.
- TUI plugin tabs can now be built either by a custom `build_tab` callback or from plugin metadata/default param widgets.
- The entropy-wave, sliding-wave, dc-heatmap, and ac-energy-heatmap plugins are current built-in examples of analysis plugins using the stronger plugin contract and are exposed through the metadata-driven TUI plugin panel path.
- The old dedicated TUI Outputs-panel controls for entropy-wave and sliding-wave have been removed; the TUI path for those analyses is now the plugin tabs.
- The old dedicated TUI Outputs-panel control for DC heatmap has been removed; the TUI path for DC heatmap is now the plugin tab.
- The old dedicated TUI Outputs-panel control for AC energy heatmap has been removed; the TUI path for AC energy heatmap is now the plugin tab.

## Remaining Work

- The TUI remains the largest maintenance hotspot by far.
- Repeated editor mechanics across SOF0/DRI/DHT/DQT are still not abstracted enough.
- Test coverage is now good for helper-level TUI behavior, but still light on full interactive/runtime flows.
- The plugin framework is now a better foundation for future built-in migration, but it still needs more real plugins and more end-to-end UI coverage.

## File: `jpeg_fault/core/api.py`
**Purpose:** Stable, programmatic API that mirrors CLI behavior and can be reused by TUI/GUI.

Classes:
- `RunOptions`: Immutable config for a full run.
- `RunResult`: Immutable summary of outputs produced.

Functions:
- `log_run_context(...) -> None`: Debug log summary of the run context.
- `validate_runtime_args(...) -> Optional[str]`: CLI-level validation rules.
- `new_mutation_paths(output_dir: str, base_name: str, before: Set[str]) -> List[str]`: Finds new files created in a run.
- `run_mutation_phase(...) -> int`: Writes mutation files.
- `run_gif_phase(...) -> int`: GIF from all matching mutations.
- `run_gif_phase_for_paths(...) -> int`: GIF from a specific set of files.
- `run_ssim_phase(...) -> int`: SSIM from all matching mutations.
- `run_ssim_phase_for_paths(...) -> int`: SSIM from a specific set of files.
- `run_metrics_phase_for_paths(...) -> Dict[str, int]`: Metrics charts for a specific set.
- `run_wave_phase(...) -> int`: Entropy wave chart.
- `run_sliding_wave_phase(...) -> int`: Sliding window chart.
- `run_dc_heatmap_phase(...) -> Tuple[int, int]`: DC heatmap.
- `run_ac_heatmap_phase(...) -> Tuple[int, int]`: AC energy heatmap.
- `run(args: RunOptions, emit_report: bool = True) -> RunResult`: Full end-to-end execution.

Tie-in:
- Called by `cli.main()` and is the intended entry for future TUI/GUI frontends.

## File: `jpeg_fault/core/cli.py`
**Purpose:** Command-line interface and compatibility layer to the API.

Functions:
- `parse_args() -> argparse.Namespace`: CLI argument parsing.
- `to_run_options(args: argparse.Namespace) -> RunOptions`: Adapter from CLI args to API options.
- `log_run_context(...) -> None`: Wrapper to API log.
- `validate_runtime_args(...) -> Optional[str]`: Wrapper to API validation.
- `run_mutation_phase(...) -> int`: Wrapper to API mutation phase.
- `run_gif_phase(...) -> int`: Wrapper to API GIF phase.
- `run_ssim_phase(...) -> int`: Wrapper to API SSIM phase.
- `run_gif_phase_for_paths(...) -> int`: Wrapper to API GIF phase for paths.
- `run_ssim_phase_for_paths(...) -> int`: Wrapper to API SSIM phase for paths.
- `run_metrics_phase_for_paths(...) -> Dict[str, int]`: Wrapper to API metrics phase.
- `run_wave_phase(...) -> int`: Wrapper to API wave phase.
- `run_sliding_wave_phase(...) -> int`: Wrapper to API sliding wave phase.
- `run_dc_heatmap_phase(...) -> Tuple[int, int]`: Wrapper to API DC heatmap phase.
- `run_ac_heatmap_phase(...) -> Tuple[int, int]`: Wrapper to API AC heatmap phase.
- `main() -> int`: CLI entrypoint, prints user-facing outputs and handles errors.

## File: `jpeg_fault/core/tui.py`
**Purpose:** Textual fullscreen TUI for interactive control.

Features:
- Left menu for Input/Info/Tools/Mutation/Strategy/Outputs/Run.
- File browser with JPEG-only list and live preview (ASCII thumbnail + metadata).
- Info tab with segment list, details, entropy, full-hex view, and APP0/SOF0/DRI/APPn/DHT/DQT decoding.
- Tools tab with APPn insertion helper.

Notable behavior:
- Info → Segments includes health checks with OK/WARN/FAIL and reasons.
- APP0 editor supports simple fields and advanced raw hex, with live preview.
- SOF0, DRI, DHT, and DQT editors all provide live byte-level preview updates.
- DHT and DQT avoid rewriting the active editor while typing; raw/structured views sync when mode changes.
- Selecting a JPEG auto-loads Info tabs for immediate inspection.

### Info Tab Details
- **General**: file size, segment count, scan count, total entropy bytes.
- **Segments**: one-line segment summary plus health status.
- **Details**: expanded per-segment explanations (from `report.explain_segment`).
- **Entropy**: entropy ranges per scan.
- **APP0**: decoded fields, legend, and colorized hex dump.
- **SOF0**: frame-header workspace with bytes/info plus frame/components/tables/edit views.
- **DRI**: restart-interval workspace with bytes/info plus summary/effect/edit views.
- **APPn**: per-segment subtabs for APP1/APP2 decoding (others are read-only).
- **DHT**: per-segment workspaces with bytes/info plus table/counts/symbols/usage/codes/edit views.
- **DQT**: per-segment workspaces with bytes/info plus grid/zigzag/stats/usage/heatmap/edit views.
- **Hex**: full-file hex view with segment coloring and clickable legend.

### Segment Health Checks
The TUI computes a health status for each segment:
- **OK**: no detected issues.
- **WARN**: unusual but non-fatal findings (e.g., gaps between markers).
- **FAIL**: structural problems (e.g., out-of-bounds, overlap, missing data).

Checks include:
- Length-field consistency (`total_length` vs `length_field`).
- Bounds checks for payload and segment sizes.
- SOI at offset 0 and length 2.
- EOI at end of file.
- SOS entropy range presence and bounds.
- Gaps/overlaps between adjacent segments.

### APP0 Editor (Info → APP0)
Two-pane layout:
- **Left**: decoded fields + legend + colorized hex dump.
- **Right**: editable fields and raw hex editor.

Modes:
- **Simple mode**: structured fields (identifier, version, units, densities, thumbnail size/data).
- **Advanced mode**: raw payload hex editor.
- **Manual length**: if enabled, overrides computed length.

Behavior:
- Live preview updates the decoded and hex views on every change.
- Save writes a new file `*_app0_edit.jpg` (or `_app0_edit_N.jpg` if needed).

### SOF0 Workspace (Info → SOF0)
- Left side shows segment structure, decoded frame geometry, component summaries, and colorized bytes.
- Right side provides Frame, Components, Tables, and Edit tabs.
- Edit supports structured frame-header fields or raw payload hex with live preview and save-as-new-file.

### DRI Workspace (Info → DRI)
- Left side shows segment structure, decoded restart interval, and colorized bytes.
- Right side provides Summary, Effect, and Edit tabs.
- Edit supports structured restart-interval fields or raw payload hex with live preview and save-as-new-file.

### APPn Decoder (Info → APPn)
- APPn tab groups APP0/APP1/APP2/APP13/APP14/etc. into subtabs.
- APP1: EXIF-aware views with raw hex, annotated hex, table view, and edit tabs for headers/IFDs.
- APP2: ICC profile decoder with header, tag table, and editable tag payloads.

### DHT Decoder (Info → DHT)
- One workspace per DHT segment.
- Left side shows segment structure, decoded summaries, and colorized bytes.
- Right side provides Tables, Counts, Symbols, Usage, Codes, and Edit tabs.
- Edit supports either structured Huffman-table dictionaries or raw payload hex.

### DQT Decoder (Info → DQT)
- One workspace per DQT segment.
- Left side shows segment structure, decoded summaries, and colorized bytes.
- Right side provides Grid, Zigzag, Stats, Usage, Heatmap, and Edit tabs.
- Edit supports either structured natural-order table grids or raw payload hex.

### Full Hex View (Info → Hex)
- Shows 512 bytes per page with offset/hex/ASCII columns.
- Segment coloring matches legend entries.
- Legend entries are clickable to jump to the segment’s page.

### Tools Tab (APPn Writer)
- Insert a custom APPn marker with payload hex or payload file.
- Optional ASCII identifier prefix.
- Default output path: `<stem>_appNN.jpg`.

## Tests: `tests/` (All Python Files)
These are Python functions too, and they define behavior expectations for the system.

### `tests/conftest.py`
Fixtures:
- `tiny_jpeg_bytes() -> bytes`: Tiny synthetic JPEG for parsing/mutation tests.
- `tiny_jpeg_path(tmp_path, tiny_jpeg_bytes) -> Path`: Writes the tiny JPEG to disk.
- `simple_entropy_ranges() -> list[EntropyRange]`: Simple entropy range list for tests.

### `tests/test_api.py`
Tests:
- `test_api_run_report_only`: Ensures API `run()` returns a zeroed result when `report_only=True`.

### `tests/test_cli.py`
Tests:
- `test_parse_args`: Basic CLI parsing.
- `test_parse_args_repeat_alias`: `--repeat` alias.
- `test_log_context_and_validate`: Debug logging and validation behavior.
- `test_run_phases`: Smoke test for CLI phase wrappers.
- `test_main_success_and_validation_error`: CLI `main()` success and validation failure.
- `test_main_wave_only_skips_mutation`: Source-only mode behavior.

### `tests/test_mutate.py`
Tests:
- `test_parse_bits_and_mode`: `bitflip` parsing and invalid cases.
- `test_mutate_byte_variants`: Mutation primitives and overflow wrap.
- `test_entropy_length_and_offset_selection`: Entropy length and selection helpers.
- `test_mutable_offsets_step_selection`: Mutability and cumulative selection.
- `test_sequential_step_selection`: Sequential selection and validation.
- `test_set_seed_and_output_helpers`: Seed derivation and naming helpers.
- `test_write_mutation_files_and_dispatch`: Independent/cumulative/sequential writers and dispatcher.

### `tests/test_jpeg_parse.py`
Tests:
- Validates JPEG parsing and entropy range detection.
- Exercises segment decoding basics and error cases.

### `tests/test_report.py`
Tests:
- Exercises report formatting, explanations, and hex rendering.

### `tests/test_media.py`
Tests:
- Verifies GIF frame loading and write behavior with mocks.

### `tests/test_ssim_analysis.py`
Tests:
- Verifies filename parsing for cumulative IDs.
- Validates grouping and mixed-step-size rejection.
- Tests metric chart generation with controlled inputs.

### `tests/test_wave_analysis.py`
Tests:
- Validates entropy stream assembly, bit conversion, and rolling computations.
- Ensures chart writers handle sizes and validation.

### `tests/test_dct_analysis.py`
Tests:
- Validates DCT basis, block mapping, and heatmap writer error cases.

### `tests/test_models_debug.py`
Tests:
- Verifies dataclasses and debug instrumentation helpers.

# JPEG Fault Tolerance Investigation — Code Reference

This document is an extended, file-by-file reference for all Python classes and functions in this repo, plus how they are tied together after the API refactor.

## Summary Of Work So Far
- Added a third mutation strategy: `sequential` (contiguous mutable bytes starting from a seed).
- Added two mutation modes: `ff` and `00` (direct replacement).
- Added `--overflow-wrap` to wrap `add1`/`sub1` at byte boundaries.
- Refactored the CLI to call a new core API layer (`jpeg_fault/core/api.py`).
- Updated tests and docs.
- Tests pass.

## End-To-End Wiring (How It All Connects)
- `jpg_fault_tolerance.py` is the executable entrypoint and calls `jpeg_fault.core.cli.main()`.
- `jpeg_fault/core/cli.py` parses CLI args and converts them to `RunOptions` (from the API layer).
- `jpeg_fault/core/api.py` orchestrates the full run: parse JPEG, print report, mutate, post-process, and run source-only analyses.
- `jpeg_fault/core/jpeg_parse.py` parses JPEG structure and finds entropy ranges.
- `jpeg_fault/core/report.py` renders the human-readable, colorized JPEG report.
- `jpeg_fault/core/mutate.py` owns all mutation logic, sampling, and file output.
- `jpeg_fault/core/media.py` builds GIFs from mutation outputs.
- `jpeg_fault/core/ssim_analysis.py` computes metrics and writes charts.
- `jpeg_fault/core/wave_analysis.py` writes entropy stream wave charts.
- `jpeg_fault/core/dct_analysis.py` writes DC/AC energy heatmaps.
- `jpeg_fault/core/debug.py` provides lightweight debug logging and optional function instrumentation.

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
- `analysis_deps(metric: str) -> Tuple[Any, Any, Any, Any]`: Imports Pillow/matplotlib/numpy/scikit-image as needed.

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
- `wave_deps() -> Tuple[Any, Any]`: Imports numpy/matplotlib with helpful error.
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
- `dct_deps() -> Tuple[Any, Any, Any]`: Imports Pillow/matplotlib/numpy with error.
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
- File browser with JPEG-only list.
- Info tab with segment list, details, entropy, APP0 decoding and editing.
- Tools tab with APPn insertion helper.

Notable behavior:
- Info → Segments includes health checks with OK/WARN/FAIL and reasons.
- APP0 editor supports simple fields and advanced raw hex, with live preview.

### Info Tab Details
- **General**: file size, segment count, scan count, total entropy bytes.
- **Segments**: one-line segment summary plus health status.
- **Details**: expanded per-segment explanations (from `report.explain_segment`).
- **Entropy**: entropy ranges per scan.
- **APP0**: decoded fields, legend, and colorized hex dump.

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

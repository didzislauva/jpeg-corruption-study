# JPEG Corruption Study: Explicit Project Summary

## Project Identity

This repository is a command-line JPEG analysis and mutation tool focused on **fault tolerance of JPEG entropy-coded data**.

The core idea is:

- Parse a JPEG file structurally.
- Identify the entropy-coded byte ranges that follow each `SOS` marker.
- Mutate bytes only inside those entropy-coded ranges.
- Keep markers, headers, tables, and metadata intact.
- Generate mutated JPEGs and analyze how corruption affects decoding and visual similarity.

This project now also includes **non-mutation analysis modes** that operate directly on the original source JPEG:

- entropy-stream byte and bit wave plots
- sliding-window entropy-stream statistics
- `8x8` block DCT-derived heatmaps (`DC` and `AC energy`)


## What The Tool Does End To End

For a given input JPEG, the tool can do all of the following:

- Parse JPEG segments and print a detailed human-readable report.
- Detect all entropy-coded scan ranges.
- Randomly sample entropy byte offsets.
- Mutate those offsets using arithmetic or bit-flip rules.
- Generate either independent mutations or cumulative mutation progressions.
- Generate sequential cumulative-style mutations starting from a seeded point.
- Repeat cumulative experiments using deterministic per-set seeds derived from a master seed.
- Build GIFs from generated mutated images.
- Compute image-quality metrics against the original image:
  - `SSIM`
  - `PSNR`
  - `MSE`
  - `MAE`
- Plot metric panels for repeated cumulative experiments.
- Plot entropy-stream wave charts from the original JPEG.
- Plot DCT-derived `DC` and `AC energy` heatmaps from the decoded original image.


## Current Entry Point

- [jpg_fault_tolerance.py](jpg_fault_tolerance.py)

This file is intentionally thin. It just imports and runs:

- `jpeg_fault.core.cli.main`

All real logic lives under:

- `jpeg_fault/core/`


## Current Module Layout

- [cli.py](jpeg_fault/core/cli.py)
  Main CLI, argument parsing, orchestration, mode switching, phase execution.

- [models.py](jpeg_fault/core/models.py)
  Shared dataclasses:
  - `Segment`
  - `EntropyRange`

- [jpeg_parse.py](jpeg_fault/core/jpeg_parse.py)
  Low-level JPEG parsing and segment decoding helpers.

- [report.py](jpeg_fault/core/report.py)
  Human-readable segment reporting and colored terminal formatting.

- [mutate.py](jpeg_fault/core/mutate.py)
  Mutation selection, mutation application, cumulative set handling, output naming.

- [media.py](jpeg_fault/core/media.py)
  GIF generation from generated mutation files.

- [ssim_analysis.py](jpeg_fault/core/ssim_analysis.py)
  Metric computation and chart generation for cumulative mutation outputs.

- [wave_analysis.py](jpeg_fault/core/wave_analysis.py)
  Entropy stream wave charts and sliding-window stream statistics.

- [entropy_trace.py](jpeg_fault/core/entropy_trace.py)
  Baseline sequential entropy scan tracing with block-level bit/byte provenance.

- [dct_heatmap.py](jpeg_fault/core/plugins/_shared/dct_heatmap.py)
  `8x8` block DCT-based visual analysis on decoded source image luminance.

- [debug.py](jpeg_fault/core/debug.py)
  Minimal debug logger.

- [tui/app.py](jpeg_fault/core/tui/app.py)
  Main Textual application shell and top-level TUI orchestration.

- [tui/segments_basic.py](jpeg_fault/core/tui/segments_basic.py)
  APP0, SOFn, and DRI TUI workspaces.

- [tui/segments_tables.py](jpeg_fault/core/tui/segments_tables.py)
  DHT and DQT TUI workspaces.

- [tui/segments_appn.py](jpeg_fault/core/tui/segments_appn.py)
  APP1, APP2, and generic APPn TUI workspaces.

- [tui/hex.py](jpeg_fault/core/tui/hex.py)
  Full-file hex pane support.

- [analysis_registry.py](jpeg_fault/core/analysis_registry.py)
  Analysis plugin registry and loader.

- [tui_plugin_registry.py](jpeg_fault/core/tui_plugin_registry.py)
  TUI plugin panel registry.


## Current Status Snapshot

- CLI/API flow is stable.
- TUI startup is currently working.
- The real TUI implementation now lives under `jpeg_fault/core/tui/`.
- The old top-level `tui_*` compatibility modules were removed; imports/tests now target `jpeg_fault.core.tui.*` directly.
- Plugin panel lifecycle issues in the TUI were fixed in this session.
- Chart-producing analyses now force matplotlib to the headless `Agg` backend to avoid Tk/thread crashes from TUI workers.
- The built-in analysis plugins now include `entropy_wave`, `entropy_trace`, `sliding_wave`, `dc_heatmap`, and `ac_energy_heatmap`.
- `entropy_trace` now provides a plugin-first baseline sequential scan tracer that maps scan bits to decoded blocks, coefficients, and source file-byte provenance.
- The TUI Info panel now includes a Trace workspace that reuses `entropy_trace.py` for per-scan block inspection.
- The built-in mutation plugins now include `mutation_55`, `mutation_aa`, and `mutation_insert_appn`.
- `dc_heatmap` and `ac_energy_heatmap` now expose `cmap`, `plane_mode`, and `block_size`, and default unnamed outputs to descriptive filenames in the current working directory.
- The TUI now launches the migrated wave/DC/AC analyses through the `Graphic Output` plugin tabs instead of the old dedicated Outputs-panel fields.
- The TUI `Core Mutations` page now combines mutation settings, strategy settings, and Run controls, plus a help column with an equivalent CLI command.
- The TUI exposes `55` and `aa` under `Plugin Mutations`, and `insert_appn` under the plugin-hosted `Tools` panel.
- The generic `Plugins` panel is now a read-only clickable inventory for analysis plugins; clicking an entry shows help/details instead of toggling selection.
- The TUI Segments pane now lists unused standard JPEG sections in a muted block under the detected segments.
- SOF0, SOS, DQT, and DHT structured editors can highlight the corresponding serialized bytes in their left hex views based on the current value selection.
- SOF markers are now grouped under an outer SOFn tab with one subtab per frame section.
- SOS markers now have a dedicated editable workspace with header/components/flow/links/edit views.
- SOF and SOS pane rendering now scopes widget lookup through the active pane root, and targeted debug logs can be written to `/tmp/jpeg_sof_debug.log` and `/tmp/jpeg_sos_debug.log` when `Debug logging` is enabled.
- Plugin context building now lives in a shared helper layer used by both `api.py` and the TUI instead of relying on API-private helpers.
- Analysis and mutation registry loading now share one package-scanning helper instead of duplicating loader logic.
- APP2 editor plumbing now centralizes ICC field collection/update generation, and all APP2 edit inputs trigger preview refresh consistently.
- JPEG/EXIF/ICC protocol constants now live under `jpeg_fault/core/constants/` instead of being repeated inline across parser and TUI code.
- `debug.py` is now just the lightweight debug logging layer; the unused instrumentation scaffolding was removed.
- The latest focused TUI verification is green:
  - `71 passed` for `tests/test_tui_segments.py tests/test_tui_plugins.py tests/test_tui_app2.py tests/test_mutation_plugins_builtin.py`
  - `20 passed` for `tests/test_tui_plugins.py tests/test_tui_options.py tests/test_tui_app2.py`

## Current Mutation UX Notes

- TUI mutation mode is now a dropdown with `bitflip` split into a second input for the bit list.
- The help column explains mutation and strategy behavior in prose.
- The current code semantics are:
  - `independent`: random offsets; each file starts from the original
  - `cumulative`: random mutable offsets accumulated across files
  - `sequential`: contiguous mutable offsets accumulated across files
- Important caveat: `sequential` is contiguous in mutable-offset order, not guaranteed contiguous in raw file-byte order.
- Current sequential output filenames still use the shared `cum_...` prefix because they reuse cumulative naming helpers. Behavior tested correctly in one reproduced run, but the naming is misleading.


## Remaining Priority

The biggest remaining risk is still TUI maintainability, not parser correctness or CLI orchestration.

What is left:

- reduce repeated editor mechanics across APP1 and the remaining DHT special cases
- improve runtime-oriented TUI/plugin coverage beyond fake widgets
- extend the plugin system with more real plugin panels now that the shell is stable
- polish the new TUI Trace workspace and extend it with richer byte-boundary highlighting and broader progressive support
- tighten mutation UX/help wording so the TUI explains `sample`, `cumulative`, and `sequential` precisely

## Plugin Placement Rule

- Keep all built-in plugin implementations under `jpeg_fault/core/plugins/<plugin_name>/plugin.py`.
- Plugin kind should be defined by what the plugin registers with, not by placing different families outside `plugins`.
- If a new plugin family is introduced later, keep it in `jpeg_fault/core/plugins/` and add the matching registry/type definitions for that family.


## Core Data Model

### `Segment`

Defined in [models.py](jpeg_fault/core/models.py).

Fields:

- `marker: int`
- `offset: int`
- `name: str`
- `length_field: Optional[int]`
- `payload_offset: Optional[int]`
- `payload_length: Optional[int]`
- `total_length: int`

Meaning:

- Represents one JPEG segment marker plus its associated metadata.
- For no-length markers like `SOI` and `EOI`, `length_field`, `payload_offset`, and `payload_length` are `None`.

### `EntropyRange`

Defined in [models.py](jpeg_fault/core/models.py).

Fields:

- `start: int`
- `end: int`
- `scan_index: int`

Meaning:

- Represents one contiguous entropy-coded data range.
- `start` is inclusive.
- `end` is exclusive.
- `scan_index` identifies which scan the range belongs to.


## JPEG Parsing Behavior

Implemented primarily in [jpeg_parse.py](jpeg_fault/core/jpeg_parse.py).

### Supported parsing model

The parser:

- Verifies that the file begins with `FF D8` (`SOI`).
- Iterates segment-by-segment through the JPEG.
- Recognizes standard marker names such as:
  - `SOI`
  - `EOI`
  - `SOF0`
  - `DHT`
  - `DQT`
  - `DRI`
  - `SOS`
  - `COM`
  - `APP0..APP15`
- Extracts segment payload offsets and lengths.

### Entropy range detection

When the parser hits `SOS`:

- It computes the end of the `SOS` payload.
- The entropy-coded stream begins immediately after that payload.
- It scans forward until the next real marker.

The parser explicitly treats these cases as **not terminating scan data**:

- stuffed bytes `FF 00`
- restart markers `FF D0` through `FF D7`

The entropy range ends at the next non-stuffed, non-restart marker.

### Lightweight segment decoding

The parser decodes selected payloads for reporting:

- `APP0` / JFIF or JFXX
- `DQT`
- `DHT`
- `SOF0`
- `SOS`
- `DRI`

This decoding is descriptive only. It is not used to re-encode JPEG data.


## Human Report Behavior

Implemented in [report.py](jpeg_fault/core/report.py).

The report prints:

- file path
- total file size
- first 64 bytes, color-classified as:
  - marker
  - length
  - payload
  - other
- a segment-by-segment breakdown including:
  - segment index
  - segment name
  - start offset
  - end offset
  - marker hex
  - payload length
  - total length
  - short hex preview
  - explanatory text
- a summary of entropy-coded scan ranges

Color modes:

- `auto`
- `always`
- `never`


## Mutation System

Implemented in [mutate.py](jpeg_fault/core/mutate.py).

### Mutation modes

Supported `--mutate` modes:

- `add1`
- `sub1`
- `flipall`
- `ff`
- `00`
- `bitflip:<bits>`

Examples:

- `bitflip:0`
- `bitflip:0,1,3`
- `bitflip:msb`
- `bitflip:lsb`

### Bitflip semantics

Bit parsing:

- `msb` means bit `7`
- `lsb` means bit `0`
- explicit bit list must contain only integers `0..7`

Independent mode behavior:

- For `bitflip`, each listed bit produces a separate output file.
- Example:
  - `bitflip:0,1`
  - one offset
  - two output files

Cumulative mode behavior:

- All listed bits are applied together to the same byte.
- The code builds one XOR mask from the provided bits.
- Example:
  - `bitflip:0,3`
  - cumulative mutation flips both bits in that byte
  - output tag is `bit0-3`

### Which bytes are mutable

For mode constraints:

- `add1` cannot modify `0xFF`
- `sub1` cannot modify `0x00`
- `flipall` can modify any byte
- `ff` cannot modify `0xFF`
- `00` cannot modify `0x00`
- `bitflip` can modify any byte

This matters mainly for cumulative mode because cumulative planning must ensure enough mutable bytes exist.

### Overflow wrapping for add1/sub1

By default:

- `add1` leaves `0xFF` unchanged
- `sub1` leaves `0x00` unchanged

If `--overflow-wrap` is set:

- `add1` wraps `0xFF -> 0x00`
- `sub1` wraps `0x00 -> 0xFF`


## Mutation Strategies

### 1. Independent

This is the default strategy.

Meaning:

- Each output file starts from the original JPEG.
- One selected offset is mutated.
- Then the original byte is restored before moving to the next selected offset.

Consequence:

- Files are unrelated except that they share the same source image.
- There is no accumulation across outputs.

### 2. Cumulative

Meaning:

- A random sequence of offsets is chosen.
- Output step `N` contains all prior mutations plus the new mutation(s) for step `N`.

Consequence:

- Image 1 has the first step’s mutations.
- Image 2 has image 1’s mutations plus step 2’s new mutations.
- Image `N` contains all mutations from steps `1..N`.

### 3. Sequential

Meaning:

- A start position is chosen in the mutable entropy stream using the seed.
- Output step `N` contains all prior mutations plus the next sequential bytes.
- Each step adds `--step` new bytes, like cumulative.

Consequence:

- Image 1 mutates the first step’s bytes in the sequence.
- Image 2 mutates image 1’s bytes plus the next step’s bytes.
- Positions are contiguous rather than randomly scattered.


## `--sample`, `--step`, and `--repeats` Semantics

These are the most important CLI semantics in this project.

### `--sample`

Meaning depends on strategy.

Independent mode:

- Number of random entropy byte offsets to select.
- `0` means all entropy offsets.

Cumulative mode:

- Number of cumulative output images per set.
- `0` means as many full cumulative steps as possible.

Sequential mode:

- Number of sequential output images per set.
- `0` means as many full sequential steps as possible.

### `--step`

Only valid for cumulative or sequential mode.

Meaning:

- Number of **new entropy bytes** added per cumulative image.

Examples:

- `--sample 100 --step 1`
  - 100 images
  - cumulative affected bytes: `1, 2, 3, ..., 100`

- `--sample 100 --step 2`
  - 100 images
  - cumulative affected bytes: `2, 4, 6, ..., 200`

Constraint:

- Requested total mutable offsets per set is `sample * step`.
- That must not exceed the number of mutable entropy bytes.

Special case:

- If `--sample 0`, the tool uses:
  - `floor(mutable_entropy_bytes / step)`
  cumulative images.

### `--repeats`

Only valid for cumulative mode.

Meaning:

- Number of independent cumulative experiment sets to generate.

If `--repeats 10`:

- you get 10 sets
- each set has its own randomized offset order
- each set is deterministic under the master seed

Alias:

- `--repeat` is accepted and maps to the same argument.


## Randomness Model

Implemented in [mutate.py](jpeg_fault/core/mutate.py).

### Independent mode randomness

- A `random.Random(seed)` instance is used.
- Offsets are selected by sampling from the entropy stream index space.

### Cumulative mode randomness

- The master seed is expanded into one unique set seed per repeat.
- This is done by `derive_set_seeds(master_seed, repeats)`.
- The derived seeds are deterministic for the same CLI inputs.
- Each set then uses its own seed to sample the offsets for that set.

Result:

- Same arguments reproduce the same outputs exactly.
- Different sets are distinct from each other.


## How Offsets Are Selected

### Entropy-stream indexing

The code treats all entropy ranges as one logical concatenated stream.

It does not require the entropy data to be one physical contiguous range.

Supporting helpers:

- `total_entropy_length`
- `build_cumulative`
- `index_to_offset`

This allows random selection over the full entropy stream, even with multiple scans.

### Independent selection

- Random sample over logical entropy indices.
- Each chosen logical index is mapped back to a real file offset.

### Cumulative selection

The current cumulative planner uses only **mutable** offsets for the chosen mutation mode.

It samples concrete file offsets from the mutable offset list directly, then groups them into chunks of size `step`.


## Output Naming

### Independent outputs

Filename structure:

- `{base}_off_{OFFSET}_orig_{OLD}_new_{NEW}_mut_{TAG}.jpg`

Example properties encoded:

- offset
- original byte value
- new byte value
- mutation tag

### Cumulative outputs

Filename structure:

- single-set:
  - `{base}_cum_{STEP}_step_{STEP_SIZE}_off_{OFFSET}_orig_{OLD}_new_{NEW}_mut_{TAG}.jpg`

- repeated sets:
  - `{base}_set_{SET_ID}_cum_{STEP}_step_{STEP_SIZE}_off_{OFFSET}_orig_{OLD}_new_{NEW}_mut_{TAG}.jpg`

If `--repeats > 1`, files are placed in:

- `output_dir/set_0001/`
- `output_dir/set_0002/`
- etc.

Important detail:

- In cumulative filenames, the encoded offset/value/tag corresponds to the **last byte changed in that cumulative step**, not the full history of all prior changes.


## Source-Only vs Mutation-Dependent Modes

Implemented in [cli.py](jpeg_fault/core/cli.py).

The CLI distinguishes between:

### Mutation-dependent outputs

These require generated mutated JPEG files:

- `--gif`
- `--ssim-chart`
- `--metrics-chart-prefix`

### Source-only outputs

These can operate directly on the original input JPEG:

- `--wave-chart`
- `--sliding-wave-chart`
- `--dc-heatmap`
- `--ac-energy-heatmap`

### Source-only execution shortcut

If the command requests only source-only outputs and no mutation-dependent outputs:

- the tool skips mutation generation entirely
- no mutation files are written
- analysis runs directly on the source JPEG

This behavior was added intentionally to avoid unnecessary work for entropy-stream and DCT visualizations.


## GIF Generation

Implemented in [media.py](jpeg_fault/core/media.py).

Behavior:

- Opens all matched mutation files that decode successfully with Pillow.
- Converts frames to `RGB`.
- Optionally shuffles frame order using the main seed.
- Writes a GIF using:
  - `--gif-fps`
  - `--gif-loop`

If no mutation images decode:

- it returns `0` frames rather than crashing.


## Metric Analysis: SSIM, PSNR, MSE, MAE

Implemented in [ssim_analysis.py](jpeg_fault/core/ssim_analysis.py).

### Metrics supported

- `ssim`
- `psnr`
- `mse`
- `mae`

### Important comparison baseline

All metric calculations compare each mutated image to the **original input image**, not to the previous cumulative image.

This is a critical project behavior.

### Decode failure handling

If a mutated file cannot be decoded:

- its metric value is `None`
- internally this becomes `NaN` in the score matrix
- it is excluded from quantile summaries
- it still affects decode-success statistics

### Multiprocessing

Metric computation defaults to:

- all detected CPU cores

Controlled by:

- `--jobs`

Behavior:

- `--jobs` omitted: use all detected cores
- `--jobs 1`: sequential path
- `--jobs N`: use up to `min(N, detected_cores)`

### Cumulative path grouping

Metric analysis expects cumulative outputs and groups them by parsing file names:

- set id
- cumulative step index
- step size

It rejects mixed cumulative step sizes inside the same analysis input set.

### X-axis meaning in metric charts

The X-axis is:

- `affected_bytes = cumulative_step * step_size`

This was explicitly fixed to avoid showing cumulative step count instead of actual bytes affected.

### Three-panel metric chart format

For every selected metric, the chart contains:

- Panel A:
  every repetition plotted as its own line

- Panel B:
  quantile summary lines:
  - median
  - `q25`
  - `q75`
  - `q10`
  - `q90`

- Panel C:
  decode success rate

### Quantile caveat

Panel B uses only decodable samples at each X position.

This means the effective sample size can shrink as corruption increases.

That behavior is currently known and should be interpreted carefully.


## Entropy Stream Wave Analysis

Implemented in [wave_analysis.py](jpeg_fault/core/wave_analysis.py).

These analyses operate on the concatenated entropy-coded bytes from all scans.

### `--wave-chart`

Produces a 2-panel chart:

- Panel 1:
  raw byte values over entropy byte index

- Panel 2:
  unpacked bits over bit index

This is a visualization of the encoded stream as a sequence, not a statement that JPEG entropy data is physically a wave.

### `--sliding-wave-chart`

Produces a 3-panel chart over a rolling window:

- rolling mean
- rolling variance
- rolling entropy

Window size:

- controlled by `--wave-window`
- default is `256`

### Downsampling

To keep charts manageable for long streams:

- byte and sliding-value series are downsampled to about `25,000` points
- bit series are downsampled to about `50,000` points

### Entropy definition here

Rolling entropy is computed over byte value frequencies in the current window:

- histogram over 256 byte values
- Shannon entropy in bits

It is **not** JPEG symbol entropy after Huffman decoding.


## DCT-Based Heatmaps

Implemented in [dct_heatmap.py](jpeg_fault/core/plugins/_shared/dct_heatmap.py).

These are source-image analyses, not direct bitstream decoders.

Important:

- They operate on the **decoded image**.
- They do **not** parse JPEG coefficient blocks from the compressed bitstream.
- They recompute an `8x8` block DCT on the decoded luminance plane.

This is still useful for visualization, but it is not equivalent to extracting the original JPEG quantized coefficients.

### Luminance conversion

The tool converts decoded `RGB` to luma using:

- `0.299 * R + 0.587 * G + 0.114 * B`

### Block grid handling

- The image is cropped to a multiple of `8x8`.
- If either cropped dimension is smaller than `8`, the heatmap analysis fails.

### `--dc-heatmap`

Produces a heatmap where each cell corresponds to one `8x8` block and stores:

- the block DCT coefficient at position `(0, 0)`

This gives a coarse low-frequency structure map.

### `--ac-energy-heatmap`

Produces a heatmap where each cell corresponds to one `8x8` block and stores:

- `sum(abs(coefficients)) - abs(DC)`

Meaning:

- total non-DC coefficient magnitude per block

This is a simple block-level texture/detail energy measure.


## Debug Logging

Implemented in [debug.py](jpeg_fault/core/debug.py).

Current philosophy:

- Debug output is **selective**.
- The project previously had broad function entry/exit tracing, but that was removed because it was too noisy.

Current debug logs include targeted information such as:

- input and entropy summary
- selected options
- mutation generation timings
- chosen repeat seeds
- number of files found for analysis
- detected CPU cores and used worker count
- metric compute timings
- decode success counts
- wave chart sizing and downsampling
- DCT heatmap block sizes and timing

Debug output goes to:

- `stderr`

Enabled by:

- `--debug`


## CLI Behavior Summary

Implemented in [cli.py](jpeg_fault/core/cli.py).

### Main execution order

High-level order:

1. Parse arguments.
2. Read input JPEG bytes.
3. Parse JPEG structure.
4. Print the report.
5. If `--report-only`, stop.
6. Validate runtime arguments.
7. Decide whether this is:
   - source-only mode
   - mutation-producing mode
8. If mutation-producing:
   - generate mutations
   - discover files created in this run
   - run GIF and/or metric phases if requested
9. Independently run source-only analyses if requested.
10. Exit.

### Post-processing file selection

When mutation generation runs, the CLI tries to analyze only files produced by the current run:

- records matching files before mutation
- records matching files after mutation
- uses set difference to find new files

Fallback:

- if no new files are detected, it falls back to all matching mutation files


## TUI Overview

The project includes a Textual fullscreen TUI:

- Launch with `./jpg_fault_tolerance.py --tui` (alias `--gui`)
- Left menu: Input/Info/Mutation/Outputs/Plugins
- File browser shows directories; a JPEG-only list is shown for selection
- Selecting a JPEG auto-loads Info views and updates the preview

### Info Tabs

- General: file size, segments, scans, entropy bytes
- Segments: per-segment summary with health status, entropy ranges, and issues
- Details: per-segment explanations
- APP0: decoded fields + colorized hex view
- SOFn: per-section subtabs; SOF0 keeps frame/components/tables/edit views and other SOF markers are read-only
- SOS: per-section subtabs with header/components/flow/links/edit views
- DRI: restart-interval workspace with summary/effect/edit views
- APPn: per-segment subtabs for APP1 (EXIF) and APP2 (ICC)
- DHT: per-segment Huffman-table workspaces with bytes/info, counts, symbols, usage, codes, and edit views
- DQT: per-segment quantization-table workspaces with bytes/info, grid, zigzag, stats, usage, heatmap, and edit views
- Trace: per-scan manual-load entropy tracing with paged MCU/block navigation
- Hex: full-file hex view with segment coloring and clickable legend

### Segment Health Checks

- OK: no detected issues
- WARN: unusual but non-fatal (e.g., gaps between markers)
- FAIL: structural problems (bounds/overlaps/missing data)

### APP0 Editor

- Simple mode: structured fields (identifier, version, units, densities, thumbnails)
- Advanced mode: raw hex payload editor
- Manual length toggle (dangerous): allows length field mismatch
- Live preview updates decoded + hex view on edit
- Saves a new file (`*_app0_edit.jpg`)

### SOF0 / SOS / DRI / DHT / DQT Editors

- SOF0 now lives inside the outer SOFn section and keeps a dedicated frame-header workspace with structured/raw editing and live preview.
- SOS has a dedicated scan-header workspace with structured/raw editing, component linkage, and live preview.
- DRI has a dedicated restart-interval workspace with structured/raw editing and live preview.
- DHT has a dedicated Huffman-table workspace with structured/raw editing and canonical-code/usage views.
- DQT has a dedicated quantization-table workspace with structured/raw editing, grid/zigzag/stats/usage/heatmap views.
- SOF0, SOS, DQT, and DHT can highlight serialized bytes in the left hex pane when the caret is on a structured-editor value.
- DHT and DQT keep the active editor stable while typing; raw/structured editor content syncs when switching modes.

### `insert_appn` Mutation Plugin

- inserts a custom APPn segment with payload hex or file
- inserts after the last APPn segment near file start
- writes one segment-level output JPEG through the mutation-plugin pipeline
- payload limit: 65,533 bytes


## API Layer

The core API lives in `jpeg_fault/core/api.py` and is the primary integration
surface for future UI layers (TUI/GUI) and scripting.


## Programming Rule: Function Size

All new functions should be modular and kept to 60 lines or fewer where
practical. If a function grows beyond this, refactor into helper functions.


## APPn Insertion Helper

There is a separate helper CLI for inserting custom APPn segments:

- `./jpg_fault_tools.py insert-appn <input.jpg> --appn N --payload-hex "..."`
- Optional `--identifier` prefix and `--payload-file` input
- Default output: `<stem>_appNN.jpg`

Implementation:

- `jpeg_fault/core/tools.py` for insertion helpers
- `jpg_fault_tools.py` for CLI wiring


## Handoff Summary (For Next Session)

- Core mutation system supports independent, cumulative, and sequential strategies.
- New mutation modes: `ff`, `00`, and overflow wrapping for `add1/sub1`.
- Textual TUI is the primary interactive UI (`--tui`), with:
  - File browser + JPEG-only list
  - Live preview panel with dimensions/size
  - Info tabs (General/Segments/Details/APP0/SOFn/SOS/DRI/APPn/DHT/DQT/Trace/Hex)
  - APP0 editor (simple + advanced, live preview, save new file)
  - SOFn workspace with editable SOF0 and read-only other SOF markers
  - SOS workspace/editor
  - DRI workspace/editor
  - DHT workspace/editor
  - DQT workspace/editor
  - APP1 EXIF decoder/editor and APP2 ICC decoder/editor
  - Plugin Mutations tabs for `55` and `aa`
  - Tools plugin tab for `insert_appn`
  - generic Plugins panel as a read-only clickable analysis inventory
- API layer (`jpeg_fault/core/api.py`) is the stable integration surface for UI layers.
- Function size guideline: keep functions ≤ 60 lines; refactor as needed.


## Error Handling and Validation

Current validations include:

- `--repeats` invalid outside cumulative mode
- `--step` invalid outside cumulative mode
- `--step < 1` rejected
- `--wave-window < 1` rejected
- cumulative total mutable offsets cannot exceed available mutable entropy bytes
- mixed cumulative step sizes in metric analysis are rejected
- source image too small for `8x8` DCT heatmaps is rejected
- missing optional dependencies are reported with installation hints


## Optional Dependencies by Feature

### Always needed

- Python itself

### GIF

- Pillow

### Metric charts

- Pillow
- matplotlib
- numpy
- scikit-image for `SSIM`

Note:

- The code path imports `scikit-image` only when `metric == "ssim"`.

### Wave charts

- matplotlib
- numpy

### DCT heatmaps

- Pillow
- matplotlib
- numpy

### Tests

- pytest


## Tests Present

Current test suite lives under:

- `tests/`

Key files:

- [test_cli.py](tests/test_cli.py)
- [test_mutate.py](tests/test_mutate.py)
- [test_jpeg_parse.py](tests/test_jpeg_parse.py)
- [test_report.py](tests/test_report.py)
- [test_media.py](tests/test_media.py)
- [test_ssim_analysis.py](tests/test_ssim_analysis.py)
- [test_wave_analysis.py](tests/test_wave_analysis.py)
- [test_dct_analysis.py](tests/test_dct_analysis.py)
- [test_models_debug.py](tests/test_models_debug.py)
- [conftest.py](tests/conftest.py)

### What tests cover

The tests currently cover:

- CLI parsing and validation
- report and parser basics
- mutation logic
- repeat aliasing
- cumulative step semantics
- metric helpers and chart generation
- multiprocessing metric path via monkeypatching
- wave analysis helpers and output files
- DCT heatmap helpers and output files
- source-only mode skipping mutations


## Known Design Choices and Limitations

These are not bugs by themselves. They are the current design.

### 1. DCT heatmaps are image-domain DCT, not JPEG coefficient extraction

The heatmaps are based on:

- decoded RGB image
- converted to luma
- fresh `8x8` DCT

They are useful but not the same as visualizing the actual Huffman-decoded quantized JPEG coefficients.

### 2. Metric quantiles exclude undecodable files

Panel B in metric charts summarizes only decodable images.

That means:

- sample size may shrink with increasing corruption
- quantile trends should be read together with Panel C decode success

### 3. Cumulative filename metadata records only the last offset changed in that step

It does not encode the full mutation history.

### 4. Wave charts visualize byte and bit sequences directly

These are exploratory visualizations.

They are not physical signal plots and not semantically aligned to JPEG block structure.

### 5. Source-only mode currently excludes metric charts

Metric charts still require mutation files because they compare multiple generated outputs.


## Practical Example Command Families

### Report only

```bash
./jpg_fault_tolerance.py portret.jpg --report-only
```

### Independent mutations

```bash
./jpg_fault_tolerance.py portret.jpg --mutation-apply independent --mutate add1 --sample 100 --seed 3
```

### Cumulative mutations with 2 bytes added per image

```bash
./jpg_fault_tolerance.py portret.jpg --mutation-apply cumulative --sample 100 --step 2 --seed 42
```

### Sequential mutations with overflow wrap

```bash
./jpg_fault_tolerance.py portret.jpg --mutation-apply sequential --sample 100 --step 2 --seed 42 --overflow-wrap
```

### Repeated cumulative experiment

```bash
./jpg_fault_tolerance.py portret.jpg --mutation-apply cumulative --sample 100 --step 2 --repeats 10 --seed 42
```

### Metric charts

```bash
./jpg_fault_tolerance.py portret.jpg --mutation-apply cumulative --sample 100 --step 2 --repeats 10 --seed 42 --metrics ssim,psnr,mse,mae --metrics-chart-prefix out_metrics
```

### Source-only entropy stream plots

```bash
./jpg_fault_tolerance.py portret.jpg --wave-chart wave.png --sliding-wave-chart slide.png --wave-window 256
```

### Source-only DCT heatmaps

```bash
./jpg_fault_tolerance.py portret.jpg --dc-heatmap dc.png --ac-energy-heatmap ac.png
```


## Current Verification Status

At the time of this summary, the implemented automated test suite passes with:

- `45 passed`

This reflects the state after:

- cumulative step support
- repeated cumulative sets
- metric chart support for `SSIM`, `PSNR`, `MSE`, `MAE`
- source-only wave charts
- source-only `DC` and `AC energy` heatmaps
- source-only mode skipping mutation generation


## Short Mental Model Of The Project

If someone needs the shortest technically correct mental model, it is this:

- The project mutates only JPEG entropy-coded bytes.
- It supports independent, cumulative, and sequential mutation experiments.
- Repeated cumulative experiments are deterministic under a master seed.
- Metric charts compare each mutated decode to the original image.
- Wave plots inspect the raw entropy byte stream.
- `DC` and `AC energy` heatmaps inspect the decoded image through recomputed `8x8` DCT blocks.
- The CLI avoids generating mutations when only source-only analyses are requested.

# jpeg_corruption_study

This project explores JPEG fault tolerance by creating controlled mutations inside the **entropy-coded data stream** (the bytes after each SOS header), while leaving JPEG headers and metadata intact. It also provides a rich, colorized report of JPEG segments and their structure.

The focus is to understand how small perturbations (byte arithmetic or bit flips) affect JPEG decoding and visual output.

## Example GIF

![Mutation GIF](mutations.gif)

## What The Script Does

1. **Parses JPEG structure**
   - Detects all JPEG segments (SOI, APPn, DQT, SOF, DHT, SOS, DRI, COM, EOI, etc.)
   - Prints detailed descriptions with:
     - segment type and purpose
     - structure and typical ranges
     - actual values decoded (where applicable)
     - marker/length/payload bytes with hex highlighting
     - start and end offsets

2. **Finds entropy-coded data ranges**
   - For each SOS segment, identifies the byte range of the compressed data stream
   - Handles byte-stuffing (0xFF 0x00) and restart markers

3. **Mutates bytes in the entropy stream**
   - Supports arithmetic changes (`add1`, `sub1`)
   - Supports direct replacement (`ff`, `00`)
   - Supports bit-flip modes (`bitflip:0,1,3`, `bitflip:msb`, `bitflip:lsb`)
   - Supports full byte inversion (`flipall`)
   - Optional overflow wrapping for `add1`/`sub1` (`--overflow-wrap`)
   - Supports two application strategies:
     - `independent` (default): each output starts from the original JPEG
     - `cumulative`: output `N` contains all prior mutations plus one new random offset
     - `sequential`: output `N` contains all prior mutations plus the next sequential bytes
   - Supports repeated cumulative experiment sets (`--repeats`)

4. **Monte Carlo sampling**
   - Limits the number of mutated offsets/steps to avoid huge output sets
   - Random sampling with reproducible seed

5. **Optional GIF generation**
   - Builds a GIF from the generated mutated images
   - Supports shuffling frame order for visual randomness

6. **Plugin-based extensions**
   - Supports analysis plugins selected from the CLI with `--analysis`
   - Supports mutation plugins selected from the CLI with `--mutation-plugin`
   - Validates plugin parameters centrally via repeated `plugin.param=value` flags
   - Provides richer host-prepared plugin context so built-in and future plugins can declare what they need instead of re-parsing everything themselves

## Files

- `jpg_fault_tolerance.py` — Thin CLI entrypoint wrapper
- `jpeg_fault/core/cli.py` — Argument parsing and execution flow
- `jpeg_fault/core/models.py` — Shared dataclasses (`Segment`, `EntropyRange`)
- `jpeg_fault/core/jpeg_parse.py` — JPEG parsing and segment decoding helpers
- `jpeg_fault/core/report.py` — Rich segment report rendering
- `jpeg_fault/core/mutate.py` — Mutation logic (independent/cumulative/repeats/step)
- `jpeg_fault/core/media.py` — GIF generation helpers
- `jpeg_fault/core/ssim_analysis.py` — SSIM metrics and plotting pipeline
- `jpeg_fault/core/wave_analysis.py` — Entropy stream wave and sliding-wave charts
- `jpeg_fault/core/dct_analysis.py` — DC and AC-energy heatmaps from decoded 8x8 DCT blocks
- `jpeg_fault/core/analysis_types.py` — Analysis plugin contracts, parameter specs, and validation
- `jpeg_fault/core/analysis_registry.py` — Analysis plugin registry and discovery
- `jpeg_fault/core/mutation_types.py` — Mutation plugin contracts
- `jpeg_fault/core/mutation_registry.py` — Mutation plugin registry and discovery
- `jpeg_fault/core/debug.py` — Debug logging helper
- `gradient.jpg` — Example input image
- `mutations/` — Default output directory for mutated files
- `README.md` — This documentation

## Requirements

- Python 3.8+
- The base CLI/report/mutation path uses only the Python standard library.
- This repo currently does not ship a pinned dependency manifest such as `requirements.txt` or `pyproject.toml`; optional packages are feature-gated in code.

Optional dependencies by feature:

- `pillow` for `--gif`
- `pillow`, `matplotlib`, and `numpy` for `--metrics-chart-prefix` with `psnr`, `mse`, or `mae`
- `pillow`, `matplotlib`, `numpy`, and `scikit-image` for `--ssim-chart` or `--metrics-chart-prefix` when `ssim` is included
- `matplotlib` and `numpy` for `--wave-chart` or `--sliding-wave-chart`
- `pillow`, `matplotlib`, and `numpy` for `--dc-heatmap` or `--ac-energy-heatmap`
- `textual` for the fullscreen TUI (`--tui` / `--gui`)
- `piexif` for APP1/EXIF editing inside the TUI; without it, the EXIF editor is disabled but the rest of the TUI still works
- `pytest` to run the test suite

Install Pillow if needed:

```bash
python3 -m pip install pillow
```

Install SSIM chart dependencies if needed:

```bash
python3 -m pip install matplotlib numpy scikit-image
```

Install metric chart dependencies for `psnr`, `mse`, or `mae` if needed:

```bash
python3 -m pip install pillow matplotlib numpy
```

Install wave chart dependencies if needed:

```bash
python3 -m pip install matplotlib numpy
```

Install test dependency if needed:

```bash
python3 -m pip install pytest
```

Install TUI dependency if needed:

```bash
python3 -m pip install textual
```

Install EXIF editing support for the TUI if needed:

```bash
python3 -m pip install piexif
```

## Usage

### Basic report only

```bash
./jpg_fault_tolerance.py gradient.jpg --report-only
```

## Tools

### Insert custom APPn segment

Use the helper CLI to insert a custom APPn segment with a payload.

```bash
./jpg_fault_tools.py insert-appn gradient.jpg --appn 15 --payload-hex "4D 59 54 41 47 00 01 02 03"
```

Add an identifier prefix:

```bash
./jpg_fault_tools.py insert-appn gradient.jpg --appn 15 --identifier "MYTAG\\0" --payload-hex "01 02 03"
```

Use a binary payload file:

```bash
./jpg_fault_tools.py insert-appn gradient.jpg --appn 2 --payload-file payload.bin -o out_with_app2.jpg
```

### Fullscreen TUI

```bash
./jpg_fault_tolerance.py --tui
```

The TUI includes:
- File browser with JPEG-only list
- Input panel with live JPEG preview (ASCII thumbnail), dimensions, and size
- Info tab with segment list, decoded details, entropy ranges, and full-hex view
- APP0 editor (simple fields + advanced raw hex) with live preview and save
- SOFn tab with per-section subtabs; SOF0 keeps the editable frame-header workspace and other SOF markers are shown in read-only frame/components/tables views
- DRI tab with restart-interval workspace: bytes/info on the left, summary/effect/edit views on the right
- APPn tab with per-segment subtabs (APP1/APP2 decoded, others shown read-only)
- DHT tab with per-segment workspaces: bytes/info on the left, table/counts/symbols/usage/codes/edit views on the right
- APP1 EXIF decoder with annotated hex/raw/table views and editable headers/IFDs
- APP2 ICC profile decoder with editable header/tags and live hex updates
- DQT tab with per-segment workspaces: bytes/info on the left, grid/zigzag/stats/usage/heatmap/edit views on the right
- Tools tab with a custom APPn writer
- Plugin panels for analysis-specific tools (currently includes entropy-wave, sliding-wave, DC-heatmap, and AC-energy output tabs; all four are launched there instead of from the Outputs panel)

### Plugins

The plugin system now has two families:

- analysis plugins: optional derived outputs such as charts, reports, and format-specific inspections
- mutation plugins: optional file-generating mutation passes that can participate in the main run

Current built-in plugin example:

- `entropy_wave` analysis plugin
- `sliding_wave` analysis plugin
- `dc_heatmap` analysis plugin
- `ac_energy_heatmap` analysis plugin

The legacy built-in wave options are still available:

- `--wave-chart`
- `--sliding-wave-chart`
- `--dc-heatmap`
- `--ac-energy-heatmap`

They now act as compatibility frontends over the `entropy_wave`, `sliding_wave`, `dc_heatmap`, and `ac_energy_heatmap` analysis plugins internally.

CLI plugin selection:

```bash
./jpg_fault_tolerance.py gradient.jpg --analysis entropy_wave
```

Pass plugin parameters with repeated `plugin.param=value` flags:

```bash
./jpg_fault_tolerance.py gradient.jpg \
  --analysis entropy_wave \
  --analysis-param entropy_wave.out_path=custom_wave.png
```

The built-in `entropy_wave` plugin currently supports:

- `out_path`: output image path
- `mode`: `byte`, `bit`, or `both` (default: `byte`)
- `transform`: `raw`, `diff1`, or `diff2` for the byte stream (default: `raw`)
- `csv_path`: optional CSV export path for the selected stream data

Example with byte-only output plus CSV export:

```bash
./jpg_fault_tolerance.py gradient.jpg \
  --analysis entropy_wave \
  --analysis-param entropy_wave.mode=byte \
  --analysis-param entropy_wave.transform=diff1 \
  --analysis-param entropy_wave.out_path=wave.png \
  --analysis-param entropy_wave.csv_path=wave.csv
```

Note: `transform` is currently supported only for byte-mode entropy waves.

The built-in `sliding_wave` plugin currently supports:

- `out_path`: output image path
- `csv_path`: optional CSV export path
- `window`: sliding-window size in bytes
- `stats`: comma-separated stats from `mean,variance,std,entropy,min,max,range,energy`
- `transform`: `raw`, `diff1`, or `diff2` applied before the sliding-window stats are computed

Example with multiple sliding stats plus CSV export:

```bash
./jpg_fault_tolerance.py gradient.jpg \
  --analysis sliding_wave \
  --analysis-param sliding_wave.window=512 \
  --analysis-param sliding_wave.transform=diff2 \
  --analysis-param sliding_wave.stats=mean,max,energy \
  --analysis-param sliding_wave.out_path=sliding.png \
  --analysis-param sliding_wave.csv_path=sliding.csv
```

The built-in `dc_heatmap` plugin currently supports:

- `out_path`: output image path; if omitted, defaults to `./<input>_dc_heatmap_<plane_mode>_b<block_size>.png`
- `cmap`: matplotlib colormap name (default: `coolwarm`)
- `plane_mode`: one of `bt601`, `bt709`, `average`, `lightness`, `max`, `min`, `red`, `green`, `blue` (default: `bt601`)
- `block_size`: transform block size (default: `8`)

Example:

```bash
./jpg_fault_tolerance.py gradient.jpg \
  --analysis dc_heatmap \
  --analysis-param dc_heatmap.out_path=dc.png \
  --analysis-param dc_heatmap.cmap=viridis \
  --analysis-param dc_heatmap.plane_mode=green \
  --analysis-param dc_heatmap.block_size=16
```

Note: `block_size=8` is the JPEG-native view. Other block sizes are exploratory and no longer correspond exactly to JPEG’s fixed 8x8 block structure.

The built-in `ac_energy_heatmap` plugin currently supports:

- `out_path`: output image path; if omitted, defaults to `./<input>_ac_energy_heatmap_<plane_mode>_b<block_size>.png`
- `cmap`: matplotlib colormap name (default: `magma`)
- `plane_mode`: one of `bt601`, `bt709`, `average`, `lightness`, `max`, `min`, `red`, `green`, `blue` (default: `bt601`)
- `block_size`: transform block size (default: `8`)

Example:

```bash
./jpg_fault_tolerance.py gradient.jpg \
  --analysis ac_energy_heatmap \
  --analysis-param ac_energy_heatmap.out_path=ac.png \
  --analysis-param ac_energy_heatmap.cmap=viridis \
  --analysis-param ac_energy_heatmap.plane_mode=green \
  --analysis-param ac_energy_heatmap.block_size=16
```

Note: `block_size=8` is the JPEG-native view. Other block sizes are exploratory and no longer correspond exactly to JPEG’s fixed 8x8 block structure.

Mutation plugins use the parallel CLI surface:

```bash
./jpg_fault_tolerance.py gradient.jpg \
  --mutation-plugin some_plugin_id \
  --mutation-plugin-param some_plugin_id.example=value
```

Plugin contracts are now more isolated than before:

- plugins declare typed params
- plugins declare what host-provided data they need
- the host prepares context such as source bytes, parsed JPEG structure, entropy ranges, decoded images, or mutation outputs
- TUI plugin tabs can be generated from plugin metadata instead of relying only on hand-wired widget conventions

## TUI Notes

- Info → Segments includes health checks with OK/WARN/FAIL and reasons.
- Info → Segments also shows standard JPEG sections not currently present in the file in a muted list.
- Info → APP0 shows decoded fields with color-matched hex preview.
- APP0 editor updates the preview live and writes a new file on save.
- Info → SOFn groups all SOF markers into subtabs; SOF0 remains editable and other SOF markers are shown as decoded read-only frame views.
- Info → DRI shows restart interval bytes, decoded effect, and editable payload views.
- Info → APPn groups all APP segments and auto-selects the first available tab.
- Info → DHT shows raw bytes plus table, counts, symbols, usage, canonical-code, and edit views per DHT segment.
- Info → APP1 shows EXIF layout, offsets, and decoded IFDs alongside hex view.
- Info → APP2 shows ICC header + tag table with structured decoding.
- Info → DQT shows raw bytes plus natural-grid, zigzag, stats, usage, heatmap, and edit views per DQT segment.
- Info → Hex provides a full-file hex view with segment coloring and a clickable legend.
- Structured editors for SOF0, DRI, DHT, and DQT refresh the byte-level preview live.
- SOF0, DQT, and DHT structured editors can highlight the corresponding serialized bytes in the left hex view when the caret is on a value.
- DQT and DHT structured editors keep the active editor stable while typing; the alternate raw/structured editor syncs when switching modes.
- Plugin panels are initialized after the Textual widget tree is ready; this fixed earlier startup crashes around dynamic `TabbedContent` population.
- Chart-producing analyses now force matplotlib onto the `Agg` backend so TUI-triggered runs do not hit Tk/thread crashes like `Tcl_AsyncDelete`.
- Exit the TUI with `q`. If the terminal is left in a bad state after an external crash, `reset` restores it.

## Current Status

- Core CLI/API, parser, mutation logic, reporting, and source-only analysis paths are working.
- The fullscreen TUI starts successfully and the plugin panel initialization path is fixed.
- The plugin system now supports stronger isolation via typed params, declared plugin needs, richer host-prepared analysis context, and a separate mutation-plugin family.
- The entropy-wave, sliding-wave, dc-heatmap, and ac-energy-heatmap plugins can be launched from the TUI using the metadata-driven plugin path.
- In the TUI, entropy wave and sliding wave are launched from the `Graphic Output` plugin tabs rather than dedicated fields in the `Outputs` panel.
- In the TUI, DC heatmap is launched from the `Graphic Output` plugin tab rather than a dedicated field in the `Outputs` panel.
- In the TUI, AC energy heatmap is launched from the `Graphic Output` plugin tab rather than a dedicated field in the `Outputs` panel.
- `--dc-heatmap` now dispatches internally through the `dc_heatmap` analysis plugin.
- `--ac-energy-heatmap` now dispatches internally through the `ac_energy_heatmap` analysis plugin.
- Current focused TUI/plugin test slices pass under `../env/bin/pytest`.

## What Still Needs Work

- The TUI is still the highest-maintenance part of the repo and remains the main refactor target.
- Large editor/workspace mixins still contain repeated save/preview/mode-switch mechanics.
- Plugin coverage is still narrow; the framework is now stronger, but only a small amount of real plugin functionality has been migrated onto it so far.
- More runtime-oriented TUI tests would still be valuable beyond the current fake-widget coverage.

### Generate mutations

```bash
./jpg_fault_tolerance.py gradient.jpg
```

### Choose mutation mode

```bash
./jpg_fault_tolerance.py gradient.jpg --mutate add1
./jpg_fault_tolerance.py gradient.jpg --mutate sub1
./jpg_fault_tolerance.py gradient.jpg --mutate flipall
./jpg_fault_tolerance.py gradient.jpg --mutate ff
./jpg_fault_tolerance.py gradient.jpg --mutate 00
./jpg_fault_tolerance.py gradient.jpg --mutate bitflip:0
./jpg_fault_tolerance.py gradient.jpg --mutate bitflip:0,1,3
./jpg_fault_tolerance.py gradient.jpg --mutate bitflip:msb
./jpg_fault_tolerance.py gradient.jpg --mutate bitflip:lsb
```

Overflow wrap for arithmetic mutations:

```bash
./jpg_fault_tolerance.py gradient.jpg --mutate add1 --overflow-wrap
./jpg_fault_tolerance.py gradient.jpg --mutate sub1 --overflow-wrap
```

### Choose mutation application strategy

Independent (current behavior, default):

```bash
./jpg_fault_tolerance.py gradient.jpg --mutation-apply independent
```

Cumulative (step N contains all previous mutations + one new random offset):

```bash
./jpg_fault_tolerance.py gradient.jpg --mutation-apply cumulative --sample 100 --seed 42
```

Set how many new bytes are added per cumulative image:

```bash
./jpg_fault_tolerance.py gradient.jpg --mutation-apply cumulative --sample 100 --step 2 --seed 42
```

Sequential (step N contains all previous mutations + the next sequential bytes):

```bash
./jpg_fault_tolerance.py gradient.jpg --mutation-apply sequential --sample 100 --step 2 --seed 42
```

### Repeat cumulative experiment sets

Generate multiple cumulative sets with different randomized offsets per set:

```bash
./jpg_fault_tolerance.py gradient.jpg --mutation-apply cumulative --sample 100 --repeats 10 --seed 42
```

`--repeat` is accepted as an alias of `--repeats`.

How set randomization works:

- `--seed` is the master seed
- The script deterministically derives one unique internal seed per set from the master seed
- Same CLI args produce identical set seeds and identical outputs
- Different sets get different offset sequences

### Monte Carlo sampling

Default is `100` with seed `3`:

```bash
./jpg_fault_tolerance.py gradient.jpg --mutate bitflip:0,1,3
```

Set explicit sample size / seed:

```bash
./jpg_fault_tolerance.py gradient.jpg --sample 500 --seed 42
```

Use all entropy offsets:

```bash
./jpg_fault_tolerance.py gradient.jpg --sample 0
```

`--sample` meaning depends on `--mutation-apply`:

- `independent`: number of random byte offsets to mutate (per offset, one or more files may be created depending on `--mutate`)
- `cumulative`: number of cumulative output steps/images
- `sequential`: number of sequential output steps/images

In cumulative mode, `sample * step` must not exceed the number of mutable entropy bytes.
In sequential mode, `sample * step` must not exceed the number of mutable entropy bytes.

`--step` meaning:

- `cumulative`: number of newly mutated entropy bytes added per image
- `sequential`: number of newly mutated entropy bytes added per image
- default: `1`
- total requested mutated offsets per set is `sample * step`
- example: `--sample 100 --step 2` gives 100 images, with cumulative mutations `2, 4, 6, ... 200`
- if `--sample 0`, the script uses the maximum full steps that fit: `floor(mutable_entropy_bytes / step)`

`--repeats` meaning:

- `cumulative`: number of repeated cumulative sets
- `sequential`: number of repeated sequential sets
- `independent`: must stay at default `1`

### Output directory

```bash
./jpg_fault_tolerance.py gradient.jpg -o mutations_out
```

### GIF creation

```bash
./jpg_fault_tolerance.py gradient.jpg --mutate bitflip:0 --sample 100 --gif out.gif
```

Randomize frame order:

```bash
./jpg_fault_tolerance.py gradient.jpg --gif out.gif --gif-shuffle
```

Adjust FPS and loop:

```bash
./jpg_fault_tolerance.py gradient.jpg --gif out.gif --gif-fps 5 --gif-loop 1
```

### SSIM chart generation

Generate 3 SSIM panels from cumulative outputs:

```bash
./jpg_fault_tolerance.py gradient.jpg --mutation-apply cumulative --sample 100 --repeats 10 --seed 42 --ssim-chart ssim_panels.png
```

By default, SSIM computation uses all detected CPU cores. Reduce workers if needed:

```bash
./jpg_fault_tolerance.py gradient.jpg --mutation-apply cumulative --sample 100 --repeats 10 --seed 42 --ssim-chart ssim_panels.png --jobs 4
```

Enable debug logging (prints core detection, selected jobs, timing, file matching, set/step counts, and decode stats to stderr):

```bash
./jpg_fault_tolerance.py gradient.jpg --mutation-apply cumulative --sample 100 --repeats 10 --seed 42 --ssim-chart ssim_panels.png --debug
```

Panels:

- A: all repetitions as separate SSIM-vs-step lines
- B: SSIM quantile lines (`median`, `q25/q75`, `q10/q90`)
- C: decode success rate vs step
- X-axis is affected bytes (`cumulative_step * --step`)

### Multi-metric chart generation

Generate one 3-panel chart per metric using a common prefix:

```bash
./jpg_fault_tolerance.py gradient.jpg --mutation-apply cumulative --sample 100 --step 2 --repeats 10 --seed 42 --metrics ssim,psnr,mse,mae --metrics-chart-prefix out_metrics
```

This writes:

- `out_metrics_ssim.png`
- `out_metrics_psnr.png`
- `out_metrics_mse.png`
- `out_metrics_mae.png`

Arguments:

- `--metrics`: comma-separated list of metrics. Supported: `ssim,psnr,mse,mae`
- `--metrics-chart-prefix`: output prefix for generated metric charts
- `--ssim-chart` still works and is equivalent to generating only SSIM

### Entropy stream wave charts

Write a 2-panel chart with byte-wave and bit-wave of the entropy stream:

```bash
./jpg_fault_tolerance.py gradient.jpg --wave-chart wave_panels.png
```

When only wave chart options are used (`--wave-chart` and/or `--sliding-wave-chart`), the script analyzes the original JPEG entropy stream directly and skips mutation generation.

### DCT block heatmaps (8x8)

Write DC coefficient heatmap:

```bash
./jpg_fault_tolerance.py gradient.jpg --dc-heatmap dc_heatmap.png
```

Write AC energy heatmap:

```bash
./jpg_fault_tolerance.py gradient.jpg --ac-energy-heatmap ac_energy_heatmap.png
```

Use both together:

```bash
./jpg_fault_tolerance.py gradient.jpg --dc-heatmap dc_heatmap.png --ac-energy-heatmap ac_energy_heatmap.png
```

These are computed from decoded image luminance using 8x8 block DCT and, when used without mutation-dependent outputs, they run in source-only mode (no mutations generated).

Write a 3-panel sliding chart (rolling mean, variance, entropy):

```bash
./jpg_fault_tolerance.py gradient.jpg --sliding-wave-chart sliding_wave.png
```

Change sliding window size (default is `256`):

```bash
./jpg_fault_tolerance.py gradient.jpg --sliding-wave-chart sliding_wave.png --wave-window 512
```

## Tests

Run all tests:

```bash
python3 -m pytest -q
```

## Output File Naming

Independent mode file naming:

```
<basename>_off_<OFFSET>_orig_<ORIG>_new_<NEW>_mut_<TAG>.jpg
```

Example:

```
gradient_off_000012CD_orig_F6_new_F7_mut_add1.jpg
```

For `bitflip`, the tag shows which bit was toggled:

```
..._mut_bit3.jpg
```

Cumulative mode file naming:

```
<basename>_cum_<STEP>_step_<STEP_SIZE>_off_<LAST_OFFSET>_orig_<LAST_ORIG>_new_<LAST_NEW>_mut_<TAG>.jpg
```

Example:

```
gradient_cum_000010_step_001_off_000012CD_orig_F6_new_F7_mut_add1.jpg
```

In cumulative mode with `bitflip:0,1,3`, all listed bits are applied to each newly selected byte in that step:

```
..._mut_bit0-1-3.jpg
```

When `--repeats > 1` (cumulative mode), files are organized in subdirectories:

```
<output_dir>/set_0001/
<output_dir>/set_0002/
...
```

And filenames include set id:

```
<basename>_set_<SET>_cum_<STEP>_step_<STEP_SIZE>_off_<LAST_OFFSET>_orig_<LAST_ORIG>_new_<LAST_NEW>_mut_<TAG>.jpg
```

Sequential mode uses the same naming pattern as cumulative mode.

## Explicit Generation Examples

Example 1: cumulative steps only

```bash
./jpg_fault_tolerance.py gradient.jpg --mutation-apply cumulative --sample 3 --seed 7 -o out_a
```

Generated:

- `out_a/gradient_cum_000001_...jpg`
- `out_a/gradient_cum_000002_...jpg`
- `out_a/gradient_cum_000003_...jpg`

Example 2: repeated cumulative sets

```bash
./jpg_fault_tolerance.py gradient.jpg --mutation-apply cumulative --sample 3 --repeats 2 --seed 7 -o out_b
```

Generated:

- `out_b/set_0001/gradient_set_0001_cum_000001_...jpg`
- `out_b/set_0001/gradient_set_0001_cum_000002_...jpg`
- `out_b/set_0001/gradient_set_0001_cum_000003_...jpg`
- `out_b/set_0002/gradient_set_0002_cum_000001_...jpg`
- `out_b/set_0002/gradient_set_0002_cum_000002_...jpg`
- `out_b/set_0002/gradient_set_0002_cum_000003_...jpg`

Example 3: repeated cumulative multi-bit flips

```bash
./jpg_fault_tolerance.py gradient.jpg --mutation-apply cumulative --mutate bitflip:0,1,3 --sample 2 --repeats 2 --seed 11 -o out_c
```

Generated files use `mut_bit0-1-3` tags, one cumulative step per file in each set.

Example 3b: repeated cumulative with 2-byte increments

```bash
./jpg_fault_tolerance.py gradient.jpg --mutation-apply cumulative --sample 3 --step 2 --repeats 2 --seed 11 -o out_c_step2
```

Generated per set:

- image 1 has 2 bytes changed
- image 2 has 4 bytes changed
- image 3 has 6 bytes changed

Example 4: repeated cumulative sets + SSIM panels

```bash
./jpg_fault_tolerance.py gradient.jpg --mutation-apply cumulative --sample 100 --repeats 10 --seed 42 --ssim-chart out_ssim.png
```

Generated:

- cumulative mutation files under `mutations/set_0001...set_0010` (default output dir)
- one chart image `out_ssim.png` with panels A/B/C

Example 5: same as above, limit SSIM workers to 4

```bash
./jpg_fault_tolerance.py gradient.jpg --mutation-apply cumulative --sample 100 --repeats 10 --seed 42 --ssim-chart out_ssim.png --jobs 4
```

Example 6: generate SSIM + PSNR + MSE + MAE charts with one command

```bash
./jpg_fault_tolerance.py gradient.jpg --mutation-apply cumulative --sample 100 --step 2 --repeats 10 --seed 42 --metrics ssim,psnr,mse,mae --metrics-chart-prefix out_metrics --jobs 4
```

Example 7: sequential mutations with overflow wrap

```bash
./jpg_fault_tolerance.py gradient.jpg --mutation-apply sequential --mutate add1 --overflow-wrap --sample 50 --step 2 --seed 7 -o out_seq
```

## How Segment Lengths Are Determined

All JPEG segments except SOI and EOI have this structure:

```
FF <marker>  <length_hi> <length_lo>  <payload...>
```

- The length field is **big-endian**
- It **includes the length bytes themselves**

So:

```
payload_length = length - 2
segment_total_length = 2 (marker bytes) + length
```

SOI and EOI are always exactly 2 bytes and contain no length field.

## Notes On SOS And Entropy Data

- SOS (Start Of Scan) is **a small header**, not the data itself
- The compressed image data begins **immediately after SOS header**
- The stream ends at the next marker (another SOS or EOI)
- A JPEG can have **one or many SOS segments** (e.g., progressive JPEGs)

## Notes On APP1

APP1 typically contains **EXIF metadata**. This can be large (often thousands of bytes), which is why APP1 segments are often much bigger than APP0. The TUI decodes EXIF headers, TIFF layout, IFD0/IFD1, and ExifIFD offsets, and renders annotated hex + table views.

## Notes On APP2

APP2 often contains an **ICC profile** (`ICC_PROFILE`). The TUI decodes the ICC header and tag table and can edit common tag payloads with live hex updates.

## Known Limitations

- The script does not decode every segment type, only the most common ones.
- Mutations are limited to entropy-coded data; headers are not mutated.
- GIF creation loads all mutated images in memory.

## Common Experiments

- Compare `add1` vs `bitflip:0` to see how arithmetic changes differ from single-bit flips.
- Use `bitflip:msb` to study high-order bit sensitivity.
- Run multiple seeds and compare the distribution of visible corruption.

## Roadmap Ideas

- Add full Huffman table decoding (code lengths and values)
- Add stratified sampling across multiple scans
- Export a CSV index of all mutations

## Session Handoff

- The analysis-plugin migration for wave/DC/AC outputs is substantially done.
- In the TUI, those analyses are now launched from `Graphic Output` plugin tabs instead of the old dedicated Outputs-panel controls.
- The TUI Mutation page now combines mutation, strategy, and run controls on one page and includes a help column plus equivalent CLI command.
- Current mutation semantics to preserve:
  - `independent`: random offsets, each file starts from the original
  - `cumulative`: random mutable offsets accumulated across files
  - `sequential`: contiguous mutable offsets accumulated across files
- Important caveat: current `sequential` behavior is contiguous in mutable-offset order, not guaranteed contiguous raw file bytes.
- Another caveat: sequential outputs still use `cum_...` in filenames because they reuse the cumulative naming helper. That naming should be cleaned up if the mutation-output UX is revisited.

## License

This project is licensed under the GNU General Public License v3.0. You are free to share, modify, and distribute this software, provided that any derivative works are also licensed under the GPL and include the original source code. 

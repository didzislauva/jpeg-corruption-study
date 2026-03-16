# JPEG Fault Tolerance Investigation

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
- `jpeg_fault/core/debug.py` — Debug logging helper
- `gradient.jpg` — Example input image
- `mutations/` — Default output directory for mutated files
- `README.md` — This documentation

## Requirements

- Python 3.8+
- Pillow (`PIL`) only if you use `--gif`
- `matplotlib`, `numpy`, and `scikit-image` only if you use `--ssim-chart`
- `matplotlib` and `numpy` if you use `--wave-chart` or `--sliding-wave-chart`
- `Pillow`, `matplotlib`, and `numpy` if you use `--dc-heatmap` or `--ac-energy-heatmap`
- `textual` if you use the fullscreen TUI (`--tui` / `--gui`)
- `pytest` only if you run tests

Install Pillow if needed:

```bash
python3 -m pip install pillow
```

Install SSIM chart dependencies if needed:

```bash
python3 -m pip install matplotlib numpy scikit-image
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
- SOF0 tab with frame-header workspace: bytes/info on the left, frame/components/tables/edit views on the right
- DRI tab with restart-interval workspace: bytes/info on the left, summary/effect/edit views on the right
- APPn tab with per-segment subtabs (APP1/APP2 decoded, others shown read-only)
- DHT tab with per-segment workspaces: bytes/info on the left, table/counts/symbols/usage/codes/edit views on the right
- APP1 EXIF decoder with annotated hex/raw/table views and editable headers/IFDs
- APP2 ICC profile decoder with editable header/tags and live hex updates
- DQT tab with per-segment workspaces: bytes/info on the left, grid/zigzag/stats/usage/heatmap/edit views on the right
- Tools tab with a custom APPn writer

## TUI Notes

- Info → Segments includes health checks with OK/WARN/FAIL and reasons.
- Info → APP0 shows decoded fields with color-matched hex preview.
- APP0 editor updates the preview live and writes a new file on save.
- Info → SOF0 shows frame geometry, component sampling/table mapping, and editable frame-header payload views.
- Info → DRI shows restart interval bytes, decoded effect, and editable payload views.
- Info → APPn groups all APP segments and auto-selects the first available tab.
- Info → DHT shows raw bytes plus table, counts, symbols, usage, canonical-code, and edit views per DHT segment.
- Info → APP1 shows EXIF layout, offsets, and decoded IFDs alongside hex view.
- Info → APP2 shows ICC header + tag table with structured decoding.
- Info → DQT shows raw bytes plus natural-grid, zigzag, stats, usage, heatmap, and edit views per DQT segment.
- Info → Hex provides a full-file hex view with segment coloring and a clickable legend.
- Structured editors for SOF0, DRI, DHT, and DQT refresh the byte-level preview live.
- DQT and DHT structured editors keep the active editor stable while typing; the alternate raw/structured editor syncs when switching modes.

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

## License

This project is licensed under the GNU General Public License v3.0. You are free to share, modify, and distribute this software, provided that any derivative works are also licensed under the GPL and include the original source code. 

# JPEG Fault Tolerance Investigation

This project explores JPEG fault tolerance by creating controlled mutations inside the **entropy-coded data stream** (the bytes after each SOS header), while leaving JPEG headers and metadata intact. It also provides a rich, colorized report of JPEG segments and their structure.

The focus is to understand how small perturbations (byte arithmetic or bit flips) affect JPEG decoding and visual output.

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
   - Supports bit-flip modes (`bitflip:0,1,3`, `bitflip:msb`, `bitflip:lsb`)
   - Supports full byte inversion (`flipall`)
   - Outputs one mutated JPEG file per change

4. **Monte Carlo sampling**
   - Limits the number of mutated offsets to avoid huge output sets
   - Random sampling with reproducible seed

5. **Optional GIF generation**
   - Builds a GIF from the generated mutated images
   - Supports shuffling frame order for visual randomness

## Files

- `jpg_fault_tolerance.py` — Main script
- `gradient.jpg` — Example input image
- `mutations/` — Default output directory for mutated files
- `README.md` — This documentation

## Requirements

- Python 3.8+
- Pillow (`PIL`) for GIF creation

Install Pillow if needed:

```bash
python3 -m pip install pillow
```

## Usage

### Basic report only

```bash
./jpg_fault_tolerance.py gradient.jpg --report-only
```

### Generate mutations

```bash
./jpg_fault_tolerance.py gradient.jpg
```

### Choose mutation mode

```bash
./jpg_fault_tolerance.py gradient.jpg --mutate add1
./jpg_fault_tolerance.py gradient.jpg --mutate sub1
./jpg_fault_tolerance.py gradient.jpg --mutate flipall
./jpg_fault_tolerance.py gradient.jpg --mutate bitflip:0
./jpg_fault_tolerance.py gradient.jpg --mutate bitflip:0,1,3
./jpg_fault_tolerance.py gradient.jpg --mutate bitflip:msb
```

### Monte Carlo sampling

Default is `100` offsets with seed `3`:

```bash
./jpg_fault_tolerance.py gradient.jpg --mutate bitflip:0,1,3
```

Set explicit sample size / seed:

```bash
./jpg_fault_tolerance.py gradient.jpg --sample 500 --seed 42
```

Disable sampling (mutate all offsets):

```bash
./jpg_fault_tolerance.py gradient.jpg --sample 0
```

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

## Output File Naming

Each mutated file encodes the offset and mutation:

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

APP1 typically contains **EXIF metadata**. This can be large (often thousands of bytes), which is why APP1 segments are often much bigger than APP0.

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
- Decode and summarize EXIF tags from APP1
- Add stratified sampling across multiple scans
- Export a CSV index of all mutations

## License

No license specified. Add one if you plan to distribute this project.

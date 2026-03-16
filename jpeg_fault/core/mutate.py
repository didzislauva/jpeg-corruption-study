"""
Mutation selection, application, and output file generation.

Key concepts:
- Independent mode: each output mutates one offset from the original.
- Cumulative mode: each output accumulates all prior mutations plus new ones.
- Sequential mode: like cumulative, but offsets are contiguous in the mutable stream.
"""

import os
import random
from bisect import bisect_right
from glob import glob
from typing import List, Optional, Tuple

from .debug import debug_log
from .models import EntropyRange


def parse_bits_list(spec: str) -> List[int]:
    """
    Parse a bit list spec for bitflip modes.

    Supports:
    - "msb" -> [7]
    - "lsb" -> [0]
    - "0,1,3" -> [0, 1, 3] (deduped and sorted)
    """
    if spec.lower() == "msb":
        return [7]
    if spec.lower() == "lsb":
        return [0]
    bits: List[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise ValueError(f"Invalid bit index: {part}")
        bit = int(part)
        if bit < 0 or bit > 7:
            raise ValueError(f"Bit index out of range (0-7): {bit}")
        bits.append(bit)
    return sorted(set(bits))


def parse_mutation_mode(spec: str) -> Tuple[str, Optional[List[int]]]:
    """
    Parse a mutation mode specification.

    Returns a tuple of (mode, bits) where bits is only set for bitflip modes.
    """
    if spec in {"add1", "sub1", "flipall", "ff", "00"}:
        return spec, None
    if spec.startswith("bitflip:"):
        bits = parse_bits_list(spec.split(":", 1)[1])
        if not bits:
            raise ValueError("bitflip requires at least one bit index")
        return "bitflip", bits
    raise ValueError("Invalid mutate mode. Use add1, sub1, flipall, ff, 00, or bitflip:<bits>")


def mutate_byte(orig: int, mode: str, bits: Optional[List[int]], overflow_wrap: bool) -> List[Tuple[int, str]]:
    """
    Apply mutation in independent mode.

    Returns a list of (new_value, tag) pairs because bitflip can fan out
    into multiple outputs per original byte.
    """
    if mode == "add1":
        if orig == 0xFF:
            return [(0x00, "add1-wrap")] if overflow_wrap else []
        return [(orig + 1, "add1")]
    if mode == "sub1":
        if orig == 0x00:
            return [(0xFF, "sub1-wrap")] if overflow_wrap else []
        return [(orig - 1, "sub1")]
    if mode == "flipall":
        return [(orig ^ 0xFF, "flipall")]
    if mode == "ff":
        if orig == 0xFF:
            return []
        return [(0xFF, "ff")]
    if mode == "00":
        if orig == 0x00:
            return []
        return [(0x00, "00")]
    if mode == "bitflip" and bits is not None:
        return [(orig ^ (1 << b), f"bit{b}") for b in bits]
    return []


def mutate_byte_cumulative(
    orig: int,
    mode: str,
    bits: Optional[List[int]],
    overflow_wrap: bool,
) -> Optional[Tuple[int, str]]:
    """
    Apply mutation in cumulative/sequential mode.

    Returns a single (new_value, tag) or None if the byte is not mutable.
    """
    if mode == "add1":
        if orig == 0xFF:
            return (0x00, "add1-wrap") if overflow_wrap else None
        return orig + 1, "add1"
    if mode == "sub1":
        if orig == 0x00:
            return (0xFF, "sub1-wrap") if overflow_wrap else None
        return orig - 1, "sub1"
    if mode == "flipall":
        return orig ^ 0xFF, "flipall"
    if mode == "ff":
        if orig == 0xFF:
            return None
        return 0xFF, "ff"
    if mode == "00":
        if orig == 0x00:
            return None
        return 0x00, "00"
    if mode == "bitflip" and bits is not None:
        mask = 0
        for bit in bits:
            mask ^= (1 << bit)
        return orig ^ mask, "bit" + "-".join(str(bit) for bit in bits)
    return None


def total_entropy_length(ranges: List[EntropyRange]) -> int:
    """
    Total length of all entropy-coded ranges combined.
    """
    return sum(r.end - r.start for r in ranges)


def build_cumulative(ranges: List[EntropyRange]) -> List[int]:
    """
    Build cumulative end positions for logical entropy indexing.
    """
    ends: List[int] = []
    total = 0
    for r in ranges:
        total += r.end - r.start
        ends.append(total)
    return ends


def index_to_offset(idx: int, ranges: List[EntropyRange], ends: List[int]) -> int:
    """
    Map a logical entropy index to a concrete file offset.
    """
    pos = bisect_right(ends, idx)
    prev_end = 0 if pos == 0 else ends[pos - 1]
    return ranges[pos].start + (idx - prev_end)


def select_offsets_from_ranges(ranges: List[EntropyRange], sample_n: int, seed: int) -> List[int]:
    """
    Select random offsets for independent mode.
    """
    total_len = total_entropy_length(ranges)
    if total_len == 0:
        return []
    if sample_n <= 0 or sample_n >= total_len:
        return [i for r in ranges for i in range(r.start, r.end)]
    rng = random.Random(seed)
    ends = build_cumulative(ranges)
    picks = rng.sample(range(total_len), sample_n)
    return [index_to_offset(i, ranges, ends) for i in picks]


def select_offsets_cumulative(ranges: List[EntropyRange], sample_n: int, seed: int) -> List[int]:
    """
    Select random logical offsets for cumulative mode.
    """
    total_len = total_entropy_length(ranges)
    if total_len == 0:
        return []
    target_n = total_len if sample_n <= 0 else sample_n
    if target_n > total_len:
        raise ValueError(
            f"Cumulative mode requested {target_n} steps, but entropy stream has only {total_len} bytes."
        )
    rng = random.Random(seed)
    ends = build_cumulative(ranges)
    picks = rng.sample(range(total_len), target_n)
    return [index_to_offset(i, ranges, ends) for i in picks]


def offset_mutable(byte_val: int, mode: str, overflow_wrap: bool) -> bool:
    """
    Determine whether a byte is mutable for a given mode.
    """
    if mode == "add1":
        return overflow_wrap or byte_val != 0xFF
    if mode == "sub1":
        return overflow_wrap or byte_val != 0x00
    if mode == "ff":
        return byte_val != 0xFF
    if mode == "00":
        return byte_val != 0x00
    return True


def mutable_offsets_in_ranges(data: bytes, ranges: List[EntropyRange], mode: str, overflow_wrap: bool) -> List[int]:
    """
    Collect mutable offsets across all entropy ranges, preserving order.
    """
    mutable: List[int] = []
    for r in ranges:
        for off in range(r.start, r.end):
            if offset_mutable(data[off], mode, overflow_wrap):
                mutable.append(off)
    return mutable


def split_offsets_by_step(offsets: List[int], step_size: int) -> List[List[int]]:
    """
    Group a flat offset list into step-sized chunks.
    """
    return [offsets[i:i + step_size] for i in range(0, len(offsets), step_size)]


def select_cumulative_step_offsets(
    data: bytes,
    ranges: List[EntropyRange],
    sample_n: int,
    seed: int,
    mode: str,
    step_size: int,
    overflow_wrap: bool,
) -> List[List[int]]:
    """
    Select random mutable offsets and group them by step size for cumulative mode.
    """
    if step_size < 1:
        raise ValueError(f"--step must be >= 1, got {step_size}")
    mutable_offsets = mutable_offsets_in_ranges(data, ranges, mode, overflow_wrap)
    mutable_total = len(mutable_offsets)
    if mutable_total == 0:
        return []
    target_steps = (mutable_total // step_size) if sample_n <= 0 else sample_n
    if target_steps < 0:
        raise ValueError(f"--sample must be >= 0, got {sample_n}")
    required_offsets = target_steps * step_size
    if required_offsets > mutable_total:
        raise ValueError(
            (
                f"Cumulative mode requested {target_steps} steps x {step_size} bytes "
                f"({required_offsets} total), but only {mutable_total} mutable entropy bytes are available."
            )
        )
    if required_offsets == 0:
        return []
    rng = random.Random(seed)
    picks = rng.sample(mutable_offsets, required_offsets)
    return split_offsets_by_step(picks, step_size)


def select_sequential_step_offsets(
    data: bytes,
    ranges: List[EntropyRange],
    sample_n: int,
    seed: int,
    mode: str,
    step_size: int,
    overflow_wrap: bool,
) -> List[List[int]]:
    """
    Select contiguous mutable offsets for sequential mode.

    A start index is chosen by seed, then `sample_n * step_size` offsets are
    taken sequentially without wraparound.
    """
    if step_size < 1:
        raise ValueError(f"--step must be >= 1, got {step_size}")
    mutable_offsets = mutable_offsets_in_ranges(data, ranges, mode, overflow_wrap)
    mutable_total = len(mutable_offsets)
    if mutable_total == 0:
        return []
    target_steps = (mutable_total // step_size) if sample_n <= 0 else sample_n
    if target_steps < 0:
        raise ValueError(f"--sample must be >= 0, got {sample_n}")
    required_offsets = target_steps * step_size
    if required_offsets > mutable_total:
        raise ValueError(
            (
                f"Sequential mode requested {target_steps} steps x {step_size} bytes "
                f"({required_offsets} total), but only {mutable_total} mutable entropy bytes are available."
            )
        )
    if required_offsets == 0:
        return []
    max_start = mutable_total - required_offsets
    rng = random.Random(seed)
    start_idx = rng.randrange(max_start + 1)
    seq = mutable_offsets[start_idx:start_idx + required_offsets]
    return split_offsets_by_step(seq, step_size)


def derive_set_seeds(master_seed: int, repeats: int) -> List[int]:
    """
    Derive deterministic per-set seeds from a master seed.
    """
    if repeats < 1:
        raise ValueError(f"--repeats must be >= 1, got {repeats}")
    if repeats == 1:
        return [master_seed]
    max_unique = 2 ** 32
    if repeats > max_unique:
        raise ValueError(f"--repeats must be <= {max_unique}, got {repeats}")
    rng = random.Random(master_seed)
    return rng.sample(range(max_unique), repeats)


def cumulative_output_dir(output_dir: str, set_index: int, repeats: int) -> str:
    """
    Resolve output directory for a given set, optionally nested under set_XXXX.
    """
    if repeats == 1:
        return output_dir
    return os.path.join(output_dir, f"set_{set_index:04d}")


def cumulative_out_name(
    base_name: str,
    step_index: int,
    offset: int,
    orig: int,
    new: int,
    tag: str,
    set_index: int,
    repeats: int,
    step_size: int,
) -> str:
    """
    Build the output filename for cumulative or sequential outputs.
    """
    prefix = f"{base_name}_cum_{step_index:06d}"
    if repeats > 1:
        prefix = f"{base_name}_set_{set_index:04d}_cum_{step_index:06d}"
    return (
        f"{prefix}_step_{step_size:03d}_off_{offset:08X}_orig_{orig:02X}_new_{new:02X}_mut_{tag}.jpg"
    )


def write_cumulative_set(
    data: bytes,
    offsets_by_step: List[List[int]],
    output_dir: str,
    base_name: str,
    mode: str,
    bits: Optional[List[int]],
    overflow_wrap: bool,
    set_index: int,
    repeats: int,
    step_size: int,
) -> int:
    """
    Apply a list of per-step offsets, writing one cumulative image per step.
    """
    os.makedirs(output_dir, exist_ok=True)
    total = 0
    data_arr = bytearray(data)
    for step_index, step_offsets in enumerate(offsets_by_step, start=1):
        last_offset = 0
        last_orig = 0
        last_new = 0
        last_tag = mode
        for offset in step_offsets:
            orig = data_arr[offset]
            change = mutate_byte_cumulative(orig, mode, bits, overflow_wrap)
            if change is None:
                continue
            new, tag = change
            data_arr[offset] = new
            last_offset = offset
            last_orig = orig
            last_new = new
            last_tag = tag
        out_name = cumulative_out_name(
            base_name, step_index, last_offset, last_orig, last_new, last_tag, set_index, repeats, step_size
        )
        out_path = os.path.join(output_dir, out_name)
        with open(out_path, "wb") as f:
            f.write(data_arr)
        total += 1
    return total


def write_mutations_independent(
    data: bytes,
    entropy_ranges: List[EntropyRange],
    output_dir: str,
    base_name: str,
    mode: str,
    bits: Optional[List[int]],
    overflow_wrap: bool,
    sample_n: int,
    seed: int,
    debug: bool,
) -> int:
    """
    Generate independent mutation files, one per selected offset.
    """
    os.makedirs(output_dir, exist_ok=True)
    total = 0
    data_arr = bytearray(data)

    offsets = select_offsets_from_ranges(entropy_ranges, sample_n, seed)
    debug_log(debug, f"Independent mode offsets selected: {len(offsets)}")
    for offset in offsets:
        orig = data[offset]
        for new, tag in mutate_byte(orig, mode, bits, overflow_wrap):
            data_arr[offset] = new
            out_name = f"{base_name}_off_{offset:08X}_orig_{orig:02X}_new_{new:02X}_mut_{tag}.jpg"
            out_path = os.path.join(output_dir, out_name)
            with open(out_path, "wb") as f:
                f.write(data_arr)
            total += 1
        data_arr[offset] = orig
    return total


def write_mutations_cumulative(
    data: bytes,
    entropy_ranges: List[EntropyRange],
    output_dir: str,
    base_name: str,
    mode: str,
    bits: Optional[List[int]],
    overflow_wrap: bool,
    sample_n: int,
    seed: int,
    repeats: int,
    step_size: int,
    debug: bool,
) -> int:
    """
    Generate cumulative mutation sets using randomly sampled mutable offsets.
    """
    total = 0
    set_seeds = derive_set_seeds(seed, repeats)
    debug_log(debug, f"Cumulative mode repeats: {repeats}, derived set seeds: {set_seeds[:8]}")
    for set_index, set_seed in enumerate(set_seeds, start=1):
        set_dir = cumulative_output_dir(output_dir, set_index, repeats)
        offsets_by_step = select_cumulative_step_offsets(
            data, entropy_ranges, sample_n, set_seed, mode, step_size, overflow_wrap
        )
        debug_log(
            debug,
            (
                f"Set {set_index:04d}: seed={set_seed}, steps={len(offsets_by_step)}, "
                f"step_size={step_size}, output={set_dir}"
            ),
        )
        total += write_cumulative_set(
            data,
            offsets_by_step,
            set_dir,
            base_name,
            mode,
            bits,
            overflow_wrap,
            set_index,
            repeats,
            step_size,
        )
    return total


def write_mutations_sequential(
    data: bytes,
    entropy_ranges: List[EntropyRange],
    output_dir: str,
    base_name: str,
    mode: str,
    bits: Optional[List[int]],
    overflow_wrap: bool,
    sample_n: int,
    seed: int,
    repeats: int,
    step_size: int,
    debug: bool,
) -> int:
    """
    Generate sequential mutation sets using contiguous mutable offsets.
    """
    total = 0
    set_seeds = derive_set_seeds(seed, repeats)
    debug_log(debug, f"Sequential mode repeats: {repeats}, derived set seeds: {set_seeds[:8]}")
    for set_index, set_seed in enumerate(set_seeds, start=1):
        set_dir = cumulative_output_dir(output_dir, set_index, repeats)
        offsets_by_step = select_sequential_step_offsets(
            data, entropy_ranges, sample_n, set_seed, mode, step_size, overflow_wrap
        )
        debug_log(
            debug,
            (
                f"Set {set_index:04d}: seed={set_seed}, steps={len(offsets_by_step)}, "
                f"step_size={step_size}, output={set_dir}"
            ),
        )
        total += write_cumulative_set(
            data,
            offsets_by_step,
            set_dir,
            base_name,
            mode,
            bits,
            overflow_wrap,
            set_index,
            repeats,
            step_size,
        )
    return total


def write_mutations(
    data: bytes,
    entropy_ranges: List[EntropyRange],
    output_dir: str,
    base_name: str,
    mode: str,
    bits: Optional[List[int]],
    overflow_wrap: bool,
    sample_n: int,
    seed: int,
    mutation_apply: str,
    repeats: int,
    step_size: int,
    debug: bool,
) -> int:
    """
    Dispatch mutation generation based on strategy name.
    """
    return _dispatch_mutations(
        data,
        entropy_ranges,
        output_dir,
        base_name,
        mode,
        bits,
        overflow_wrap,
        sample_n,
        seed,
        mutation_apply,
        repeats,
        step_size,
        debug,
    )


def _dispatch_mutations(
    data: bytes,
    entropy_ranges: List[EntropyRange],
    output_dir: str,
    base_name: str,
    mode: str,
    bits: Optional[List[int]],
    overflow_wrap: bool,
    sample_n: int,
    seed: int,
    mutation_apply: str,
    repeats: int,
    step_size: int,
    debug: bool,
) -> int:
    if mutation_apply == "independent":
        return write_mutations_independent(
            data, entropy_ranges, output_dir, base_name, mode, bits, overflow_wrap, sample_n, seed, debug
        )
    if mutation_apply == "cumulative":
        return write_mutations_cumulative(
            data,
            entropy_ranges,
            output_dir,
            base_name,
            mode,
            bits,
            overflow_wrap,
            sample_n,
            seed,
            repeats,
            step_size,
            debug,
        )
    if mutation_apply == "sequential":
        return write_mutations_sequential(
            data,
            entropy_ranges,
            output_dir,
            base_name,
            mode,
            bits,
            overflow_wrap,
            sample_n,
            seed,
            repeats,
            step_size,
            debug,
        )
    raise ValueError(f"Unsupported mutation apply mode: {mutation_apply}")


def list_mutation_files(output_dir: str, base_name: str) -> List[str]:
    """
    List all mutation output files matching the naming pattern.
    """
    pattern = os.path.join(output_dir, "**", f"{base_name}_*_mut_*.jpg")
    return sorted(glob(pattern, recursive=True))

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .analysis_types import PluginParamSpec
from .mutate import cumulative_out_name, cumulative_output_dir, derive_set_seeds, select_cumulative_step_offsets, select_offsets_from_ranges, select_sequential_step_offsets
from .mutation_types import MutationContext, MutationPlugin, MutationResult


@dataclass(frozen=True)
class FixedByteMutationPlugin(MutationPlugin):
    id: str
    label: str
    target_byte: int
    tag: str
    supported_formats: set[str] = frozenset({"jpeg"})
    needs: frozenset[str] = frozenset({"source_bytes", "entropy_ranges"})
    params_spec: tuple[PluginParamSpec, ...] = (
        PluginParamSpec(name="sample", label="Sample size", type="int", default=100, help="Number of entropy-byte offsets to sample. Use 0 for all offsets."),
        PluginParamSpec(name="seed", label="Seed", type="int", default=3, help="Random seed used when sampling entropy-byte offsets."),
    )

    def run(self, input_path: str, context: MutationContext) -> MutationResult:
        data = context.source_bytes or Path(input_path).read_bytes()
        entropy_ranges = context.entropy_ranges or []
        params = context.params or {}
        sample_n = int(params.get("sample", 100))
        seed = int(params.get("seed", 3))
        output_dir = Path(context.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        apply_mode = context.mutation_apply or "independent"
        repeats = int(context.repeats or 1)
        step_size = int(context.step or 1)
        outputs: list[str] = []
        base_name = Path(input_path).stem
        if apply_mode == "independent":
            for offset in select_offsets_from_ranges(entropy_ranges, sample_n, seed):
                orig = data[offset]
                if orig == self.target_byte:
                    continue
                mutated = bytearray(data)
                mutated[offset] = self.target_byte
                out_path = output_dir / f"{base_name}_off_{offset:08X}_orig_{orig:02X}_new_{self.target_byte:02X}_mut_{self.tag}.jpg"
                out_path.write_bytes(mutated)
                outputs.append(str(out_path))
        else:
            outputs.extend(self._run_staged_sets(data, entropy_ranges, output_dir, base_name, sample_n, seed, repeats, step_size, apply_mode))
        return MutationResult(
            self.id,
            outputs,
            {
                "target_byte": f"{self.target_byte:02X}",
                "sample": sample_n,
                "seed": seed,
                "mutation_apply": apply_mode,
                "repeats": repeats,
                "step": step_size,
            },
        )

    def _run_staged_sets(
        self,
        data: bytes,
        entropy_ranges,
        output_dir: Path,
        base_name: str,
        sample_n: int,
        seed: int,
        repeats: int,
        step_size: int,
        apply_mode: str,
    ) -> list[str]:
        outputs: list[str] = []
        set_seeds = derive_set_seeds(seed, repeats)
        for set_index, set_seed in enumerate(set_seeds, start=1):
            set_dir = Path(cumulative_output_dir(str(output_dir), set_index, repeats))
            set_dir.mkdir(parents=True, exist_ok=True)
            if apply_mode == "cumulative":
                offsets_by_step = select_cumulative_step_offsets(
                    data, entropy_ranges, sample_n, set_seed, "ff", step_size, True
                )
            else:
                offsets_by_step = select_sequential_step_offsets(
                    data, entropy_ranges, sample_n, set_seed, "ff", step_size, True
                )
            data_arr = bytearray(data)
            for step_index, step_offsets in enumerate(offsets_by_step, start=1):
                last_offset = 0
                last_orig = 0
                for offset in step_offsets:
                    orig = data_arr[offset]
                    if orig == self.target_byte:
                        continue
                    data_arr[offset] = self.target_byte
                    last_offset = offset
                    last_orig = orig
                out_name = cumulative_out_name(
                    base_name,
                    step_index,
                    last_offset,
                    last_orig,
                    self.target_byte,
                    self.tag,
                    set_index,
                    repeats,
                    step_size,
                )
                out_path = set_dir / out_name
                out_path.write_bytes(data_arr)
                outputs.append(str(out_path))
        return outputs

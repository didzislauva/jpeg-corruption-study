from __future__ import annotations

from pathlib import Path

from jpeg_fault.core import api
from jpeg_fault.core.mutation_registry import clear_registry_for_tests, get_plugin, load_plugins
from jpeg_fault.core.plugin_contexts import build_mutation_context


def _changed_offsets(before: bytes, after: bytes) -> list[int]:
    return [idx for idx, (lhs, rhs) in enumerate(zip(before, after)) if lhs != rhs]


def test_builtin_mutation_plugins_load() -> None:
    clear_registry_for_tests()

    load_plugins(force=True)

    plugin_55 = get_plugin("55")
    plugin_aa = get_plugin("aa")
    plugin_insert_appn = get_plugin("insert_appn")
    assert plugin_55 is not None
    assert plugin_aa is not None
    assert plugin_insert_appn is not None
    assert plugin_55.label == "55 Mutation"
    assert plugin_aa.label == "AA Mutation"
    assert plugin_insert_appn.label == "Insert APPn"


def test_builtin_55_mutation_plugin_writes_sampled_outputs(tmp_path: Path, tiny_jpeg_path: Path) -> None:
    clear_registry_for_tests()
    load_plugins(force=True)
    plugin = get_plugin("55")
    assert plugin is not None
    data = tiny_jpeg_path.read_bytes()
    segments, entropy_ranges = api.parse_jpeg(data)  # type: ignore[attr-defined]
    context = build_mutation_context(
        plugin=plugin,
        input_path=str(tiny_jpeg_path),
        fmt="jpeg",
        output_dir=str(tmp_path),
        debug=False,
        params={"sample": 2, "seed": 1},
        data=data,
        segments=segments,
        entropy_ranges=entropy_ranges,
    )

    result = plugin.run(str(tiny_jpeg_path), context)

    assert len(result.outputs) == 2
    for out_path_str in result.outputs:
        out_path = Path(out_path_str)
        changed = _changed_offsets(data, out_path.read_bytes())
        assert len(changed) == 1
        assert out_path.read_bytes()[changed[0]] == 0x55


def test_builtin_aa_mutation_plugin_respects_all_offsets_mode(tmp_path: Path, tiny_jpeg_path: Path) -> None:
    clear_registry_for_tests()
    load_plugins(force=True)
    plugin = get_plugin("aa")
    assert plugin is not None
    data = tiny_jpeg_path.read_bytes()
    segments, entropy_ranges = api.parse_jpeg(data)  # type: ignore[attr-defined]
    context = build_mutation_context(
        plugin=plugin,
        input_path=str(tiny_jpeg_path),
        fmt="jpeg",
        output_dir=str(tmp_path),
        debug=False,
        params={"sample": 0, "seed": 3},
        data=data,
        segments=segments,
        entropy_ranges=entropy_ranges,
    )

    result = plugin.run(str(tiny_jpeg_path), context)

    total_entropy = sum(r.end - r.start for r in entropy_ranges)
    assert len(result.outputs) == total_entropy
    first_out = Path(result.outputs[0]).read_bytes()
    changed = _changed_offsets(data, first_out)
    assert len(changed) == 1
    assert first_out[changed[0]] == 0xAA


def test_builtin_insert_appn_plugin_writes_segment_level_output(tmp_path: Path, tiny_jpeg_path: Path) -> None:
    clear_registry_for_tests()
    load_plugins(force=True)
    plugin = get_plugin("insert_appn")
    assert plugin is not None
    data = tiny_jpeg_path.read_bytes()
    segments, entropy_ranges = api.parse_jpeg(data)  # type: ignore[attr-defined]
    context = build_mutation_context(
        plugin=plugin,
        input_path=str(tiny_jpeg_path),
        fmt="jpeg",
        output_dir=str(tmp_path),
        debug=False,
        params={"appn": 15, "identifier": "TAG\x00", "payload_hex": "01 02 03", "payload_file": "", "output_path": ""},
        data=data,
        segments=segments,
        entropy_ranges=entropy_ranges,
    )

    result = plugin.run(str(tiny_jpeg_path), context)

    assert len(result.outputs) == 1
    out_path = Path(result.outputs[0])
    out_data = out_path.read_bytes()
    out_segments, _ = api.parse_jpeg(out_data)  # type: ignore[attr-defined]
    assert any(seg.name == "APP15" for seg in out_segments)
    assert len(out_data) > len(data)

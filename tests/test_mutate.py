from pathlib import Path

from jpeg_fault.core.models import EntropyRange
from jpeg_fault.core import mutate as m


def test_parse_bits_and_mode() -> None:
    assert m.parse_bits_list("msb") == [7]
    assert m.parse_bits_list("lsb") == [0]
    assert m.parse_bits_list("0,1,1,3") == [0, 1, 3]

    try:
        m.parse_bits_list("bad")
        assert False
    except ValueError:
        pass

    assert m.parse_mutation_mode("add1") == ("add1", None)
    assert m.parse_mutation_mode("bitflip:0,2") == ("bitflip", [0, 2])

    try:
        m.parse_mutation_mode("wat")
        assert False
    except ValueError:
        pass


def test_mutate_byte_variants() -> None:
    assert m.mutate_byte(0x10, "add1", None) == [(0x11, "add1")]
    assert m.mutate_byte(0xFF, "add1", None) == []
    assert m.mutate_byte(0x01, "sub1", None) == [(0x00, "sub1")]
    assert m.mutate_byte(0x00, "sub1", None) == []
    assert m.mutate_byte(0x0F, "flipall", None) == [(0xF0, "flipall")]
    assert m.mutate_byte(0b0001, "bitflip", [0, 1]) == [(0b0000, "bit0"), (0b0011, "bit1")]
    assert m.mutate_byte(0, "unknown", None) == []

    assert m.mutate_byte_cumulative(0x10, "add1", None) == (0x11, "add1")
    assert m.mutate_byte_cumulative(0xFF, "add1", None) is None
    assert m.mutate_byte_cumulative(0x10, "bitflip", [0, 3]) == (0x19, "bit0-3")


def test_entropy_length_and_offset_selection() -> None:
    ranges = [EntropyRange(10, 13, 0), EntropyRange(20, 22, 1)]
    assert m.total_entropy_length(ranges) == 5
    assert m.build_cumulative(ranges) == [3, 5]
    assert m.index_to_offset(0, ranges, [3, 5]) == 10
    assert m.index_to_offset(4, ranges, [3, 5]) == 21

    all_offsets = m.select_offsets_from_ranges(ranges, 0, 1)
    assert all_offsets == [10, 11, 12, 20, 21]

    sample = m.select_offsets_from_ranges(ranges, 2, 123)
    assert len(sample) == 2
    assert all(o in all_offsets for o in sample)

    cum = m.select_offsets_cumulative(ranges, 2, 7)
    assert len(cum) == 2

    try:
        m.select_offsets_cumulative(ranges, 99, 7)
        assert False
    except ValueError:
        pass


def test_mutable_offsets_step_selection() -> None:
    data = bytes([0x00, 0xFF, 0x01, 0x02, 0x03, 0x04])
    ranges = [EntropyRange(0, 6, 0)]
    assert m.offset_mutable(0xFF, "add1") is False
    assert m.offset_mutable(0x00, "sub1") is False
    assert m.offset_mutable(0x00, "flipall") is True

    offs_add = m.mutable_offsets_in_ranges(data, ranges, "add1")
    assert 1 not in offs_add and len(offs_add) == 5

    assert m.split_offsets_by_step([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]

    groups = m.select_cumulative_step_offsets(data, ranges, sample_n=2, seed=3, mode="add1", step_size=2)
    assert len(groups) == 2 and all(len(g) == 2 for g in groups)

    auto_groups = m.select_cumulative_step_offsets(data, ranges, sample_n=0, seed=3, mode="add1", step_size=2)
    assert len(auto_groups) == 2

    try:
        m.select_cumulative_step_offsets(data, ranges, sample_n=10, seed=3, mode="add1", step_size=2)
        assert False
    except ValueError:
        pass


def test_set_seed_and_output_helpers(tmp_path: Path) -> None:
    assert m.derive_set_seeds(5, 1) == [5]
    assert len(m.derive_set_seeds(5, 3)) == 3

    try:
        m.derive_set_seeds(5, 0)
        assert False
    except ValueError:
        pass

    assert m.cumulative_output_dir("x", 1, 1) == "x"
    assert m.cumulative_output_dir("x", 2, 3).endswith("set_0002")

    name = m.cumulative_out_name("img", 2, 0x10, 1, 2, "add1", 3, 4, 2)
    assert "set_0003" in name and "step_002" in name


def test_write_mutation_files_and_dispatch(tmp_path: Path) -> None:
    data = bytes([0xFF, 0xD8, 0x10, 0x11, 0x12, 0x13, 0xFF, 0xD9])
    ranges = [EntropyRange(2, 6, 0)]
    out = tmp_path / "m"

    cnt = m.write_mutations_independent(data, ranges, str(out), "img", "add1", None, sample_n=2, seed=1, debug=False)
    assert cnt == 2

    files = sorted(out.glob("*.jpg"))
    assert len(files) == 2

    # cumulative with step size 2 and two steps
    out2 = tmp_path / "c"
    cnt2 = m.write_mutations_cumulative(
        data, ranges, str(out2), "img", "add1", None, sample_n=2, seed=4, repeats=1, step_size=2, debug=False
    )
    assert cnt2 == 2
    assert any("step_002" in p.name for p in out2.glob("*.jpg"))

    # write_cumulative_set direct
    out3 = tmp_path / "cs"
    groups = [[2, 3], [4, 5]]
    cnt3 = m.write_cumulative_set(data, groups, str(out3), "img", "add1", None, 1, 1, 2)
    assert cnt3 == 2

    # dispatcher
    cnt4 = m.write_mutations(
        data, ranges, str(tmp_path / "d1"), "img", "add1", None, 2, 1, "independent", 1, 1, False
    )
    assert cnt4 == 2

    cnt5 = m.write_mutations(
        data, ranges, str(tmp_path / "d2"), "img", "add1", None, 2, 1, "cumulative", 1, 1, False
    )
    assert cnt5 == 2

    try:
        m.write_mutations(data, ranges, str(tmp_path / "d3"), "img", "add1", None, 1, 1, "bad", 1, 1, False)
        assert False
    except ValueError:
        pass

    listed = m.list_mutation_files(str(tmp_path), "img")
    assert listed

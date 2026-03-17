from __future__ import annotations

from pathlib import Path

from jpeg_fault.core.tui import JpegFaultTui
from tests.tui_test_helpers import FakeCheckbox, FakeInput, FakeSelect, install_query


def test_mutation_mode_options_cover_supported_specs() -> None:
    app = JpegFaultTui()
    options = app._mutation_mode_options()
    values = [value for _label, value in options]

    assert values == ["add1", "sub1", "flipall", "ff", "00", "bitflip"]
    assert len(values) == len(set(values))


def test_build_options_reads_mutation_mode_from_select(tmp_path: Path) -> None:
    app = JpegFaultTui()
    input_path = tmp_path / "in.jpg"
    input_path.write_bytes(b"\xFF\xD8\xFF\xD9")

    widgets = {
        "#input-path": FakeInput(str(input_path)),
        "#output-dir": FakeInput(str(tmp_path)),
        "#color-mode": FakeInput("auto"),
        "#mutate-mode": FakeSelect("bitflip"),
        "#mutate-bitflip-bits": FakeInput("0,1,3"),
        "#sample": FakeInput("10"),
        "#seed": FakeInput("3"),
        "#overflow-wrap": FakeCheckbox(False),
        "#report-only": FakeCheckbox(False),
        "#debug": FakeCheckbox(False),
        "#mutation-apply": FakeSelect("independent"),
        "#repeats": FakeInput("1"),
        "#step": FakeInput("1"),
        "#gif": FakeInput(""),
        "#gif-fps": FakeInput("10"),
        "#gif-loop": FakeInput("0"),
        "#gif-shuffle": FakeCheckbox(False),
        "#ssim-chart": FakeInput(""),
        "#metrics": FakeInput("ssim"),
        "#metrics-prefix": FakeInput(""),
        "#jobs": FakeInput(""),
    }
    install_query(app, widgets)
    app._selected_plugins_csv = lambda: ""  # type: ignore[assignment]

    options = app._build_options()

    assert options.mutate == "bitflip:0,1,3"


def test_default_mutation_helpers_use_bitflip_defaults() -> None:
    app = JpegFaultTui()
    assert app._default_mutation_mode_value() == "add1"
    assert app._default_mutation_bits_value() == "0,2,7"

    app2 = JpegFaultTui()
    app2.defaults.mutate = "bitflip:lsb"
    assert app2._default_mutation_mode_value() == "bitflip"
    assert app2._default_mutation_bits_value() == "lsb"


def test_mutation_help_text_summarizes_outputs(tmp_path: Path) -> None:
    app = JpegFaultTui()
    input_path = tmp_path / "in.jpg"
    input_path.write_bytes(b"\xFF\xD8\xFF\xD9")

    widgets = {
        "#input-path": FakeInput(str(input_path)),
        "#output-dir": FakeInput(str(tmp_path / "out")),
        "#mutate-mode": FakeSelect("bitflip"),
        "#mutate-bitflip-bits": FakeInput("0,2,7"),
        "#mutation-apply": FakeSelect("cumulative"),
        "#sample": FakeInput("10"),
        "#seed": FakeInput("9"),
        "#repeats": FakeInput("2"),
        "#step": FakeInput("3"),
        "#overflow-wrap": FakeCheckbox(True),
        "#report-only": FakeCheckbox(False),
        "#debug": FakeCheckbox(True),
        "#gif": FakeInput(str(tmp_path / "x.gif")),
        "#ssim-chart": FakeInput(""),
        "#metrics-prefix": FakeInput(str(tmp_path / "metrics")),
    }
    install_query(app, widgets)
    app._safe_selected_plugins_csv = lambda: "entropy_wave,dc_heatmap"  # type: ignore[assignment]

    text = app._mutation_help_text()

    assert "Each selected entropy byte will have bit positions 0,2,7 toggled." in text
    assert "sample setting is 10" in text
    assert "each new file keeps all earlier byte changes and adds the next group of mutations" in text
    assert "Repeats is 2 and step is 3" in text
    assert "mutated JPEG files written into the selected output directory" in text
    assert "\n\n" in text
    assert "a GIF built from the generated mutation outputs" in text
    assert "metric charts for the generated mutation outputs" in text
    assert "analysis plugin outputs from entropy_wave,dc_heatmap" in text
    assert "Equivalent CLI command:" in text
    assert "--mutate bitflip:0,2,7" in text
    assert "--overflow-wrap" in text
    assert "--debug" in text

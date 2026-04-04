from __future__ import annotations

import math
from pathlib import Path

from textual import on
from textual import events
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches, WrongType
from textual.widgets import Button, Input, Label, RichLog, Static, TabbedContent, TabPane
from rich.text import Text

from ..entropy_trace import BlockTrace, ScanTrace, ScanTraceChunk
from ..debug import debug_log
from ..jpeg_parse import decode_dqt_tables


QUERY_ERRORS = (NoMatches, WrongType, AssertionError)
TRACE_PAGE_SIZE = 10
TRACE_WRAP_BYTES = 8
TRACE_VISUAL_CANVAS_SIZE = 200
TRACE_VISUAL_PREVIEW_WIDTH = 24
TRACE_VISUAL_PREVIEW_HEIGHT = 24


class TraceNavButton(Button):
    def __init__(self, label: str, trace_key: str, direction: str, **kwargs) -> None:
        super().__init__(label, **kwargs)
        self.trace_key = trace_key
        self.trace_direction = direction

    def on_click(self, event: events.Click) -> None:
        event.stop()
        app = self.app
        if hasattr(app, "_handle_entropy_trace_nav"):
            app._handle_entropy_trace_nav(self.trace_key, self.trace_direction)


class TraceLoadButton(Button):
    def on_click(self, event: events.Click) -> None:
        event.stop()
        app = self.app
        if hasattr(app, "_trigger_entropy_trace_load"):
            app._trigger_entropy_trace_load()


class TraceBlockButton(Button):
    def __init__(self, label: str, trace_key: str, block_index: int, **kwargs) -> None:
        super().__init__(label, **kwargs)
        self.trace_key = trace_key
        self.trace_block_index = block_index

    def on_click(self, event: events.Click) -> None:
        event.stop()
        app = self.app
        if hasattr(app, "_handle_entropy_trace_block"):
            app._handle_entropy_trace_block(self.trace_key, self.trace_block_index)


class TuiEntropyTraceMixin:
    TRACE_DEBUG_LOG = Path("/tmp/jpeg_trace_debug.log")

    def _next_entropy_trace_reset_id(self) -> int:
        current = int(getattr(self, "_entropy_trace_reset_counter", 0)) + 1
        self._entropy_trace_reset_counter = current
        return current

    def _trace_debug_enabled(self) -> bool:
        try:
            return self._checkbox_value("#debug")
        except Exception:
            return False

    def _trace_debug(self, msg: str) -> None:
        if not self._trace_debug_enabled():
            return
        debug_log(True, msg)
        try:
            with self.TRACE_DEBUG_LOG.open("a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            return

    def _add_entropy_trace_tab(self) -> None:
        tabs = self.query_one("#info-tabs", TabbedContent)
        tabs.add_pane(TabPane("Trace", self._build_entropy_trace_pane()))
        self._reset_entropy_trace_tabs(None)
        self._set_entropy_trace_status("Click Load Trace to decode entropy.")
        self._set_entropy_trace_load_button(disabled=False, label="Load Trace")

    def _build_entropy_trace_pane(self) -> Vertical:
        return Vertical(
            Horizontal(
                TraceLoadButton("Load Trace", id="entropy-trace-load", variant="primary"),
                Static("", id="entropy-trace-status"),
                classes="row",
            ),
            Static("Entropy trace by scan (one stream per SOS).", classes="field"),
            TabbedContent(id="entropy-trace-tabs"),
            id="entropy-trace-panel",
        )

    def _build_entropy_trace_scan_pane(self, key: str) -> Horizontal:
        return Horizontal(
            Vertical(
                Horizontal(
                    TraceNavButton("Prev", key, "prev", id=f"{key}-prev"),
                    TraceNavButton("Next", key, "next", id=f"{key}-next"),
                    Label("Page", classes="field"),
                    Input(value="1", id=f"{key}-page"),
                    Static("", id=f"{key}-page-info"),
                    classes="row",
                ),
                VerticalScroll(id=f"{key}-blocks"),
                classes="sof-left",
            ),
            VerticalScroll(
                TabbedContent(id=f"{key}-detail-tabs"),
                classes="sof-right",
            ),
            classes="row",
        )

    def _populate_entropy_trace_detail_tabs(self, key: str) -> bool:
        try:
            tabs = self.query_one(f"#{key}-detail-tabs", TabbedContent)
        except QUERY_ERRORS:
            return False
        if getattr(tabs, "_trace_tabs_loaded", False):
            return False
        tabs.clear_panes()
        log_ids: dict[str, str] = {}
        for name in ("Overview", "Bits", "DC", "AC", "Coefficients", "Tables"):
            pane_id = name.lower()
            log_id = self._dynamic_pane_id(f"info-{key}-{pane_id}")
            log_ids[pane_id] = log_id
            tabs.add_pane(
                TabPane(
                    name,
                    RichLog(id=log_id, highlight=True, classes="sof-log"),
                    id=self._dynamic_pane_id(f"{key}-pane-{pane_id}"),
                )
            )
        self.entropy_trace_log_ids[key] = log_ids
        tabs.add_pane(
            TabPane(
                "Visualisations",
                self._build_entropy_trace_visualisations_pane(key),
                id=self._dynamic_pane_id(f"{key}-pane-visualisations"),
            )
        )
        setattr(tabs, "_trace_tabs_loaded", True)
        return True

    def _build_entropy_trace_visualisations_pane(self, key: str) -> VerticalScroll:
        return VerticalScroll(TabbedContent(id=f"{key}-visuals-tabs"))

    def _populate_entropy_trace_visualisations_tabs(self, key: str) -> bool:
        try:
            tabs = self.query_one(f"#{key}-visuals-tabs", TabbedContent)
        except QUERY_ERRORS:
            return False
        if getattr(tabs, "_trace_visuals_tabs_loaded", False):
            return False
        tabs.clear_panes()
        tabs.add_pane(
            TabPane(
                "Reconstruction",
                VerticalScroll(Static("", id=f"{key}-visual-reconstruction", classes="field")),
            )
        )
        tabs.add_pane(
            TabPane(
                "Wave Composition",
                VerticalScroll(Static("", id=f"{key}-visual-wave", classes="field")),
            )
        )
        setattr(tabs, "_trace_visuals_tabs_loaded", True)
        return True

    def _reset_entropy_trace_tabs(self, scans: list[ScanTrace] | None) -> list[tuple[str, ScanTrace]]:
        tabs = self.query_one("#entropy-trace-tabs", TabbedContent)
        tabs.clear_panes()
        setattr(tabs, "_trace_real_tabs_loaded", False)
        reset_id = self._next_entropy_trace_reset_id()
        self.entropy_trace_scans = {}
        self.entropy_trace_pages = {}
        self.entropy_trace_selected = {}
        self.entropy_trace_item_ids = {}
        self.entropy_trace_log_ids = {}
        self._entropy_trace_syncing = False
        targets: list[tuple[str, ScanTrace]] = []
        if scans is None:
            pane = TabPane(
                "Trace",
                RichLog(id="info-entropy-trace-empty", highlight=True),
                id=self._dynamic_pane_id(f"entropy-trace-empty-{reset_id}"),
            )
            tabs.add_pane(pane)
            self.query_one("#info-entropy-trace-empty", RichLog).write("Click Load Trace to decode entropy.")
            tabs.show_tab(pane.id)
            return targets
        if not scans:
            pane = TabPane(
                "Trace",
                RichLog(id="info-entropy-trace-empty", highlight=True),
                id=self._dynamic_pane_id(f"entropy-trace-empty-{reset_id}"),
            )
            tabs.add_pane(pane)
            self.query_one("#info-entropy-trace-empty", RichLog).write("No entropy trace available.")
            tabs.show_tab(pane.id)
            return targets
        first_pane_id = None
        for scan in scans:
            key = f"etrace-scan-{scan.scan_index}"
            label = f"Scan {scan.scan_index}"
            pane = TabPane(label, self._build_entropy_trace_scan_pane(key), id=self._dynamic_pane_id(f"{key}-pane"))
            tabs.add_pane(pane)
            if first_pane_id is None:
                first_pane_id = pane.id
            targets.append((key, scan))
        if first_pane_id is not None:
            tabs.show_tab(first_pane_id)
        return targets

    def _render_entropy_trace_tabs(self, targets: list[tuple[str, ScanTrace]]) -> None:
        for key, scan in targets:
            self._render_entropy_trace_scan(key, scan)

    def _set_entropy_trace_status(self, text: str) -> None:
        try:
            self.query_one("#entropy-trace-status", Static).update(text)
        except QUERY_ERRORS:
            return

    def _set_entropy_trace_load_button(self, *, disabled: bool, label: str) -> None:
        try:
            button = self.query_one("#entropy-trace-load", Button)
        except QUERY_ERRORS:
            return
        button.disabled = disabled
        button.label = label

    def _apply_entropy_trace_chunk(self, serial: int, chunk: ScanTraceChunk) -> None:
        if serial != getattr(self, "_entropy_trace_worker_serial", -1):
            return
        key = f"etrace-scan-{chunk.scan_index}"
        created = False
        if key not in self.entropy_trace_scans:
            scan = ScanTrace(
                scan_index=chunk.scan_index,
                sof_name=chunk.sof_name,
                progressive=chunk.progressive,
                supported=chunk.supported,
                reason=chunk.reason,
                ss=chunk.ss,
                se=chunk.se,
                ah=chunk.ah,
                al=chunk.al,
                restart_interval=chunk.restart_interval,
                component_ids=list(chunk.component_ids),
                component_names=list(chunk.component_names),
                total_scan_bits=chunk.total_scan_bits,
                entropy_file_start=chunk.entropy_file_start,
                entropy_file_end=chunk.entropy_file_end,
                blocks=[],
                restart_segments=[],
            )
            self._append_entropy_trace_scan_tab(key, scan)
            self.entropy_trace_scans[key] = scan
            self.entropy_trace_pages.setdefault(key, 0)
            self.entropy_trace_selected.setdefault(key, 0)
            created = True
        scan = self.entropy_trace_scans[key]
        had_blocks = bool(scan.blocks)
        scan.blocks.extend(chunk.blocks)
        scan.restart_segments.extend(chunk.restart_segments)
        if created:
            self._render_entropy_trace_scan(key, scan)
            return
        if not had_blocks and scan.blocks:
            self._render_entropy_trace_page(key)

    def _append_entropy_trace_scan_tab(self, key: str, scan: ScanTrace) -> None:
        tabs = self.query_one("#entropy-trace-tabs", TabbedContent)
        if not getattr(tabs, "_trace_real_tabs_loaded", False):
            tabs.clear_panes()
            setattr(tabs, "_trace_real_tabs_loaded", True)
        pane = TabPane(
            f"Scan {scan.scan_index}",
            self._build_entropy_trace_scan_pane(key),
            id=self._dynamic_pane_id(f"{key}-pane"),
        )
        tabs.add_pane(pane)
        if tabs.tab_count == 1:
            tabs.show_tab(pane.id)

    def _render_entropy_trace_scan(self, key: str, scan: ScanTrace) -> None:
        self.entropy_trace_scans[key] = scan
        self.entropy_trace_pages.setdefault(key, 0)
        self.entropy_trace_selected.setdefault(key, 0)
        if self._populate_entropy_trace_detail_tabs(key):
            self.call_after_refresh(self._populate_entropy_trace_visualisations_tabs, key)
            self.call_after_refresh(self._render_entropy_trace_page, key)
            return
        self._populate_entropy_trace_visualisations_tabs(key)
        self._render_entropy_trace_page(key)

    def _render_entropy_trace_page(self, key: str) -> None:
        try:
            scan = self.entropy_trace_scans[key]
            block_list = self.query_one(f"#{key}-blocks", VerticalScroll)
            page_info = self.query_one(f"#{key}-page-info", Static)
            page_input = self.query_one(f"#{key}-page", Input)
        except QUERY_ERRORS:
            return
        self._trace_debug(f"trace render page key={key}")
        blocks = scan.blocks
        page_total = max(1, (len(blocks) + TRACE_PAGE_SIZE - 1) // TRACE_PAGE_SIZE)
        page = max(0, min(self.entropy_trace_pages.get(key, 0), page_total - 1))
        self.entropy_trace_pages[key] = page
        for child in list(block_list.children):
            child.remove()
        page_input.value = str(page + 1)
        if not scan.supported or not blocks:
            suffix = " (loading)" if getattr(self, "entropy_trace_pending", False) else ""
            page_info.update(f"Scan {scan.scan_index}: {len(blocks)} block(s){suffix}")
            self._render_entropy_trace_scan_summary(key, scan)
            return
        start = page * TRACE_PAGE_SIZE
        end = min(start + TRACE_PAGE_SIZE, len(blocks))
        suffix = " +" if getattr(self, "entropy_trace_pending", False) else ""
        page_info.update(f"Blocks {start + 1}-{end}/{len(blocks)}{suffix}")
        self.entropy_trace_item_counter += 1
        item_generation = self.entropy_trace_item_counter
        for block_index, block in enumerate(blocks[start:end], start=start):
            label = (
                f"MCU {block.mcu_index} | #{block.block_index_in_mcu} {block.component_name} | "
                f"bits {block.scan_bit_start}-{block.scan_bit_end} | bytes {block.scan_byte_start}-{block.scan_byte_end}"
            )
            item = TraceBlockButton(
                label,
                key,
                block_index,
                id=self._dynamic_pane_id(f"{key}-blocksel-{block_index}-{item_generation}"),
            )
            if self.entropy_trace_selected.get(key, start) == block_index:
                item.variant = "primary"
            block_list.mount(item)
        selected_index = self.entropy_trace_selected.get(key, start)
        if selected_index < start or selected_index >= end:
            selected_index = start
            self.entropy_trace_selected[key] = selected_index
        self._trace_debug(f"trace page key={key} start={start} end={end} selected={selected_index}")
        self._render_entropy_trace_block_detail(key, blocks[selected_index], scan)

    def _render_entropy_trace_scan_summary(self, key: str, scan: ScanTrace) -> None:
        logs = self._entropy_trace_logs(key)
        if logs is None:
            return
        for log in logs:
            log.clear()
        overview, bits, dc, ac, coeffs, tables = logs
        overview.write(f"Scan {scan.scan_index}")
        overview.write(f"SOF: {scan.sof_name or '<unknown>'}")
        overview.write(f"Supported: {'yes' if scan.supported else 'no'}")
        overview.write(f"Progressive/refinement: {'yes' if scan.progressive else 'no'}")
        overview.write(f"Components: {', '.join(scan.component_names) or '<none>'}")
        overview.write(f"Bits in scan: {scan.total_scan_bits}")
        overview.write(f"Entropy file range: 0x{scan.entropy_file_start:08X}..0x{max(scan.entropy_file_start, scan.entropy_file_end - 1):08X}")
        if scan.reason:
            overview.write(f"Note: {scan.reason}")
        bits.write("No block-level trace available for this scan.")
        dc.write("No block-level DC trace available.")
        ac.write("No block-level AC trace available.")
        coeffs.write("No coefficient trace available.")
        tables.write("No block-level table provenance available.")

    def _render_entropy_trace_block_detail(self, key: str, block: BlockTrace, scan: ScanTrace) -> None:
        logs = self._entropy_trace_logs(key)
        if logs is None:
            self._trace_debug(f"trace logs missing key={key}")
            return
        self._trace_debug(f"trace detail key={key} mcu={block.mcu_index} block={block.block_index_in_mcu}")
        overview, bits, dc, ac, coeffs, tables = logs
        for log in (overview, bits, dc, ac, coeffs, tables):
            log.clear()
        overview.write(f"Scan {scan.scan_index} MCU {block.mcu_index} block {block.block_index_in_mcu}")
        overview.write(f"Component: {block.component_name} (id={block.component_id})")
        overview.write(f"Restart segment: {block.restart_segment_index}")
        overview.write(f"Bits used: {block.bits_used}")
        overview.write(f"Scan bits: [{block.scan_bit_start},{block.scan_bit_end})")
        overview.write(f"Scan bytes: {block.scan_byte_start}..{block.scan_byte_end}")

        bits.write(f"Scan bit range: [{block.scan_bit_start},{block.scan_bit_end})")
        bits.write(f"Start byte/bit: {block.scan_byte_start}:{block.start_bit_in_byte}")
        bits.write(f"End byte/bit: {block.scan_byte_end}:{block.end_bit_in_byte}")
        bits.write(f"File byte offsets: {self._format_trace_file_offsets(block.file_byte_offsets)}")
        bits.write("")
        bits.write("Bitstream:")
        bit_text = self._format_trace_bitstream(block)
        if bit_text is not None:
            bits.write(bit_text)
        bits.write("")
        bits.write("Bytestream:")
        byte_text = self._format_trace_bytestream(block)
        if byte_text is not None:
            bits.write(byte_text)
        bits.write("")
        bits.write(f"DC Huffman bits: {block.dc.huffman.bits}")
        for step in block.ac_steps:
            bits.write(f"AC symbol bits: {step.huffman.bits}")

        dc.write(f"Table id: {block.dc_table_id}")
        dc.write(f"Category: {block.dc.category}")
        dc.write(f"Value bits: {block.dc.value_bits or '-'}")
        dc.write(f"Diff: {block.dc.diff_value}")
        dc.write(f"Predictor: {block.dc.predictor_before} -> {block.dc.predictor_after}")
        dc.write(f"Coefficient: {block.dc.coefficient}")

        if not block.ac_steps:
            ac.write("No AC steps recorded.")
        for step in block.ac_steps:
            ac.write(
                f"k={step.index} run={step.run_length} size={step.size} symbol=0x{step.symbol_hex} "
                f"huff={step.huffman.bits} value_bits={step.value_bits or '-'} coeff={step.coefficient} "
                f"EOB={step.is_eob} ZRL={step.is_zrl}"
            )

        for line in self._trace_coefficient_interpretation_lines(block):
            coeffs.write(line)
        coeffs.write("")
        coeffs.write("Zigzag coefficients:")
        coeffs.write(" ".join(str(value) for value in block.zz_coeffs))
        coeffs.write("")
        coeffs.write("Natural 8x8 grid:")
        for row in range(8):
            start = row * 8
            coeffs.write(" ".join(f"{value:4d}" for value in block.natural_coeffs[start:start + 8]))
        self._render_entropy_trace_visual(key, block)

        tables.write(f"DC table id: {block.dc_table_id}")
        tables.write(f"AC table id: {block.ac_table_id}")
        tables.write(f"Quant table id: {block.quant_table_id}")
        tables.write(f"Component ids in scan: {', '.join(str(value) for value in scan.component_ids)}")
        tables.write(f"Scan components: {', '.join(scan.component_names)}")
        tables.write(f"Ss={scan.ss} Se={scan.se} Ah={scan.ah} Al={scan.al}")
        tables.write(f"Restart interval: {scan.restart_interval}")

    def _entropy_trace_logs(self, key: str) -> tuple[RichLog, RichLog, RichLog, RichLog, RichLog, RichLog] | None:
        log_ids = self.entropy_trace_log_ids.get(key)
        if log_ids is None:
            log_ids = {
                "overview": f"info-{key}-overview",
                "bits": f"info-{key}-bits",
                "dc": f"info-{key}-dc",
                "ac": f"info-{key}-ac",
                "coefficients": f"info-{key}-coefficients",
                "tables": f"info-{key}-tables",
            }
        if not log_ids:
            return None
        try:
            return (
                self.query_one(f"#{log_ids['overview']}", RichLog),
                self.query_one(f"#{log_ids['bits']}", RichLog),
                self.query_one(f"#{log_ids['dc']}", RichLog),
                self.query_one(f"#{log_ids['ac']}", RichLog),
                self.query_one(f"#{log_ids['coefficients']}", RichLog),
                self.query_one(f"#{log_ids['tables']}", RichLog),
            )
        except QUERY_ERRORS:
            return None

    def _format_trace_file_offsets(self, offsets: list[int]) -> str:
        if not offsets:
            return "<none>"
        if len(offsets) == 1:
            return f"0x{offsets[0]:08X}"
        return f"0x{offsets[0]:08X}..0x{offsets[-1]:08X}"

    def _trace_block_bytes(self, block: BlockTrace) -> list[int]:
        data = getattr(self, "info_data", None)
        if not data:
            return []
        values: list[int] = []
        for offset in block.file_byte_offsets:
            if 0 <= offset < len(data):
                values.append(data[offset])
        return values

    def _format_trace_bytestream(self, block: BlockTrace) -> Text | None:
        values = self._trace_block_bytes(block)
        if not values:
            return None
        text = Text()
        first_index = 0
        last_index = len(values) - 1
        for idx, value in enumerate(values):
            if idx:
                self._append_trace_byte_separator(text, idx)
            style = ""
            if first_index == last_index == idx:
                style = "bold black on yellow"
            elif idx == first_index:
                style = "bold black on cyan"
            elif idx == last_index:
                style = "bold black on magenta"
            text.append(f"{value:02X}", style=style)
        return text

    def _format_trace_bitstream(self, block: BlockTrace) -> Text | None:
        values = self._trace_block_bytes(block)
        if not values:
            return None
        text = Text()
        inactive_style = "grey50"
        first_index = 0
        last_index = len(values) - 1
        for idx, value in enumerate(values):
            if idx:
                self._append_trace_byte_separator(text, idx)
            bits = f"{value:08b}"
            if first_index == last_index == idx:
                start = block.start_bit_in_byte
                end = block.end_bit_in_byte + 1
                text.append(bits[:start], style=inactive_style)
                text.append(bits[start:end], style="bold black on yellow")
                text.append(bits[end:], style=inactive_style)
                continue
            if idx == first_index:
                start = block.start_bit_in_byte
                text.append(bits[:start], style=inactive_style)
                text.append(bits[start:], style="bold black on cyan")
                continue
            if idx == last_index:
                end = block.end_bit_in_byte + 1
                text.append(bits[:end], style="bold black on magenta")
                text.append(bits[end:], style=inactive_style)
                continue
            text.append(bits)
        return text

    def _append_trace_byte_separator(self, text: Text, idx: int) -> None:
        if idx % TRACE_WRAP_BYTES == 0:
            text.append("\n")
            return
        text.append(" ")

    def _render_entropy_trace_visual(self, key: str, block: BlockTrace) -> None:
        try:
            reconstruction_widget = self.query_one(f"#{key}-visual-reconstruction", Static)
            wave_widget = self.query_one(f"#{key}-visual-wave", Static)
        except QUERY_ERRORS:
            return
        coeffs = list(block.natural_coeffs)
        quant_grid = self._trace_quant_natural_grid(block.quant_table_id)
        if quant_grid is None:
            message = "Preview unavailable: missing quantization table."
            reconstruction_widget.update(message)
            wave_widget.update(message)
            return
        reconstruction_pixels = self._trace_visual_reconstruction_pixels(coeffs, quant_grid, TRACE_VISUAL_CANVAS_SIZE)
        wave_pixels = self._trace_visual_wave_pixels(coeffs, quant_grid, TRACE_VISUAL_CANVAS_SIZE)
        reconstruction_widget.update(self._trace_visual_preview_text("Reconstruction", reconstruction_pixels))
        wave_widget.update(self._trace_visual_preview_text("Wave Composition", wave_pixels))

    def _trace_visual_strongest_term(self, coeffs: list[int]) -> tuple[int, int, int] | None:
        best_index = None
        best_value = 0
        for idx, value in enumerate(coeffs[1:], start=1):
            if abs(value) > abs(best_value):
                best_index = idx
                best_value = value
        if best_index is None or best_value == 0:
            return None
        return best_index // 8, best_index % 8, best_value

    def _trace_coefficient_interpretation_lines(self, block: BlockTrace) -> list[str]:
        coeffs = list(block.natural_coeffs)
        strongest = self._trace_visual_strongest_term(coeffs)
        lines = [
            "Interpretation:",
            (
                f"- DC = {coeffs[0]}: the block's low-frequency base level, "
                "roughly its overall brightness in JPEG transform space."
            ),
            "- AC terms add variation on top of that base; larger magnitudes contribute more strongly.",
            "- Negative values are normal and mean that basis pattern contributes in the opposite phase.",
            "- Zigzag is JPEG storage order; Natural 8x8 is the same values mapped back into frequency positions.",
        ]
        if strongest is None:
            lines.append("- Strongest AC term: <none>")
        else:
            u, v, value = strongest
            lines.append(f"- Strongest AC term: ({u},{v}) = {value}")
        return lines

    def _trace_visual_reconstruction_pixels(
        self,
        natural_coeffs: list[int],
        quant_grid: list[int],
        canvas_size: int,
    ) -> list[list[int]]:
        samples = self._trace_visual_sample_block(natural_coeffs, quant_grid)
        return self._trace_visual_upscale_block(samples, canvas_size)

    def _trace_visual_wave_pixels(
        self,
        natural_coeffs: list[int],
        quant_grid: list[int],
        canvas_size: int,
    ) -> list[list[int]]:
        dequant = [coef * quant for coef, quant in zip(natural_coeffs, quant_grid)]
        raw: list[list[float]] = []
        max_abs = 0.0
        for y in range(canvas_size):
            row: list[float] = []
            fy = ((y + 0.5) * 8.0 / canvas_size) - 0.5
            for x in range(canvas_size):
                fx = ((x + 0.5) * 8.0 / canvas_size) - 0.5
                value = self._trace_visual_idct_value(dequant, fx, fy)
                row.append(value)
                max_abs = max(max_abs, abs(value))
            raw.append(row)
        if max_abs <= 1e-9:
            return [[128 for _ in range(canvas_size)] for _ in range(canvas_size)]
        pixels: list[list[int]] = []
        for row in raw:
            pixels.append([self._clamp_byte(128.0 + (127.0 * value / max_abs)) for value in row])
        return pixels

    def _trace_visual_sample_block(self, natural_coeffs: list[int], quant_grid: list[int]) -> list[list[int]]:
        dequant = [coef * quant for coef, quant in zip(natural_coeffs, quant_grid)]
        samples: list[list[int]] = []
        for y in range(8):
            row: list[int] = []
            for x in range(8):
                value = 128.0 + self._trace_visual_idct_value(dequant, x, y)
                row.append(self._clamp_byte(value))
            samples.append(row)
        return samples

    def _trace_visual_idct_value(self, natural_coeffs: list[int], x: float, y: float) -> float:
        total = 0.0
        for u in range(8):
            cu = 1.0 / math.sqrt(2.0) if u == 0 else 1.0
            for v in range(8):
                coeff = natural_coeffs[(u * 8) + v]
                if coeff == 0:
                    continue
                cv = 1.0 / math.sqrt(2.0) if v == 0 else 1.0
                total += (
                    cu
                    * cv
                    * coeff
                    * math.cos(((2.0 * x) + 1.0) * u * math.pi / 16.0)
                    * math.cos(((2.0 * y) + 1.0) * v * math.pi / 16.0)
                )
        return 0.25 * total

    def _trace_visual_upscale_block(self, samples: list[list[int]], canvas_size: int) -> list[list[int]]:
        pixels: list[list[int]] = []
        for y in range(canvas_size):
            source_y = min(7, int(y * 8 / canvas_size))
            row: list[int] = []
            for x in range(canvas_size):
                source_x = min(7, int(x * 8 / canvas_size))
                row.append(samples[source_y][source_x])
            pixels.append(row)
        return pixels

    def _trace_visual_pixels_to_text(self, pixels: list[list[int]]) -> Text:
        text = Text()
        height = len(pixels)
        width = len(pixels[0]) if pixels else 0
        if not width or not height:
            text.append("Preview unavailable.")
            return text
        for row_index in range(TRACE_VISUAL_PREVIEW_HEIGHT):
            if row_index:
                text.append("\n")
            y0 = int(row_index * height / TRACE_VISUAL_PREVIEW_HEIGHT)
            y1 = max(y0 + 1, int((row_index + 1) * height / TRACE_VISUAL_PREVIEW_HEIGHT))
            for col_index in range(TRACE_VISUAL_PREVIEW_WIDTH):
                x0 = int(col_index * width / TRACE_VISUAL_PREVIEW_WIDTH)
                x1 = max(x0 + 1, int((col_index + 1) * width / TRACE_VISUAL_PREVIEW_WIDTH))
                total = 0
                count = 0
                for yy in range(y0, min(y1, height)):
                    for xx in range(x0, min(x1, width)):
                        total += pixels[yy][xx]
                        count += 1
                value = total // max(1, count)
                style = f"on rgb({value},{value},{value})"
                text.append("  ", style=style)
        return text

    def _trace_visual_preview_text(self, title: str, pixels: list[list[int]]) -> Text:
        text = Text()
        text.append(title)
        text.append("\n\n")
        text.append_text(self._trace_visual_pixels_to_text(pixels))
        return text

    def _trace_quant_natural_grid(self, table_id: int) -> list[int] | None:
        data = getattr(self, "info_data", None)
        segments = getattr(self, "info_segments", None)
        if data is None or segments is None:
            return None
        for seg in segments:
            if seg.name != "DQT" or seg.payload_offset is None or seg.payload_length is None:
                continue
            payload = data[seg.payload_offset:seg.payload_offset + seg.payload_length]
            for table in decode_dqt_tables(payload):
                if int(table.get("id", -1)) != table_id:
                    continue
                values = list(table.get("values", []))[:64]
                natural = [0] * 64
                for idx, value in enumerate(values):
                    zigzag_pos = idx
                    natural_index = self._trace_visual_natural_index_from_zigzag(zigzag_pos)
                    natural[natural_index] = int(value)
                return natural
        return None

    def _trace_visual_natural_index_from_zigzag(self, zigzag_index: int) -> int:
        from ..constants.jpeg import JPEG_ZIGZAG_ORDER

        return JPEG_ZIGZAG_ORDER[zigzag_index]

    def _clamp_byte(self, value: float) -> int:
        return max(0, min(255, int(round(value))))

    def _entropy_trace_key_from_widget_id(self, widget_id: str | None, suffix: str) -> str | None:
        if not widget_id or not widget_id.endswith(suffix):
            return None
        return widget_id[: -len(suffix)]

    def _entropy_trace_select_block(self, key: str, block_index: int) -> None:
        scan = self.entropy_trace_scans.get(key)
        if scan is None:
            return
        if 0 <= block_index < len(scan.blocks):
            self.entropy_trace_selected[key] = block_index
            self._render_entropy_trace_block_detail(key, scan.blocks[block_index], scan)

    def _handle_entropy_trace_nav(self, key: str, direction: str) -> None:
        self._trace_debug(f"trace nav key={key} dir={direction}")
        if direction == "prev":
            if self.entropy_trace_pages.get(key, 0) > 0:
                self.entropy_trace_pages[key] -= 1
                self._render_entropy_trace_page(key)
            return
        scan = self.entropy_trace_scans.get(key)
        if scan is None:
            return
        total_pages = max(1, (len(scan.blocks) + TRACE_PAGE_SIZE - 1) // TRACE_PAGE_SIZE)
        if self.entropy_trace_pages.get(key, 0) + 1 < total_pages:
            self.entropy_trace_pages[key] += 1
            self._render_entropy_trace_page(key)

    def _handle_entropy_trace_block(self, key: str, block_index: int) -> None:
        self._trace_debug(f"trace block key={key} index={block_index}")
        self._entropy_trace_select_block(key, block_index)

    def _trigger_entropy_trace_load(self) -> None:
        if getattr(self, "entropy_trace_pending", False):
            return
        data = getattr(self, "info_data", None)
        segments = getattr(self, "info_segments", None)
        entropy_ranges = getattr(self, "info_entropy_ranges", None)
        if data is None or segments is None or entropy_ranges is None:
            self._set_entropy_trace_status("Load image info first.")
            return
        self.entropy_trace_loaded = False
        self.entropy_trace_pending = True
        self._reset_entropy_trace_tabs(None)
        self._set_entropy_trace_status("Loading entropy trace...")
        self._set_entropy_trace_load_button(disabled=True, label="Loading Trace...")
        self._entropy_trace_worker_serial = getattr(self, "_info_rebuild_serial", 0)
        self._start_entropy_trace_worker(data, segments, entropy_ranges, self._entropy_trace_worker_serial)

    @on(Button.Pressed, "#entropy-trace-load")
    def _on_entropy_trace_load_pressed(self, event: Button.Pressed) -> None:
        self._trigger_entropy_trace_load()

    @on(Button.Pressed)
    def _on_entropy_trace_nav_pressed(self, event: Button.Pressed) -> None:
        button = event.button
        if not isinstance(button, TraceNavButton):
            return
        self._handle_entropy_trace_nav(button.trace_key, button.trace_direction)

    @on(Button.Pressed)
    def _on_entropy_trace_block_pressed(self, event: Button.Pressed) -> None:
        button = event.button
        if not isinstance(button, TraceBlockButton):
            return
        self._handle_entropy_trace_block(button.trace_key, button.trace_block_index)

    @on(Input.Changed)
    def _on_entropy_trace_page_changed(self, event: Input.Changed) -> None:
        key = self._entropy_trace_key_from_widget_id(event.input.id, "-page")
        if key is None:
            return
        scan = self.entropy_trace_scans.get(key)
        if scan is None:
            return
        text = event.input.value.strip()
        if not text:
            return
        try:
            page = int(text) - 1
        except ValueError:
            return
        total_pages = max(1, (len(scan.blocks) + TRACE_PAGE_SIZE - 1) // TRACE_PAGE_SIZE)
        if 0 <= page < total_pages:
            self.entropy_trace_pages[key] = page
            self._render_entropy_trace_page(key)

    def _render_entropy_trace_visual_for_selected_block(self, key: str) -> None:
        scan = self.entropy_trace_scans.get(key)
        if scan is None or not scan.blocks:
            return
        block_index = self.entropy_trace_selected.get(key, 0)
        block_index = max(0, min(block_index, len(scan.blocks) - 1))
        self._render_entropy_trace_visual(key, scan.blocks[block_index])

from __future__ import annotations

from pathlib import Path

from textual import on
from textual import events
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches, WrongType
from textual.widgets import Button, Input, Label, RichLog, Static, TabbedContent, TabPane
from rich.text import Text

from ..entropy_trace import BlockTrace, ScanTrace, ScanTraceChunk
from ..debug import debug_log


QUERY_ERRORS = (NoMatches, WrongType, AssertionError)
TRACE_PAGE_SIZE = 10


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
                Static("Views: overview, bits, dc, ac, coefficients, tables", classes="field"),
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
        setattr(tabs, "_trace_tabs_loaded", True)
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
            self.call_after_refresh(self._render_entropy_trace_page, key)
            return
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

        coeffs.write("Zigzag coefficients:")
        coeffs.write(" ".join(str(value) for value in block.zz_coeffs))
        coeffs.write("")
        coeffs.write("Natural 8x8 grid:")
        for row in range(8):
            start = row * 8
            coeffs.write(" ".join(f"{value:4d}" for value in block.natural_coeffs[start:start + 8]))

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
                text.append(" ")
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
        first_index = 0
        last_index = len(values) - 1
        for idx, value in enumerate(values):
            if idx:
                text.append(" ")
            bits = f"{value:08b}"
            if first_index == last_index == idx:
                start = block.start_bit_in_byte
                end = block.end_bit_in_byte + 1
                text.append(bits[:start])
                text.append(bits[start:end], style="bold black on yellow")
                text.append(bits[end:])
                continue
            if idx == first_index:
                start = block.start_bit_in_byte
                text.append(bits[:start])
                text.append(bits[start:], style="bold black on cyan")
                continue
            if idx == last_index:
                end = block.end_bit_in_byte + 1
                text.append(bits[:end], style="bold black on magenta")
                text.append(bits[end:])
                continue
            text.append(bits)
        return text

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

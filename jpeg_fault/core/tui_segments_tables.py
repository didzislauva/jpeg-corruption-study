from __future__ import annotations

import ast
import re
from pprint import pformat
from typing import Optional

from textual import on
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    Label,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
    TextArea,
)
from rich.text import Text

from .jpeg_parse import (
    JPEG_ZIGZAG_ORDER,
    build_dht_payload,
    build_dqt_payload,
    decode_dht,
    decode_dht_tables,
    decode_dqt,
    decode_dqt_tables,
    decode_sof_components,
    decode_sos_components,
    dqt_natural_grid_to_values,
    dqt_values_to_natural_grid,
)


class TuiSegmentsTablesMixin:
    def _text_area_cursor(self, editor: TextArea) -> tuple[int, int]:
        cursor = getattr(editor, "cursor_location", (0, 0))
        if isinstance(cursor, tuple) and len(cursor) >= 2:
            return int(cursor[0]), int(cursor[1])
        row = int(getattr(cursor, "row", 0))
        col = int(getattr(cursor, "column", 0))
        return row, col

    def _value_span_in_line(self, line: str, name: str) -> Optional[tuple[int, int]]:
        match = re.search(rf"'{re.escape(name)}'\s*:\s*([^,\]\}}]+)", line)
        if match is None:
            return None
        return match.start(1), match.end(1)

    def _number_spans_in_line(self, line: str) -> list[tuple[int, int, int]]:
        spans: list[tuple[int, int, int]] = []
        for match in re.finditer(r"-?\d+", line):
            spans.append((match.start(), match.end(), int(match.group(0))))
        return spans

    def _add_dqt_tab(self) -> None:
        tabs = self.query_one("#info-tabs", TabbedContent)
        tabs.add_pane(TabPane("DQT", self._build_dqt_pane()))
        self._reset_dqt_tabs([])

    def _add_dht_tab(self) -> None:
        tabs = self.query_one("#info-tabs", TabbedContent)
        tabs.add_pane(TabPane("DHT", self._build_dht_pane()))
        self._reset_dht_tabs([])

    def _build_dqt_pane(self) -> Vertical:
        return Vertical(
            Static("Quantization tables (DQT)", classes="field"),
            TabbedContent(id="dqt-tabs"),
            id="dqt-panel",
        )

    def _build_dht_pane(self) -> Vertical:
        return Vertical(
            Static("Huffman tables (DHT)", classes="field"),
            TabbedContent(id="dht-tabs"),
            id="dht-panel",
        )

    def _build_dqt_segment_pane(self, key: str, title: str) -> Horizontal:
        return Horizontal(
            VerticalScroll(
                Static(f"{title} bytes and structure", classes="field"),
                RichLog(id=f"info-{key}-left", highlight=True, classes="dqt-log dqt-left"),
            ),
            VerticalScroll(
                Static("Views: grid, zigzag, stats, usage, heatmap, edit", classes="field"),
                TabbedContent(id=f"{key}-tabs"),
                classes="dqt-right",
            ),
            classes="row",
        )

    def _init_dqt_detail_tabs(self, key: str) -> None:
        tabs = self.query_one(f"#{key}-tabs", TabbedContent)
        tabs.clear_panes()
        for name in ("Grid", "Zigzag", "Stats", "Usage", "Heatmap"):
            pane_id = name.lower()
            tabs.add_pane(
                TabPane(name, RichLog(id=f"info-{key}-{pane_id}", highlight=True, classes="dqt-log"))
            )
        tabs.add_pane(
            TabPane(
                "Edit",
                VerticalScroll(
                    Static("Edit DQT tables in natural 8x8 order or raw payload hex.", classes="field"),
                    Checkbox("Advanced mode (raw payload hex)", value=False, id=f"{key}-advanced-mode"),
                    Checkbox("Manual length (dangerous)", value=False, id=f"{key}-manual-length"),
                    Input(value="", id=f"{key}-length", placeholder="Length (hex, e.g. 0043)"),
                    Button("Save edited file", id=f"{key}-save", variant="success", disabled=True),
                    Static("", id=f"{key}-error"),
                    Static("Natural-grid editor", classes="field", id=f"{key}-simple-title"),
                    TextArea("", id=f"{key}-grid-edit", soft_wrap=True, show_line_numbers=True, classes="dqt-edit-area"),
                    Static("Raw payload hex", classes="field", id=f"{key}-adv-title"),
                    TextArea("", id=f"{key}-raw-hex", soft_wrap=True, show_line_numbers=True, classes="dqt-edit-area"),
                ),
            )
        )

    def _build_dht_segment_pane(self, key: str, title: str) -> Horizontal:
        return Horizontal(
            VerticalScroll(
                Static(f"{title} bytes and structure", classes="field"),
                RichLog(id=f"info-{key}-left", highlight=True, classes="dht-log dht-left"),
            ),
            VerticalScroll(
                Static("Views: tables, counts, symbols, usage, codes, edit", classes="field"),
                TabbedContent(id=f"{key}-tabs"),
                classes="dht-right",
            ),
            classes="row",
        )

    def _init_dht_detail_tabs(self, key: str) -> None:
        tabs = self.query_one(f"#{key}-tabs", TabbedContent)
        tabs.clear_panes()
        for name in ("Tables", "Counts", "Symbols", "Usage", "Codes"):
            pane_id = name.lower()
            tabs.add_pane(
                TabPane(name, RichLog(id=f"info-{key}-{pane_id}", highlight=True, classes="dht-log"))
            )
        tabs.add_pane(
            TabPane(
                "Edit",
                VerticalScroll(
                    Static("Edit DHT tables as Python literal or raw payload hex.", classes="field"),
                    Checkbox("Advanced mode (raw payload hex)", value=False, id=f"{key}-advanced-mode"),
                    Checkbox("Manual length (dangerous)", value=False, id=f"{key}-manual-length"),
                    Input(value="", id=f"{key}-length", placeholder="Length (hex, e.g. 001F)"),
                    Button("Save edited file", id=f"{key}-save", variant="success", disabled=True),
                    Static("", id=f"{key}-error"),
                    Static("Structured editor", classes="field", id=f"{key}-simple-title"),
                    TextArea("", id=f"{key}-table-edit", soft_wrap=True, show_line_numbers=True, classes="dht-edit-area"),
                    Static("Raw payload hex", classes="field", id=f"{key}-adv-title"),
                    TextArea("", id=f"{key}-raw-hex", soft_wrap=True, show_line_numbers=True, classes="dht-edit-area"),
                ),
            )
        )

    @on(Checkbox.Changed)
    def _on_dqt_checkbox_changed(self, event: Checkbox.Changed) -> None:
        key = self._dqt_key_from_id(event.checkbox.id, "-advanced-mode")
        if key:
            self._apply_dqt_mode_visibility(key)
            try:
                self._sync_dqt_editor_for_mode(key)
            except Exception:
                pass
            self._refresh_dqt_preview(key)
            return
        key = self._dqt_key_from_id(event.checkbox.id, "-manual-length")
        if not key:
            return
        self._apply_dqt_mode_visibility(key)
        if not event.checkbox.value and key in self.dqt_preview_payload:
            payload = self.dqt_preview_payload[key]
            self.query_one(f"#{key}-length", Input).value = f"{len(payload) + 2:04X}"
        self._refresh_dqt_preview(key)

    @on(Input.Changed)
    def _on_dqt_input_changed(self, event: Input.Changed) -> None:
        key = self._dqt_key_from_id(event.input.id, "-length")
        if not key:
            return
        self._set_dqt_dirty(key, True)
        if self.query_one(f"#{key}-manual-length", Checkbox).value:
            self._refresh_dqt_preview(key)

    @on(TextArea.Changed)
    def _on_dqt_textarea_changed(self, event: TextArea.Changed) -> None:
        key = self._dqt_key_from_id(event.text_area.id, "-grid-edit")
        if not key:
            key = self._dqt_key_from_id(event.text_area.id, "-raw-hex")
        if not key:
            return
        if event.text_area.id.endswith("-grid-edit"):
            self._update_dqt_active_highlight(key)
        else:
            self.dqt_active_highlight.pop(key, None)
        if not self.query_one(f"#{key}-manual-length", Checkbox).value:
            try:
                payload = self._build_dqt_payload(key)
            except Exception:
                self._set_dqt_dirty(key, True)
            else:
                self.query_one(f"#{key}-length", Input).value = f"{len(payload) + 2:04X}"
        self._refresh_dqt_preview(key)

    @on(TextArea.SelectionChanged)
    def _on_dqt_selection_changed(self, event: TextArea.SelectionChanged) -> None:
        key = self._dqt_key_from_id(event.text_area.id, "-grid-edit")
        if key:
            self._update_dqt_active_highlight(key)
            if key in self.dqt_segment_info and key in self.dqt_preview_payload:
                offset, _, length_field, _ = self.dqt_segment_info[key]
                self._render_dqt_views(key, self.dqt_preview_payload[key], offset, length_field)
            return
        key = self._dht_key_from_id(event.text_area.id, "-table-edit")
        if not key:
            return
        self._update_dht_active_highlight(key)
        if key in self.dht_segment_info and key in self.dht_preview_payload:
            offset, _, length_field, _ = self.dht_segment_info[key]
            self._render_dht_views(key, self.dht_preview_payload[key], offset, length_field)

    @on(Button.Pressed)
    def _on_dqt_save(self, event: Button.Pressed) -> None:
        key = self._dqt_key_from_id(event.button.id, "-save")
        if not key:
            return
        err = self.query_one(f"#{key}-error", Static)
        err.update("")
        try:
            input_path, payload, length_field = self._dqt_save_inputs(key)
        except Exception as e:
            err.update(f"Error: {e}")
            return
        out_path = self._dqt_write_file(key, input_path, payload, length_field)
        self._dqt_save_log(key, out_path, payload, length_field)
        self._set_dqt_dirty(key, False)

    @on(Checkbox.Changed)
    def _on_dht_checkbox_changed(self, event: Checkbox.Changed) -> None:
        key = self._dht_key_from_id(event.checkbox.id, "-advanced-mode")
        if key:
            self._apply_dht_mode_visibility(key)
            try:
                self._sync_dht_editor_for_mode(key)
            except Exception:
                pass
            self._refresh_dht_preview(key)
            return
        key = self._dht_key_from_id(event.checkbox.id, "-manual-length")
        if not key:
            return
        self._apply_dht_mode_visibility(key)
        if not event.checkbox.value and key in self.dht_preview_payload:
            payload = self.dht_preview_payload[key]
            self.query_one(f"#{key}-length", Input).value = f"{len(payload) + 2:04X}"
        self._refresh_dht_preview(key)

    @on(Input.Changed)
    def _on_dht_input_changed(self, event: Input.Changed) -> None:
        key = self._dht_key_from_id(event.input.id, "-length")
        if not key:
            return
        self._set_dht_dirty(key, True)
        if self.query_one(f"#{key}-manual-length", Checkbox).value:
            self._refresh_dht_preview(key)

    @on(TextArea.Changed)
    def _on_dht_textarea_changed(self, event: TextArea.Changed) -> None:
        key = self._dht_key_from_id(event.text_area.id, "-table-edit")
        if not key:
            key = self._dht_key_from_id(event.text_area.id, "-raw-hex")
        if not key:
            return
        if event.text_area.id.endswith("-table-edit"):
            self._update_dht_active_highlight(key)
        else:
            self.dht_active_highlight.pop(key, None)
        if not self.query_one(f"#{key}-manual-length", Checkbox).value:
            try:
                payload = self._build_dht_payload(key)
            except Exception:
                self._set_dht_dirty(key, True)
            else:
                self.query_one(f"#{key}-length", Input).value = f"{len(payload) + 2:04X}"
        self._refresh_dht_preview(key)

    @on(Button.Pressed)
    def _on_dht_save(self, event: Button.Pressed) -> None:
        key = self._dht_key_from_id(event.button.id, "-save")
        if not key:
            return
        err = self.query_one(f"#{key}-error", Static)
        err.update("")
        try:
            input_path, payload, length_field = self._dht_save_inputs(key)
        except Exception as e:
            err.update(f"Error: {e}")
            return
        out_path = self._dht_write_file(key, input_path, payload, length_field)
        self._dht_save_log(key, out_path, payload, length_field)
        self._set_dht_dirty(key, False)

    def _reset_dqt_tabs(self, segments) -> list[Tuple[str, object]]:
        dqt_tabs = self.query_one("#dqt-tabs", TabbedContent)
        dqt_tabs.clear_panes()
        targets: list[Tuple[str, object]] = []
        dqt_segments = [s for s in segments if s.name == "DQT"]
        if not dqt_segments:
            pane = TabPane("DQT", RichLog(id="info-dqt-empty", highlight=True))
            dqt_tabs.add_pane(pane)
            self.query_one("#info-dqt-empty", RichLog).write("No DQT segments found.")
            dqt_tabs.show_tab(pane.id)
            return targets
        first_pane_id = None
        for idx, seg in enumerate(dqt_segments, start=1):
            key = f"dqt-{seg.offset:08X}"
            label = f"DQT #{idx}"
            pane = TabPane(label, self._build_dqt_segment_pane(key, label))
            dqt_tabs.add_pane(pane)
            self._init_dqt_detail_tabs(key)
            if first_pane_id is None:
                first_pane_id = pane.id
            targets.append((key, seg))
        if first_pane_id is not None:
            dqt_tabs.show_tab(first_pane_id)
        return targets

    def _reset_dht_tabs(self, segments) -> list[Tuple[str, object]]:
        dht_tabs = self.query_one("#dht-tabs", TabbedContent)
        dht_tabs.clear_panes()
        targets: list[Tuple[str, object]] = []
        dht_segments = [s for s in segments if s.name == "DHT"]
        if not dht_segments:
            pane = TabPane("DHT", RichLog(id="info-dht-empty", highlight=True))
            dht_tabs.add_pane(pane)
            self.query_one("#info-dht-empty", RichLog).write("No DHT segments found.")
            dht_tabs.show_tab(pane.id)
            return targets
        first_pane_id = None
        for idx, seg in enumerate(dht_segments, start=1):
            key = f"dht-{seg.offset:08X}"
            label = f"DHT #{idx}"
            pane = TabPane(label, self._build_dht_segment_pane(key, label))
            dht_tabs.add_pane(pane)
            self._init_dht_detail_tabs(key)
            if first_pane_id is None:
                first_pane_id = pane.id
            targets.append((key, seg))
        if first_pane_id is not None:
            dht_tabs.show_tab(first_pane_id)
        return targets

    def _render_dqt_segments(self, data: bytes, targets: list[Tuple[str, object]]) -> None:
        for key, seg in targets:
            self._render_dqt_segment(data, seg, key)

    def _render_dht_segments(self, data: bytes, targets: list[Tuple[str, object]]) -> None:
        for key, seg in targets:
            self._render_dht_segment(data, seg, key)

    def _render_dht_segment(self, data: bytes, seg, key: str) -> None:
        left_log = self.query_one(f"#info-{key}-left", RichLog)
        if seg.payload_offset is None or seg.payload_length is None:
            left_log.clear()
            left_log.write("DHT has no payload.")
            return
        payload = data[seg.payload_offset:seg.payload_offset + seg.payload_length]
        self.dht_segment_info[key] = (seg.offset, seg.total_length, seg.length_field or 0, seg.payload_offset)
        self.dht_original_payload[key] = payload
        self.dht_preview_payload[key] = payload
        self._set_dht_editor_values(key, payload, seg.length_field or 0)
        self._apply_dht_mode_visibility(key)
        self._set_dht_dirty(key, False)
        self._render_dht_views(key, payload, seg.offset, seg.length_field or 0)

    def _render_dht_views(self, key: str, payload: bytes, offset: int, length_field: int) -> None:
        left_log = self.query_one(f"#info-{key}-left", RichLog)
        tables_log = self.query_one(f"#info-{key}-tables", RichLog)
        counts_log = self.query_one(f"#info-{key}-counts", RichLog)
        symbols_log = self.query_one(f"#info-{key}-symbols", RichLog)
        usage_log = self.query_one(f"#info-{key}-usage", RichLog)
        codes_log = self.query_one(f"#info-{key}-codes", RichLog)
        for log in (left_log, tables_log, counts_log, symbols_log, usage_log, codes_log):
            log.clear()
        # Keep one decode pass for summaries and one for the full structured views.
        summaries = decode_dht(payload)
        tables = decode_dht_tables(payload)
        self._write_dht_left_panel(key, left_log, offset, length_field, payload, summaries, tables)
        self._write_dht_tables_tab(tables_log, tables)
        self._write_dht_counts_tab(counts_log, tables)
        self._write_dht_symbols_tab(symbols_log, tables)
        self._write_dht_usage_tab(usage_log, tables)
        self._write_dht_codes_tab(codes_log, tables)

    def _write_dht_left_panel(
        self, key: str, log: RichLog, offset: int, length_field: int, payload: bytes, summaries, tables
    ) -> None:
        log.write(f"DHT at 0x{offset:08X} length=0x{length_field:04X} payload={len(payload)}")
        log.write(f"Tables in segment: {len(tables)}")
        log.write("JPEG stores canonical Huffman tables as 16 code-length counts followed by symbols.")
        log.write("Legend:")
        for label, style in [
            ("Marker", "bold yellow"),
            ("Length", "bold cyan"),
            ("Table header (Tc/Th)", "bright_blue"),
            ("Code-length counts", "magenta"),
            ("Symbol values", "green"),
        ]:
            log.write(Text("  " + label, style=style))
        for idx, table in enumerate(summaries, start=1):
            log.write(f"Table {idx}: {', '.join(f'{k}={v}' for k, v in table.items())}")
        segment_bytes = b"\xFF\xC4" + length_field.to_bytes(2, "big") + payload
        for line in self._hex_dump(segment_bytes, 0, len(segment_bytes), self._dht_ranges(key, payload)):
            log.write(line)

    def _dht_ranges(self, key: str, payload: bytes) -> list[Tuple[int, int, str]]:
        ranges = [(0, 2, "bold yellow"), (2, 4, "bold cyan")]
        payload_idx = 0
        cursor = 4
        colors = [("magenta", "green"), ("bright_magenta", "bright_green")]
        table_idx = 0
        while payload_idx + 17 <= len(payload):
            header_start = cursor
            ranges.append((header_start, header_start + 1, "bright_blue"))
            payload_idx += 1
            cursor += 1
            counts = list(payload[payload_idx:payload_idx + 16])
            ranges.append((cursor, cursor + 16, colors[table_idx % 2][0]))
            payload_idx += 16
            cursor += 16
            total = sum(counts)
            sym_end = min(cursor + total, 4 + len(payload))
            if total > 0:
                ranges.append((cursor, sym_end, colors[table_idx % 2][1]))
            payload_idx += total
            cursor = sym_end
            table_idx += 1
        return self._with_keyed_active_highlight(ranges, self.dht_active_highlight.get(key))

    def _write_dht_tables_tab(self, log: RichLog, tables: list[dict[str, object]]) -> None:
        if not tables:
            log.write("No decodable DHT tables found.")
            return
        log.write("Canonical Huffman table summaries.")
        for idx, table in enumerate(tables, start=1):
            log.write("")
            log.write(f"Table {idx}: class={table['class']} id={table['id']}")
            log.write(f"  symbols={len(table['symbols'])} max_code_length={self._dht_max_length(table)}")
            log.write(f"  total_count_sum={sum(table['counts'])}")

    def _write_dht_counts_tab(self, log: RichLog, tables: list[dict[str, object]]) -> None:
        if not tables:
            log.write("No decodable DHT tables found.")
            return
        log.write("Counts are the number of codes for bit lengths 1..16.")
        for idx, table in enumerate(tables, start=1):
            counts = list(table["counts"])
            log.write("")
            log.write(f"Table {idx}: class={table['class']} id={table['id']}")
            for start in range(0, 16, 8):
                chunk = counts[start:start + 8]
                line = " ".join(f"L{start + i + 1:02d}:{count:3d}" for i, count in enumerate(chunk))
                log.write(line)

    def _write_dht_symbols_tab(self, log: RichLog, tables: list[dict[str, object]]) -> None:
        if not tables:
            log.write("No decodable DHT tables found.")
            return
        log.write("Symbols are listed in JPEG payload order after the 16 count bytes.")
        for idx, table in enumerate(tables, start=1):
            symbols = list(table["symbols"])
            log.write("")
            log.write(f"Table {idx}: class={table['class']} id={table['id']}")
            if not symbols:
                log.write("  No symbols.")
                continue
            for start in range(0, len(symbols), 8):
                chunk = symbols[start:start + 8]
                line = " ".join(f"{start + i:02d}:0x{symbol:02X}" for i, symbol in enumerate(chunk))
                log.write(line)

    def _write_dht_usage_tab(self, log: RichLog, tables: list[dict[str, object]]) -> None:
        if not tables:
            log.write("No decodable DHT tables found.")
            return
        scans = self._scan_huffman_usage()
        if not scans:
            log.write("No SOS component mapping found, so Huffman-table usage cannot be inferred.")
            return
        log.write("Usage is inferred from SOS component selectors (DC/AC table ids per scan component).")
        for table in tables:
            table_class = str(table["class"])
            table_id = int(table["id"])
            log.write("")
            log.write(f"Table class={table_class} id={table_id}")
            hits = []
            for scan_idx, scan in enumerate(scans, start=1):
                for comp in scan:
                    wanted = comp["dc_table_id"] if table_class == "DC" else comp["ac_table_id"]
                    if wanted != table_id:
                        continue
                    hits.append((scan_idx, comp))
            if not hits:
                log.write("  No scan components reference this table.")
                continue
            for scan_idx, comp in hits:
                log.write(f"  Scan {scan_idx}: component {comp['id']} ({self._component_name(comp['id'])})")

    def _write_dht_codes_tab(self, log: RichLog, tables: list[dict[str, object]]) -> None:
        if not tables:
            log.write("No decodable DHT tables found.")
            return
        log.write("Canonical codes reconstructed from the JPEG count bytes.")
        for idx, table in enumerate(tables, start=1):
            codes = list(table["codes"])
            log.write("")
            log.write(f"Table {idx}: class={table['class']} id={table['id']}")
            if not codes:
                log.write("  No codes.")
                continue
            for start in range(0, len(codes), 8):
                chunk = codes[start:start + 8]
                parts = [
                    f"{entry['code']:0{entry['length']}b}:{entry['symbol']:02X}"
                    for entry in chunk
                ]
                log.write(" ".join(parts))

    def _dht_max_length(self, table: dict[str, object]) -> int:
        counts = list(table["counts"])
        for idx in range(15, -1, -1):
            if counts[idx]:
                return idx + 1
        return 0

    def _scan_huffman_usage(self) -> list[list[dict[str, int]]]:
        if not self.info_segments or not self.info_data:
            return []
        scans = []
        for seg in self.info_segments:
            if seg.name != "SOS" or seg.payload_offset is None or seg.payload_length is None:
                continue
            payload = self.info_data[seg.payload_offset:seg.payload_offset + seg.payload_length]
            components = decode_sos_components(payload)
            if components:
                scans.append(components)
        return scans

    def _render_dqt_segment(self, data: bytes, seg, key: str) -> None:
        left_log = self.query_one(f"#info-{key}-left", RichLog)
        if seg.payload_offset is None or seg.payload_length is None:
            left_log.clear()
            left_log.write("DQT has no payload.")
            return
        payload = data[seg.payload_offset:seg.payload_offset + seg.payload_length]
        self.dqt_segment_info[key] = (seg.offset, seg.total_length, seg.length_field or 0, seg.payload_offset)
        self.dqt_original_payload[key] = payload
        self.dqt_preview_payload[key] = payload
        self._set_dqt_editor_values(key, payload, seg.length_field or 0)
        self._apply_dqt_mode_visibility(key)
        self._set_dqt_dirty(key, False)
        self._render_dqt_views(key, payload, seg.offset, seg.length_field or 0)

    def _render_dqt_views(self, key: str, payload: bytes, offset: int, length_field: int) -> None:
        left_log = self.query_one(f"#info-{key}-left", RichLog)
        grid_log = self.query_one(f"#info-{key}-grid", RichLog)
        zigzag_log = self.query_one(f"#info-{key}-zigzag", RichLog)
        stats_log = self.query_one(f"#info-{key}-stats", RichLog)
        usage_log = self.query_one(f"#info-{key}-usage", RichLog)
        heatmap_log = self.query_one(f"#info-{key}-heatmap", RichLog)
        for log in (left_log, grid_log, zigzag_log, stats_log, usage_log, heatmap_log):
            log.clear()
        # The left panel shows the segment as stored; the right panels show derived views.
        tables = decode_dqt(payload)
        full_tables = decode_dqt_tables(payload)
        self._write_dqt_left_panel(key, left_log, offset, length_field, payload, tables, full_tables)
        self._write_dqt_grid_tab(grid_log, full_tables)
        self._write_dqt_zigzag_tab(zigzag_log, full_tables)
        self._write_dqt_stats_tab(stats_log, full_tables)
        self._write_dqt_usage_tab(usage_log, full_tables)
        self._write_dqt_heatmap_tab(heatmap_log, full_tables)

    def _write_dqt_left_panel(
        self, key: str, log: RichLog, offset: int, length_field: int, payload: bytes, tables, full_tables
    ) -> None:
        log.write(f"DQT at 0x{offset:08X} length=0x{length_field:04X} payload={len(payload)}")
        log.write(f"Tables in segment: {len(full_tables)}")
        log.write("JPEG stores DQT values in zigzag order; analysis views may remap them into natural 8x8 order.")
        log.write("Legend:")
        for label, style in [
            ("Marker", "bold yellow"),
            ("Length", "bold cyan"),
            ("Table header (Pq/Tq)", "bright_blue"),
            ("Table payload", "green"),
        ]:
            log.write(Text("  " + label, style=style))
        for idx, table in enumerate(tables, start=1):
            log.write(f"Table {idx}: {', '.join(f'{k}={v}' for k, v in table.items())}")
        segment_bytes = b"\xFF\xDB" + length_field.to_bytes(2, "big") + payload
        ranges = self._dqt_ranges(key, payload, log)
        for line in self._hex_dump(segment_bytes, 0, len(segment_bytes), ranges):
            log.write(line)

    def _dqt_ranges(self, key: str, payload: bytes, log: RichLog) -> list[Tuple[int, int, str]]:
        ranges = [(0, 2, "bold yellow"), (2, 4, "bold cyan")]
        cursor = 4
        payload_idx = 0
        colors = ["green", "bright_green"]
        while payload_idx < len(payload):
            table_start = cursor
            if payload_idx >= len(payload):
                break
            pq_tq = payload[payload_idx]
            payload_idx += 1
            cursor += 1
            precision = 16 if (pq_tq >> 4) else 8
            size = 128 if precision == 16 else 64
            table_end = min(cursor + size, 4 + len(payload))
            ranges.append((table_start, table_start + 1, "bright_blue"))
            if table_start + 1 < table_end:
                ranges.append((table_start + 1, table_end, colors[(len(ranges) // 2) % len(colors)]))
            payload_idx += size
            cursor = table_end
        return self._with_keyed_active_highlight(ranges, self.dqt_active_highlight.get(key))

    def _with_keyed_active_highlight(
        self,
        ranges: list[Tuple[int, int, str]],
        highlight: Optional[tuple[int, int, str, str]],
    ) -> list[Tuple[int, int, str]]:
        if highlight is None:
            return ranges
        start, end, style, _ = highlight
        return [*ranges, (start, end, style)]

    def _write_dqt_grid_tab(self, log: RichLog, tables: list[dict[str, object]]) -> None:
        if not tables:
            log.write("No decodable DQT tables found.")
            return
        log.write("Natural 8x8 view. Top-left is DC / lowest spatial frequency.")
        log.write("Rows and columns increase toward higher spatial frequencies.")
        for idx, table in enumerate(tables, start=1):
            table_id = int(table.get("id", 0))
            precision = int(table.get("precision_bits", 8))
            grid = dqt_values_to_natural_grid(list(table.get("values", [])))
            log.write("")
            log.write(f"Table {idx} (id={table_id}, precision={precision}-bit)")
            for line in self._format_dqt_grid(grid, precision):
                log.write(line)

    def _write_dqt_zigzag_tab(self, log: RichLog, tables: list[dict[str, object]]) -> None:
        if not tables:
            log.write("No decodable DQT tables found.")
            return
        log.write("Raw JPEG serialization order (zigzag). Index 0 is DC, later indices move toward higher frequencies.")
        for idx, table in enumerate(tables, start=1):
            values = list(table.get("values", []))
            precision = int(table.get("precision_bits", 8))
            width = 4 if precision <= 8 else 6
            log.write("")
            log.write(f"Table {idx} zigzag order:")
            for start in range(0, len(values), 8):
                chunk = values[start:start + 8]
                text = " ".join(f"{start + i:02d}:{value:{width}d}" for i, value in enumerate(chunk))
                log.write(text)

    def _write_dqt_stats_tab(self, log: RichLog, tables: list[dict[str, object]]) -> None:
        if not tables:
            log.write("No decodable DQT tables found.")
            return
        log.write("Stats use raw zigzag values. Low-frequency = first 10 entries; high-frequency = last 10 entries.")
        for idx, table in enumerate(tables, start=1):
            values = list(table.get("values", []))
            if not values:
                continue
            low_band = values[:10]
            high_band = values[-10:]
            mean = sum(values) / len(values)
            median = sorted(values)[len(values) // 2]
            log.write("")
            log.write(f"Table {idx} (id={table.get('id')}, precision={table.get('precision_bits')}-bit)")
            log.write(f"  min={min(values)} max={max(values)} mean={mean:.2f} median={median}")
            log.write(f"  DC={values[0]} low-band avg={sum(low_band) / len(low_band):.2f}")
            log.write(f"  high-band avg={sum(high_band) / len(high_band):.2f}")
            log.write(f"  monotonic trend: {'rising' if values[-1] >= values[0] else 'mixed/non-rising'}")

    def _write_dqt_usage_tab(self, log: RichLog, tables: list[dict[str, object]]) -> None:
        if not tables:
            log.write("No decodable DQT tables found.")
            return
        components = self._frame_components()
        if not components:
            log.write("No SOF component mapping found, so table usage cannot be inferred.")
            return
        log.write("Usage is inferred from the frame header's component -> quantization table mapping.")
        for table in tables:
            table_id = int(table.get("id", 0))
            users = [comp for comp in components if comp["quant_table_id"] == table_id]
            log.write("")
            log.write(f"Table id={table_id}")
            if not users:
                log.write("  No frame components reference this table.")
                continue
            for comp in users:
                name = self._component_name(comp["id"])
                sampling = f"{comp['h_sampling']}x{comp['v_sampling']}"
                log.write(f"  Component {comp['id']} ({name}) sampling={sampling}")

    def _write_dqt_heatmap_tab(self, log: RichLog, tables: list[dict[str, object]]) -> None:
        if not tables:
            log.write("No decodable DQT tables found.")
            return
        log.write("Heatmap view of the natural 8x8 grid. Hotter cells indicate larger quantization values.")
        for idx, table in enumerate(tables, start=1):
            grid = dqt_values_to_natural_grid(list(table.get("values", [])))
            flat = [value for row in grid for value in row]
            vmin, vmax = min(flat), max(flat)
            log.write("")
            log.write(f"Table {idx} heatmap (id={table.get('id')}):")
            log.write(f"Range: {vmin}..{vmax}")
            for row_idx, row in enumerate(grid):
                line = Text(f"v{row_idx} ", style="bold white")
                for col_idx, value in enumerate(row):
                    # The TUI has no true canvas here, so the heatmap is encoded in cell background color.
                    style = self._heatmap_style(value, vmin, vmax)
                    label = f"{value:4d}"
                    if row_idx == 0 and col_idx == 0:
                        label = f"[{value:02d}]"
                    line.append(label + " ", style=style)
                log.write(line)

    def _format_dqt_grid(self, grid: list[list[int]], precision: int) -> list[Text]:
        if precision <= 8:
            fmt = "{:4d}"
        else:
            fmt = "{:6d}"
        lines: list[Text] = []
        header = "      " + " ".join(f"h{idx:>3}" for idx in range(8))
        lines.append(Text(header, style="bold white"))
        for row_idx, row in enumerate(grid):
            line = Text(f"v{row_idx:>2} ", style="bold white")
            for col_idx, value in enumerate(row):
                cell = fmt.format(value)
                style = "bold yellow" if row_idx == 0 and col_idx == 0 else "white"
                line.append(cell + " ", style=style)
            lines.append(line)
        return lines

    def _frame_components(self) -> list[dict[str, int]]:
        if not self.info_segments or not self.info_data:
            return []
        for seg in self.info_segments:
            if not seg.name.startswith("SOF") or seg.payload_offset is None or seg.payload_length is None:
                continue
            payload = self.info_data[seg.payload_offset:seg.payload_offset + seg.payload_length]
            components = decode_sof_components(payload)
            if components:
                return components
        return []

    def _component_name(self, comp_id: int) -> str:
        names = {1: "Y / luma", 2: "Cb", 3: "Cr", 4: "I", 5: "Q"}
        return names.get(comp_id, "unknown / custom")

    def _heatmap_style(self, value: int, vmin: int, vmax: int) -> str:
        if vmax <= vmin:
            r, g, b = 96, 96, 96
        else:
            ratio = (value - vmin) / (vmax - vmin)
            r = int(40 + 190 * ratio)
            g = int(60 + 110 * (1.0 - abs(ratio - 0.5) * 2.0))
            b = int(180 - 140 * ratio)
        fg = "black" if (r + g + b) > 380 else "white"
        return f"{fg} on rgb({r},{g},{b})"

    def _dqt_key_from_id(self, widget_id: Optional[str], suffix: str) -> Optional[str]:
        if not widget_id or not widget_id.startswith("dqt-") or not widget_id.endswith(suffix):
            return None
        return widget_id[: -len(suffix)]

    def _apply_dqt_mode_visibility(self, key: str) -> None:
        self._apply_editor_mode_visibility(
            advanced_id=f"{key}-advanced-mode",
            struct_id=f"{key}-grid-edit",
            simple_title_id=f"{key}-simple-title",
            raw_id=f"{key}-raw-hex",
            adv_title_id=f"{key}-adv-title",
            manual_length_id=f"{key}-manual-length",
            length_id=f"{key}-length",
        )

    def _set_dqt_editor_values(self, key: str, payload: bytes, length_field: int) -> None:
        tables = []
        for table in decode_dqt_tables(payload):
            tables.append({
                "id": int(table.get("id", 0)),
                "precision_bits": int(table.get("precision_bits", 8)),
                "grid": dqt_values_to_natural_grid(list(table.get("values", []))),
            })
        self.query_one(f"#{key}-raw-hex", TextArea).text = self._bytes_to_hex(payload)
        self.query_one(f"#{key}-grid-edit", TextArea).text = pformat(tables, width=100, sort_dicts=False)
        self.query_one(f"#{key}-length", Input).value = f"{length_field:04X}"
        self._update_dqt_active_highlight(key)

    def _update_dqt_active_highlight(self, key: str) -> None:
        self.dqt_active_highlight.pop(key, None)
        try:
            if self.query_one(f"#{key}-advanced-mode", Checkbox).value:
                return
            editor = self.query_one(f"#{key}-grid-edit", TextArea)
        except Exception:
            return
        try:
            payload = self._build_dqt_payload(key)
        except Exception:
            payload = self.dqt_preview_payload.get(key, b"")
        highlight = self._dqt_highlight_from_editor(editor, payload)
        if highlight is not None:
            self.dqt_active_highlight[key] = highlight

    def _dqt_highlight_from_editor(
        self, editor: TextArea, payload: bytes
    ) -> Optional[tuple[int, int, str, str]]:
        line_no, col_no = self._text_area_cursor(editor)
        lines = editor.text.splitlines() or [editor.text]
        if not lines:
            return None
        line_no = max(0, min(line_no, len(lines) - 1))
        line = lines[line_no]
        table_index = max(0, len(re.findall(r"\{'id'\s*:", "\n".join(lines[:line_no + 1]))) - 1)
        layout = self._dqt_table_layout(payload)
        if table_index >= len(layout):
            return None
        table_start, value_width = layout[table_index]
        for name in ("id", "precision_bits"):
            span = self._value_span_in_line(line, name)
            if span is not None and span[0] <= col_no < span[1]:
                return (table_start, table_start + 1, "bold black on grey70", f"DQT {name}")
        row_index = self._dqt_grid_row_index(lines, line_no)
        if row_index is None:
            return None
        for value_index, (start, end, _) in enumerate(self._number_spans_in_line(line)):
            if not (start <= col_no < end):
                continue
            natural_index = row_index * 8 + value_index
            zigzag_index = JPEG_ZIGZAG_ORDER.index(natural_index)
            byte_start = table_start + 1 + zigzag_index * value_width
            return (byte_start, byte_start + value_width, "bold black on grey70", "DQT value")
        return None

    def _dqt_grid_row_index(self, lines: list[str], line_no: int) -> Optional[int]:
        for idx in range(line_no, -1, -1):
            if "'grid':" in lines[idx]:
                return line_no - idx
        return None

    def _dqt_table_layout(self, payload: bytes) -> list[tuple[int, int]]:
        layout: list[tuple[int, int]] = []
        payload_idx = 0
        cursor = 4
        while payload_idx < len(payload):
            header = payload[payload_idx]
            value_width = 2 if (header >> 4) else 1
            value_count = 64
            layout.append((cursor, value_width))
            payload_idx += 1 + value_count * value_width
            cursor += 1 + value_count * value_width
        return layout

    def _serialize_dqt_struct_to_payload(self, key: str) -> bytes:
        parsed = ast.literal_eval(self.query_one(f"#{key}-grid-edit", TextArea).text)
        if not isinstance(parsed, list):
            raise ValueError("grid editor must be a list of table dictionaries.")
        tables = []
        for idx, item in enumerate(parsed, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"table {idx} must be a dictionary.")
            grid = item.get("grid")
            if not isinstance(grid, list) or len(grid) != 8 or any(
                not isinstance(row, list) or len(row) != 8 for row in grid
            ):
                raise ValueError(f"table {idx} grid must be an 8x8 list.")
            tables.append({
                "id": int(item.get("id", 0)),
                "precision_bits": int(item.get("precision_bits", 8)),
                "values": dqt_natural_grid_to_values([[int(value) for value in row] for row in grid]),
            })
        return build_dqt_payload(tables)

    def _deserialize_dqt_payload_to_struct(self, key: str, payload: bytes) -> None:
        tables = []
        for table in decode_dqt_tables(payload):
            tables.append({
                "id": int(table.get("id", 0)),
                "precision_bits": int(table.get("precision_bits", 8)),
                "grid": dqt_values_to_natural_grid(list(table.get("values", []))),
            })
        self.query_one(f"#{key}-grid-edit", TextArea).text = pformat(tables, width=100, sort_dicts=False)

    def _sync_dqt_editor_for_mode(self, key: str) -> None:
        self._sync_keyed_editor_for_mode(
            key=key,
            advanced_id=f"{key}-advanced-mode",
            raw_id=f"{key}-raw-hex",
            serialize_struct=self._serialize_dqt_struct_to_payload,
            deserialize_payload=self._deserialize_dqt_payload_to_struct,
        )

    def _build_dqt_payload(self, key: str) -> bytes:
        if self.query_one(f"#{key}-advanced-mode", Checkbox).value:
            return self._parse_hex(self.query_one(f"#{key}-raw-hex", TextArea).text)
        try:
            return self._serialize_dqt_struct_to_payload(key)
        except Exception as e:
            raise ValueError(f"invalid grid editor content: {e}")

    def _set_dqt_dirty(self, key: str, dirty: bool) -> None:
        self.dqt_dirty[key] = dirty
        try:
            self.query_one(f"#{key}-save", Button).disabled = not dirty
        except Exception:
            return

    def _dqt_length_from_ui(self, key: str, payload: bytes) -> int:
        return self._length_from_ui_hex(
            manual_length_id=f"{key}-manual-length",
            length_id=f"{key}-length",
            payload=payload,
            example="0043",
        )

    def _refresh_dqt_preview(self, key: str) -> None:
        self._update_dqt_active_highlight(key)
        self._refresh_keyed_segment_preview(
            key=key,
            segment_info=self.dqt_segment_info,
            err_id=f"{key}-error",
            build_payload=self._build_dqt_payload,
            length_from_ui=self._dqt_length_from_ui,
            set_preview=self._set_dqt_preview_payload,
            render_views=self._render_dqt_views,
            set_dirty=self._set_dqt_dirty,
        )

    def _set_dqt_preview_payload(self, key: str, payload: bytes) -> None:
        self.dqt_preview_payload[key] = payload

    def _dqt_save_inputs(self, key: str) -> Tuple[str, bytes, int]:
        input_path = self.query_one("#input-path", Input).value.strip()
        if not input_path:
            raise ValueError("input path is required.")
        if key not in self.dqt_segment_info:
            raise ValueError("DQT not loaded. Click Load Info first.")
        payload = self._build_dqt_payload(key)
        return input_path, payload, self._dqt_length_from_ui(key, payload)

    def _dqt_write_file(self, key: str, input_path: str, payload: bytes, length_field: int) -> Path:
        offset, total_len, _, _ = self.dqt_segment_info[key]
        return self._write_segment_edit_file(
            input_path=input_path,
            offset=offset,
            total_len=total_len,
            payload=payload,
            length_field=length_field,
            suffix=f"_{key}_edit",
        )

    def _dqt_save_log(self, key: str, out_path: Path, payload: bytes, length_field: int) -> None:
        self._segment_save_log(
            log_id=f"info-{key}-left",
            out_path=out_path,
            payload=payload,
            length_field=length_field,
            manual_length_id=f"{key}-manual-length",
        )

    def _dht_key_from_id(self, widget_id: Optional[str], suffix: str) -> Optional[str]:
        if not widget_id or not widget_id.startswith("dht-") or not widget_id.endswith(suffix):
            return None
        return widget_id[: -len(suffix)]

    def _apply_dht_mode_visibility(self, key: str) -> None:
        self._apply_editor_mode_visibility(
            advanced_id=f"{key}-advanced-mode",
            struct_id=f"{key}-table-edit",
            simple_title_id=f"{key}-simple-title",
            raw_id=f"{key}-raw-hex",
            adv_title_id=f"{key}-adv-title",
            manual_length_id=f"{key}-manual-length",
            length_id=f"{key}-length",
        )

    def _set_dht_editor_values(self, key: str, payload: bytes, length_field: int) -> None:
        tables = []
        for table in decode_dht_tables(payload):
            tables.append({
                "class": str(table["class"]),
                "id": int(table["id"]),
                "counts": list(table["counts"]),
                "symbols": list(table["symbols"]),
            })
        self.query_one(f"#{key}-raw-hex", TextArea).text = self._bytes_to_hex(payload)
        self.query_one(f"#{key}-table-edit", TextArea).text = pformat(tables, width=100, sort_dicts=False)
        self.query_one(f"#{key}-length", Input).value = f"{length_field:04X}"
        self._update_dht_active_highlight(key)

    def _update_dht_active_highlight(self, key: str) -> None:
        self.dht_active_highlight.pop(key, None)
        try:
            if self.query_one(f"#{key}-advanced-mode", Checkbox).value:
                return
            editor = self.query_one(f"#{key}-table-edit", TextArea)
        except Exception:
            return
        try:
            payload = self._build_dht_payload(key)
        except Exception:
            payload = self.dht_preview_payload.get(key, b"")
        highlight = self._dht_highlight_from_editor(editor, payload)
        if highlight is not None:
            self.dht_active_highlight[key] = highlight

    def _dht_highlight_from_editor(
        self, editor: TextArea, payload: bytes
    ) -> Optional[tuple[int, int, str, str]]:
        line_no, col_no = self._text_area_cursor(editor)
        lines = editor.text.splitlines() or [editor.text]
        if not lines:
            return None
        line_no = max(0, min(line_no, len(lines) - 1))
        line = lines[line_no]
        table_index = max(0, len(re.findall(r"\{'class'\s*:", "\n".join(lines[:line_no + 1]))) - 1)
        layout = self._dht_table_layout(payload)
        if table_index >= len(layout):
            return None
        header_start, counts_start, symbols_start = layout[table_index]
        for name in ("class", "id"):
            span = self._value_span_in_line(line, name)
            if span is not None and span[0] <= col_no < span[1]:
                return (header_start, header_start + 1, "bold black on grey70", f"DHT {name}")
        if "'counts':" in line:
            for idx, (start, end, _) in enumerate(self._number_spans_in_line(line)):
                if start <= col_no < end:
                    return (counts_start + idx, counts_start + idx + 1, "bold black on grey70", "DHT count")
        if "'symbols':" in line:
            for idx, (start, end, _) in enumerate(self._number_spans_in_line(line)):
                if start <= col_no < end:
                    return (symbols_start + idx, symbols_start + idx + 1, "bold black on grey70", "DHT symbol")
        return None

    def _dht_table_layout(self, payload: bytes) -> list[tuple[int, int, int]]:
        layout: list[tuple[int, int, int]] = []
        payload_idx = 0
        cursor = 4
        while payload_idx + 17 <= len(payload):
            header_start = cursor
            payload_idx += 1
            cursor += 1
            counts = list(payload[payload_idx:payload_idx + 16])
            counts_start = cursor
            payload_idx += 16
            cursor += 16
            symbols_start = cursor
            total = sum(counts)
            payload_idx += total
            cursor += total
            layout.append((header_start, counts_start, symbols_start))
        return layout

    def _serialize_dht_struct_to_payload(self, key: str) -> bytes:
        parsed = ast.literal_eval(self.query_one(f"#{key}-table-edit", TextArea).text)
        if not isinstance(parsed, list):
            raise ValueError("table editor must be a list of table dictionaries.")
        tables = []
        for idx, item in enumerate(parsed, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"table {idx} must be a dictionary.")
            tables.append({
                "class": str(item.get("class", "DC")),
                "id": int(item.get("id", 0)),
                "counts": [int(v) for v in list(item.get("counts", []))],
                "symbols": [int(v) for v in list(item.get("symbols", []))],
            })
        return build_dht_payload(tables)

    def _deserialize_dht_payload_to_struct(self, key: str, payload: bytes) -> None:
        tables = []
        for table in decode_dht_tables(payload):
            tables.append({
                "class": str(table["class"]),
                "id": int(table["id"]),
                "counts": list(table["counts"]),
                "symbols": list(table["symbols"]),
            })
        self.query_one(f"#{key}-table-edit", TextArea).text = pformat(tables, width=100, sort_dicts=False)

    def _sync_dht_editor_for_mode(self, key: str) -> None:
        self._sync_keyed_editor_for_mode(
            key=key,
            advanced_id=f"{key}-advanced-mode",
            raw_id=f"{key}-raw-hex",
            serialize_struct=self._serialize_dht_struct_to_payload,
            deserialize_payload=self._deserialize_dht_payload_to_struct,
        )

    def _build_dht_payload(self, key: str) -> bytes:
        if self.query_one(f"#{key}-advanced-mode", Checkbox).value:
            return self._parse_hex(self.query_one(f"#{key}-raw-hex", TextArea).text)
        try:
            return self._serialize_dht_struct_to_payload(key)
        except Exception as e:
            raise ValueError(f"invalid table editor content: {e}")

    def _set_dht_dirty(self, key: str, dirty: bool) -> None:
        self.dht_dirty[key] = dirty
        try:
            self.query_one(f"#{key}-save", Button).disabled = not dirty
        except Exception:
            return

    def _dht_length_from_ui(self, key: str, payload: bytes) -> int:
        return self._length_from_ui_hex(
            manual_length_id=f"{key}-manual-length",
            length_id=f"{key}-length",
            payload=payload,
            example="001F",
        )

    def _refresh_dht_preview(self, key: str) -> None:
        if key not in self.dht_segment_info:
            return
        self._update_dht_active_highlight(key)
        err = self.query_one(f"#{key}-error", Static)
        warning = None
        try:
            payload = self._build_dht_payload(key)
            length_field = self._dht_length_from_ui(key, payload)
        except Exception as e:
            if self.query_one(f"#{key}-advanced-mode", Checkbox).value:
                try:
                    payload = self._parse_hex_lenient(
                        self.query_one(f"#{key}-raw-hex", TextArea).text
                    )
                    length_field = self._dht_length_from_ui(key, payload)
                    warning = f"Warning: {e}"
                except Exception:
                    err.update(f"Error: {e}")
                    return
            else:
                err.update(f"Error: {e}")
                return
        err.update(warning or "")
        self._set_dht_preview_payload(key, payload)
        offset, _, _, _ = self.dht_segment_info[key]
        self._render_dht_views(key, payload, offset, length_field)
        self._set_dht_dirty(key, True)

    def _set_dht_preview_payload(self, key: str, payload: bytes) -> None:
        self.dht_preview_payload[key] = payload

    def _dht_save_inputs(self, key: str) -> Tuple[str, bytes, int]:
        input_path = self.query_one("#input-path", Input).value.strip()
        if not input_path:
            raise ValueError("input path is required.")
        if key not in self.dht_segment_info:
            raise ValueError("DHT not loaded. Click Load Info first.")
        payload = self._build_dht_payload(key)
        return input_path, payload, self._dht_length_from_ui(key, payload)

    def _dht_write_file(self, key: str, input_path: str, payload: bytes, length_field: int) -> Path:
        offset, total_len, _, _ = self.dht_segment_info[key]
        return self._write_segment_edit_file(
            input_path=input_path,
            offset=offset,
            total_len=total_len,
            payload=payload,
            length_field=length_field,
            suffix=f"_{key}_edit",
        )

    def _dht_save_log(self, key: str, out_path: Path, payload: bytes, length_field: int) -> None:
        self._segment_save_log(
            log_id=f"info-{key}-left",
            out_path=out_path,
            payload=payload,
            length_field=length_field,
            manual_length_id=f"{key}-manual-length",
        )

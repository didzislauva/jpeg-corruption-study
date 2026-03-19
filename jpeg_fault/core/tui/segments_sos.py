from __future__ import annotations

import ast
import re
from pathlib import Path
from pprint import pformat
from typing import Optional, Tuple

from textual import on
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches, WrongType
from textual.widget import Widget
from textual.widgets import Button, Checkbox, Input, Label, RichLog, Static, TabbedContent, TabPane, TextArea
from rich.text import Text

from ..debug import debug_log
from ..jpeg_parse import build_sos_payload, decode_dht_tables, decode_dri, decode_sos, decode_sos_components, decode_sof_components


QUERY_ERRORS = (NoMatches, WrongType, AssertionError)


class SosCheckbox(Checkbox):
    def __init__(self, label: str, sos_key: str, sos_role: str, **kwargs) -> None:
        super().__init__(label, **kwargs)
        self.sos_key = sos_key
        self.sos_role = sos_role

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        event.stop()
        app = self.app
        if hasattr(app, "_handle_sos_checkbox"):
            app._handle_sos_checkbox(self.sos_key, self.sos_role, event.value)


class SosTextArea(TextArea):
    def __init__(self, text: str, sos_key: str, sos_role: str, **kwargs) -> None:
        super().__init__(text, **kwargs)
        self.sos_key = sos_key
        self.sos_role = sos_role

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        event.stop()
        app = self.app
        if hasattr(app, "_handle_sos_textarea_changed"):
            app._handle_sos_textarea_changed(self.sos_key, self.sos_role, self)

    def on_text_area_selection_changed(self, event: TextArea.SelectionChanged) -> None:
        event.stop()
        app = self.app
        if hasattr(app, "_handle_sos_textarea_selection_changed"):
            app._handle_sos_textarea_selection_changed(self.sos_key, self.sos_role, self)


class SosSaveButton(Button):
    def __init__(self, label: str, sos_key: str, **kwargs) -> None:
        super().__init__(label, **kwargs)
        self.sos_key = sos_key

    def on_click(self, event) -> None:
        event.stop()
        app = self.app
        if hasattr(app, "_handle_sos_save"):
            app._handle_sos_save(self.sos_key)


class TuiSegmentsSosMixin:
    SOS_DEBUG_LOG = Path("/tmp/jpeg_sos_debug.log")

    def _sos_debug_enabled(self) -> bool:
        try:
            return self._checkbox_value("#debug")
        except Exception:
            return False

    def _sos_debug(self, msg: str) -> None:
        if not self._sos_debug_enabled():
            return
        debug_log(True, msg)
        try:
            with self.SOS_DEBUG_LOG.open("a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            return

    def _add_sos_tab(self) -> None:
        tabs = self.query_one("#info-tabs", TabbedContent)
        tabs.add_pane(TabPane("SOS", self._build_sos_pane()))
        self._reset_sos_tabs([])

    def _build_sos_pane(self) -> Vertical:
        return Vertical(
            Static("Start Of Scan sections (SOS)", classes="field"),
            TabbedContent(id="sos-tabs"),
            id="sos-panel",
        )

    def _build_sos_segment_pane(self, key: str, title: str, root_id: str) -> Horizontal:
        return Horizontal(
            VerticalScroll(
                Static(f"{title} bytes and scan summary", classes="field"),
                RichLog(id=f"info-{key}-left", highlight=True, classes="sof-log sof-left"),
            ),
            VerticalScroll(
                Static("Views: header, components, flow, links, edit", classes="field"),
                TabbedContent(id=f"{key}-tabs"),
                classes="sof-right",
            ),
            classes="row",
            id=root_id,
        )

    def _init_sos_detail_tabs(self, key: str) -> None:
        tabs = self.query_one(f"#{key}-tabs", TabbedContent)
        tabs.clear_panes()
        for name in ("Header", "Components", "Flow", "Links"):
            pane_id = name.lower()
            tabs.add_pane(
                TabPane(
                    name,
                    RichLog(id=f"info-{key}-{pane_id}", highlight=True, classes="sof-log"),
                    id=self._dynamic_pane_id(f"{key}-pane-{pane_id}"),
                )
            )
        tabs.add_pane(
                TabPane(
                    "Edit",
                    VerticalScroll(
                        Static("Edit SOS scan header as Python literal or raw payload hex.", classes="field"),
                        SosCheckbox("Advanced mode (raw payload hex)", key, "advanced", value=False, id=f"{key}-advanced-mode"),
                        SosCheckbox("Manual length (dangerous)", key, "manual-length", value=False, id=f"{key}-manual-length"),
                        Input(value="", id=f"{key}-length", placeholder="Length (hex, e.g. 000C)"),
                        SosSaveButton("Save edited file", key, id=f"{key}-save", variant="success", disabled=True),
                        Static("", id=f"{key}-error"),
                        Static("Structured editor", classes="field", id=f"{key}-simple-title"),
                        SosTextArea("", key, "struct", id=f"{key}-struct-edit", soft_wrap=True, show_line_numbers=True, classes="sof-edit-area"),
                        Static("Raw payload hex", classes="field", id=f"{key}-adv-title"),
                        SosTextArea("", key, "raw", id=f"{key}-raw-hex", soft_wrap=True, show_line_numbers=True, classes="sof-edit-area"),
                    ),
                    id=self._dynamic_pane_id(f"{key}-pane-edit"),
                )
            )

    def _reset_sos_tabs(self, segments) -> list[tuple[str, object, int]]:
        tabs = self.query_one("#sos-tabs", TabbedContent)
        tabs.clear_panes()
        targets: list[tuple[str, object, int]] = []
        sos_segments = [s for s in segments if s.name == "SOS"]
        if not sos_segments:
            pane = TabPane("SOS", RichLog(id="info-sos-empty", highlight=True), id=self._dynamic_pane_id("sos-pane-empty"))
            tabs.add_pane(pane)
            self.query_one("#info-sos-empty", RichLog).write("No SOS segments found.")
            tabs.show_tab(pane.id)
            return targets
        first_pane_id = None
        for idx, seg in enumerate(sos_segments):
            key = f"sos-{seg.offset:08X}"
            label = f"SOS #{idx + 1}"
            root_id = self._dynamic_pane_id(f"{key}-root")
            self.sos_root_ids[key] = root_id
            pane = TabPane(label, self._build_sos_segment_pane(key, label, root_id), id=self._dynamic_pane_id(f"sos-pane-{idx+1}"))
            tabs.add_pane(pane)
            self._init_sos_detail_tabs(key)
            if first_pane_id is None:
                first_pane_id = pane.id
            targets.append((key, seg, idx))
        if first_pane_id is not None:
            tabs.show_tab(first_pane_id)
        return targets

    def _sos_query_one(self, key: str, selector: str, expect):
        root_id = self.sos_root_ids.get(key)
        if root_id:
            try:
                root = self.query_one(f"#{root_id}", Widget)
                self._sos_debug(f"sos query key={key} root={root_id} selector={selector} scoped=yes")
                return root.query_one(selector, expect)
            except QUERY_ERRORS:
                self._sos_debug(f"sos query key={key} root={root_id} selector={selector} scoped=miss")
                pass
        self._sos_debug(f"sos query key={key} selector={selector} scoped=no")
        return self.query_one(selector, expect)

    def _render_sos_segments(self, data: bytes, targets: list[tuple[str, object, int]]) -> None:
        for key, seg, scan_index in targets:
            self._render_sos_segment(data, seg, key, scan_index)

    def _render_sos_segment(self, data: bytes, seg, key: str, scan_index: int) -> None:
        self._sos_debug(f"sos render key={key} scan_index={scan_index} offset=0x{seg.offset:08X}")
        try:
            left_log = self._sos_query_one(key, f"#info-{key}-left", RichLog)
        except QUERY_ERRORS:
            self._sos_debug(f"sos render key={key} left=missing")
            return
        if seg.payload_offset is None or seg.payload_length is None:
            left_log.clear()
            left_log.write("SOS has no payload.")
            return
        payload = data[seg.payload_offset:seg.payload_offset + seg.payload_length]
        self.sos_segment_info[key] = (seg.offset, seg.total_length, seg.length_field or 0, seg.payload_offset)
        self.sos_original_payload[key] = payload
        self.sos_preview_payload[key] = payload
        self.sos_scan_index[key] = scan_index
        self._set_sos_editor_values(key, payload, seg.length_field or 0)
        self._apply_sos_mode_visibility(key)
        self._set_sos_dirty(key, False)
        self._render_sos_views(key, payload, seg.offset, seg.length_field or 0)

    def _render_sos_views(self, key: str, payload: bytes, offset: int, length_field: int) -> None:
        self._sos_debug(
            f"sos views key={key} payload_len={len(payload)} length=0x{length_field:04X} "
            f"highlight={self.sos_active_highlight.get(key)}"
        )
        try:
            left = self._sos_query_one(key, f"#info-{key}-left", RichLog)
        except QUERY_ERRORS:
            self._sos_debug(f"sos views key={key} left=missing")
            return
        info = decode_sos(payload) or {}
        comps = decode_sos_components(payload)
        scan_index = self.sos_scan_index.get(key, 0)
        left.clear()
        self._write_sos_left_panel(key, left, offset, length_field, payload, scan_index, comps)
        try:
            header = self._sos_query_one(key, f"#info-{key}-header", RichLog)
            components = self._sos_query_one(key, f"#info-{key}-components", RichLog)
            flow = self._sos_query_one(key, f"#info-{key}-flow", RichLog)
            links = self._sos_query_one(key, f"#info-{key}-links", RichLog)
        except QUERY_ERRORS:
            self._sos_debug(f"sos views key={key} right_logs=missing")
            return
        for log in (header, components, flow, links):
            log.clear()

        ns = int(info.get("components", "0") or 0)
        ahal = int(info.get("ahal", "0x00"), 16) if info.get("ahal") else 0
        header.write(f"Components in scan (Ns): {ns}")
        header.write(f"Ss={info.get('ss', '?')} Se={info.get('se', '?')} Ah={ahal >> 4} Al={ahal & 0x0F}")
        header.write(f"Mode: {'baseline-style' if info.get('ss') == '0' and info.get('se') == '63' and ahal == 0 else 'progressive/refinement or custom'}")

        if not comps:
            components.write("No SOS component selectors decoded.")
        for idx, comp in enumerate(comps, start=1):
            components.write(
                f"Component {idx}: id={comp['id']} ({self._component_name(comp['id'])}) "
                f"DC table={comp['dc_table_id']} AC table={comp['ac_table_id']}"
            )

        entropy_ranges = getattr(self, "info_entropy_ranges", []) or []
        rng = entropy_ranges[scan_index] if scan_index < len(entropy_ranges) else None
        if rng is None:
            flow.write("No matching entropy range found for this SOS.")
        else:
            flow.write(f"Scan {scan_index}: 0x{rng.start:08X}..0x{rng.end:08X} ({rng.end - rng.start} bytes)")
        if self.dri_segment_info and self.dri_preview_payload:
            flow.write(f"Restart interval active: {decode_dri(self.dri_preview_payload).get('restart_interval', '?')} MCUs")
        else:
            flow.write("Restart interval: none")

        sof_components = self._frame_components()
        if not sof_components:
            links.write("No SOF component mapping found.")
        else:
            links.write("SOS to SOF component links:")
            for comp in comps:
                match = next((item for item in sof_components if item["id"] == comp["id"]), None)
                if match is None:
                    links.write(f"  Component {comp['id']}: not found in SOF")
                    continue
                links.write(
                    f"  Component {comp['id']} ({self._component_name(comp['id'])}) "
                    f"sampling={match['h_sampling']}x{match['v_sampling']} QT={match['quant_table_id']}"
                )
        dht_tables = self._all_dht_tables()
        links.write("")
        links.write("Referenced Huffman tables:")
        for comp in comps:
            dc_ok = ("DC", comp["dc_table_id"]) in dht_tables
            ac_ok = ("AC", comp["ac_table_id"]) in dht_tables
            links.write(
                f"  Component {comp['id']}: DC {comp['dc_table_id']} ({'ok' if dc_ok else 'missing'}), "
                f"AC {comp['ac_table_id']} ({'ok' if ac_ok else 'missing'})"
            )

    def _write_sos_left_panel(
        self,
        key: str,
        log: RichLog,
        offset: int,
        length_field: int,
        payload: bytes,
        scan_index: int,
        comps: list[dict[str, int]],
    ) -> None:
        log.write(f"SOS at 0x{offset:08X} length=0x{length_field:04X} payload={len(payload)} scan_index={scan_index}")
        log.write("SOS selects scan components, Huffman tables, and spectral/approximation bounds.")
        log.write("Legend:")
        for label, style in [
            ("Marker", "bold yellow"),
            ("Length", "bold cyan"),
            ("Scan component count (Ns)", "bright_blue"),
            ("Component selector (Csj)", "magenta"),
            ("Table selector (Td/Ta)", "green"),
            ("Spectral/approximation bytes (Ss/Se/AhAl)", "bright_cyan"),
        ]:
            log.write(Text("  " + label, style=style))
        if comps:
            for idx, comp in enumerate(comps, start=1):
                log.write(
                    f"Component {idx}: id={comp['id']} ({self._component_name(comp['id'])}) "
                    f"DC table={comp['dc_table_id']} AC table={comp['ac_table_id']}"
                )
        segment_bytes = b"\xFF\xDA" + length_field.to_bytes(2, "big") + payload
        for line in self._hex_dump(segment_bytes, 0, len(segment_bytes), self._sos_ranges(key, payload)):
            log.write(line)

    def _sos_ranges(self, key: str, payload: bytes) -> list[tuple[int, int, str]]:
        if len(payload) < 1:
            ranges = [(0, 2, "bold yellow"), (2, 4, "bold cyan")]
            return self._with_sos_active_highlight(key, ranges)
        ns = payload[0]
        ranges = [(0, 2, "bold yellow"), (2, 4, "bold cyan"), (4, 5, "bright_blue")]
        cursor = 5
        for _ in range(ns):
            ranges.append((cursor, cursor + 1, "magenta"))
            ranges.append((cursor + 1, cursor + 2, "green"))
            cursor += 2
        ranges.append((cursor, cursor + 1, "bright_cyan"))
        ranges.append((cursor + 1, cursor + 2, "bright_cyan"))
        ranges.append((cursor + 2, cursor + 3, "bright_cyan"))
        return self._with_sos_active_highlight(key, ranges)

    def _with_sos_active_highlight(
        self,
        key: str,
        ranges: list[tuple[int, int, str]],
    ) -> list[tuple[int, int, str]]:
        highlight = self.sos_active_highlight.get(key)
        if highlight is None:
            return ranges
        start, end, style, _ = highlight
        return [*ranges, (start, end, style)]

    def _sos_key_from_id(self, widget_id: Optional[str], suffix: str) -> Optional[str]:
        if not widget_id or not widget_id.startswith("sos-") or not widget_id.endswith(suffix):
            return None
        return widget_id[: -len(suffix)]

    def _apply_sos_mode_visibility(self, key: str) -> None:
        try:
            adv = self._sos_query_one(key, f"#{key}-advanced-mode", Checkbox).value
            self._sos_query_one(key, f"#{key}-struct-edit", TextArea).display = not adv
            self._sos_query_one(key, f"#{key}-simple-title", Static).display = not adv
            self._sos_query_one(key, f"#{key}-raw-hex", TextArea).display = adv
            self._sos_query_one(key, f"#{key}-adv-title", Static).display = adv
            manual = self._sos_query_one(key, f"#{key}-manual-length", Checkbox).value
            self._sos_query_one(key, f"#{key}-length", Input).disabled = not manual
            self._sos_debug(f"sos visibility key={key} adv={adv} manual={manual}")
        except QUERY_ERRORS:
            self._sos_debug(f"sos visibility key={key} widgets=missing")
            return

    def _set_sos_editor_values(self, key: str, payload: bytes, length_field: int) -> None:
        info = decode_sos(payload) or {}
        comps = decode_sos_components(payload)
        ahal = int(info.get("ahal", "0x00"), 16) if info.get("ahal") else 0
        struct = {
            "ns": len(comps),
            "components": comps,
            "ss": int(info.get("ss", "0") or 0),
            "se": int(info.get("se", "63") or 63),
            "ah": ahal >> 4,
            "al": ahal & 0x0F,
        }
        try:
            self._sos_query_one(key, f"#{key}-raw-hex", TextArea).text = self._bytes_to_hex(payload)
            self._sos_query_one(key, f"#{key}-struct-edit", TextArea).text = pformat(struct, width=100, sort_dicts=False)
            self._sos_query_one(key, f"#{key}-length", Input).value = f"{length_field:04X}"
        except QUERY_ERRORS:
            return
        self._update_sos_active_highlight(key)

    def _update_sos_active_highlight(self, key: str) -> None:
        self.sos_active_highlight.pop(key, None)
        try:
            advanced = self._sos_query_one(key, f"#{key}-advanced-mode", Checkbox).value
            editor = self._sos_query_one(key, f"#{key}-raw-hex", TextArea) if advanced else self._sos_query_one(key, f"#{key}-struct-edit", TextArea)
        except Exception:
            self._sos_debug(f"sos highlight key={key} editor=missing")
            return
        try:
            payload = self._build_sos_payload(key)
        except Exception:
            payload = self.sos_preview_payload.get(key, b"")
        if advanced:
            highlight = self._sos_raw_highlight_from_editor(editor, payload)
        else:
            highlight = self._sos_highlight_from_editor(editor, payload)
        if highlight is not None:
            self.sos_active_highlight[key] = highlight
        self._sos_debug(f"sos highlight key={key} adv={advanced} cursor={getattr(editor, 'cursor_location', None)} result={highlight}")

    def _sos_raw_highlight_from_editor(
        self, editor: TextArea, payload: bytes
    ) -> Optional[tuple[int, int, str, str]]:
        line_no, col_no = self._text_area_cursor(editor)
        lines = editor.text.splitlines() or [editor.text]
        if not lines:
            return None
        line_no = max(0, min(line_no, len(lines) - 1))
        char_offset = sum(len(line) + 1 for line in lines[:line_no]) + min(col_no, len(lines[line_no]))
        nibble_count = sum(1 for ch in editor.text[:char_offset] if ch in "0123456789abcdefABCDEF")
        if nibble_count <= 0:
            byte_index = 0
        else:
            byte_index = min((nibble_count - 1) // 2, max(0, len(payload) - 1))
        return (4 + byte_index, 5 + byte_index, "bold black on grey70", "SOS raw byte")

    def _sos_highlight_from_editor(
        self, editor: TextArea, payload: bytes
    ) -> Optional[tuple[int, int, str, str]]:
        line_no, col_no = self._text_area_cursor(editor)
        lines = editor.text.splitlines() or [editor.text]
        if not lines:
            return None
        line_no = max(0, min(line_no, len(lines) - 1))
        line = lines[line_no]
        layout = self._sos_layout(payload)
        if layout is None:
            return None
        ns_start, components_start, scan_tail_start = layout
        span = self._value_span_in_line(line, "ns")
        if span is not None and span[0] <= col_no < span[1]:
            return (ns_start, ns_start + 1, "bold black on grey70", "SOS Ns")
        span = self._value_span_in_line(line, "ss")
        if span is not None and span[0] <= col_no < span[1]:
            return (scan_tail_start, scan_tail_start + 1, "bold black on grey70", "SOS Ss")
        span = self._value_span_in_line(line, "se")
        if span is not None and span[0] <= col_no < span[1]:
            return (scan_tail_start + 1, scan_tail_start + 2, "bold black on grey70", "SOS Se")
        for name in ("ah", "al"):
            span = self._value_span_in_line(line, name)
            if span is not None and span[0] <= col_no < span[1]:
                return (scan_tail_start + 2, scan_tail_start + 3, "bold black on grey70", "SOS Ah/Al")
        if "'id':" not in line and "'dc_table_id':" not in line and "'ac_table_id':" not in line:
            return None
        component_index = max(0, len(re.findall(r"\{'id'\s*:", "\n".join(lines[:line_no + 1]))) - 1)
        if component_index >= len(components_start):
            return None
        component_start = components_start[component_index]
        span = self._value_span_in_line(line, "id")
        if span is not None and span[0] <= col_no < span[1]:
            return (component_start, component_start + 1, "bold black on grey70", "SOS component id")
        for name in ("dc_table_id", "ac_table_id"):
            span = self._value_span_in_line(line, name)
            if span is not None and span[0] <= col_no < span[1]:
                return (component_start + 1, component_start + 2, "bold black on grey70", "SOS table selector")
        return None

    def _sos_layout(self, payload: bytes) -> Optional[tuple[int, list[int], int]]:
        if len(payload) < 4:
            return None
        ns = payload[0]
        if len(payload) < 1 + ns * 2 + 3:
            return None
        ns_start = 4
        components_start = [5 + idx * 2 for idx in range(ns)]
        scan_tail_start = 5 + ns * 2
        return ns_start, components_start, scan_tail_start

    def _serialize_sos_struct_to_payload(self, key: str) -> bytes:
        parsed = ast.literal_eval(self._sos_query_one(key, f"#{key}-struct-edit", TextArea).text)
        if not isinstance(parsed, dict):
            raise ValueError("SOS editor must be a dictionary.")
        if "ns" in parsed and int(parsed.get("ns", 0)) != len(list(parsed.get("components", []))):
            raise ValueError("SOS ns must match the number of components.")
        components = parsed.get("components", [])
        if not isinstance(components, list):
            raise ValueError("SOS components must be a list.")
        normalized = []
        for idx, comp in enumerate(components, start=1):
            if not isinstance(comp, dict):
                raise ValueError(f"SOS component {idx} must be a dictionary.")
            normalized.append({
                "id": int(comp.get("id", 0)),
                "dc_table_id": int(comp.get("dc_table_id", 0)),
                "ac_table_id": int(comp.get("ac_table_id", 0)),
            })
        return build_sos_payload(
            normalized,
            int(parsed.get("ss", 0)),
            int(parsed.get("se", 63)),
            int(parsed.get("ah", 0)),
            int(parsed.get("al", 0)),
        )

    def _deserialize_sos_payload_to_struct(self, key: str, payload: bytes) -> None:
        self._set_sos_editor_values(key, payload, len(payload) + 2)

    def _sync_sos_editor_for_mode(self, key: str) -> None:
        try:
            adv = self._sos_query_one(key, f"#{key}-advanced-mode", Checkbox).value
        except QUERY_ERRORS:
            self._sos_debug(f"sos sync key={key} adv=missing")
            return
        if adv:
            payload = self._serialize_sos_struct_to_payload(key)
            try:
                self._sos_query_one(key, f"#{key}-raw-hex", TextArea).text = self._bytes_to_hex(payload)
            except QUERY_ERRORS:
                self._sos_debug(f"sos sync key={key} adv=yes raw=missing")
                return
            self._sos_debug(f"sos sync key={key} adv=yes payload_len={len(payload)}")
            return
        try:
            payload = self._parse_hex(self._sos_query_one(key, f"#{key}-raw-hex", TextArea).text)
        except QUERY_ERRORS:
            self._sos_debug(f"sos sync key={key} adv=no raw=missing")
            return
        self._deserialize_sos_payload_to_struct(key, payload)
        self._sos_debug(f"sos sync key={key} adv=no payload_len={len(payload)}")

    def _build_sos_payload(self, key: str) -> bytes:
        if self._sos_query_one(key, f"#{key}-advanced-mode", Checkbox).value:
            return self._parse_hex(self._sos_query_one(key, f"#{key}-raw-hex", TextArea).text)
        try:
            return self._serialize_sos_struct_to_payload(key)
        except Exception as e:
            raise ValueError(f"invalid SOS editor content: {e}")

    def _set_sos_dirty(self, key: str, dirty: bool) -> None:
        self.sos_dirty[key] = dirty
        try:
            self._sos_query_one(key, f"#{key}-save", Button).disabled = not dirty
        except Exception:
            return

    def _sos_length_from_ui(self, key: str, payload: bytes) -> int:
        return self._length_from_ui_hex(
            manual_length_id=f"{key}-manual-length",
            length_id=f"{key}-length",
            payload=payload,
            example="000C",
        )

    def _refresh_sos_preview(self, key: str) -> None:
        self._update_sos_active_highlight(key)
        self._sos_debug(f"sos preview key={key} start")
        self._refresh_keyed_segment_preview(
            key=key,
            segment_info=self.sos_segment_info,
            err_id=f"{key}-error",
            build_payload=self._build_sos_payload,
            length_from_ui=self._sos_length_from_ui,
            set_preview=self._set_sos_preview_payload,
            render_views=self._render_sos_views,
            set_dirty=self._set_sos_dirty,
            recover_payload=self._recover_sos_preview_payload,
        )
        self._sos_debug(f"sos preview key={key} end payload_len={len(self.sos_preview_payload.get(key, b''))}")

    def _set_sos_preview_payload(self, key: str, payload: bytes) -> None:
        self.sos_preview_payload[key] = payload

    def _recover_sos_preview_payload(self, key: str, error: Exception) -> Tuple[bytes, Optional[str]]:
        if not self._sos_query_one(key, f"#{key}-advanced-mode", Checkbox).value:
            raise error
        payload = self._parse_hex_lenient(self._sos_query_one(key, f"#{key}-raw-hex", TextArea).text)
        return payload, f"Warning: {error}"

    def _sos_save_inputs(self, key: str) -> Tuple[str, bytes, int]:
        input_path = self.query_one("#input-path", Input).value.strip()
        if not input_path:
            raise ValueError("input path is required.")
        if key not in self.sos_segment_info:
            raise ValueError("SOS not loaded. Click Load Info first.")
        payload = self._build_sos_payload(key)
        return input_path, payload, self._sos_length_from_ui(key, payload)

    def _sos_write_file(self, key: str, input_path: str, payload: bytes, length_field: int):
        offset, total_len, _, _ = self.sos_segment_info[key]
        return self._write_segment_edit_file(
            input_path=input_path,
            offset=offset,
            total_len=total_len,
            payload=payload,
            length_field=length_field,
            suffix=f"_{key}_edit",
        )

    def _sos_save_log(self, key: str, out_path, payload: bytes, length_field: int) -> None:
        self._segment_save_log(
            log_id=f"info-{key}-left",
            out_path=out_path,
            payload=payload,
            length_field=length_field,
            manual_length_id=f"{key}-manual-length",
        )

    def _all_dht_tables(self) -> set[tuple[str, int]]:
        found: set[tuple[str, int]] = set()
        if not self.info_segments or not self.info_data:
            return found
        for seg in self.info_segments:
            if seg.name != "DHT" or seg.payload_offset is None or seg.payload_length is None:
                continue
            payload = self.info_data[seg.payload_offset:seg.payload_offset + seg.payload_length]
            for table in decode_dht_tables(payload):
                found.add((str(table["class"]), int(table["id"])))
        return found

    @on(Checkbox.Changed)
    def _on_sos_checkbox_changed(self, event: Checkbox.Changed) -> None:
        key = self._sos_key_from_id(event.checkbox.id, "-advanced-mode")
        if key:
            self._handle_sos_checkbox(key, "advanced", event.value)
            return
        key = self._sos_key_from_id(event.checkbox.id, "-manual-length")
        if not key:
            return
        self._handle_sos_checkbox(key, "manual-length", event.value)

    @on(Input.Changed)
    def _on_sos_input_changed(self, event: Input.Changed) -> None:
        self._sos_debug(f"sos input id={event.input.id} value={event.value}")
        key = self._sos_key_from_id(event.input.id, "-length")
        if not key:
            return
        self._set_sos_dirty(key, True)
        try:
            if self._sos_query_one(key, f"#{key}-manual-length", Checkbox).value:
                self._refresh_sos_preview(key)
        except QUERY_ERRORS:
            return

    @on(TextArea.Changed)
    def _on_sos_textarea_changed(self, event: TextArea.Changed) -> None:
        key = self._sos_key_from_id(event.text_area.id, "-struct-edit")
        if not key:
            key = self._sos_key_from_id(event.text_area.id, "-raw-hex")
        if not key:
            return
        role = "struct" if event.text_area.id.endswith("-struct-edit") else "raw"
        self._handle_sos_textarea_changed(key, role, event.text_area)

    @on(TextArea.SelectionChanged)
    def _on_sos_selection_changed(self, event: TextArea.SelectionChanged) -> None:
        key = self._sos_key_from_id(event.text_area.id, "-struct-edit")
        if not key:
            key = self._sos_key_from_id(event.text_area.id, "-raw-hex")
        if not key:
            return
        role = "struct" if event.text_area.id.endswith("-struct-edit") else "raw"
        self._handle_sos_textarea_selection_changed(key, role, event.text_area)

    @on(Button.Pressed)
    def _on_sos_save(self, event: Button.Pressed) -> None:
        key = self._sos_key_from_id(event.button.id, "-save")
        if not key:
            return
        self._handle_sos_save(key)

    def _handle_sos_checkbox(self, key: str, role: str, value: bool) -> None:
        self._sos_debug(f"sos checkbox key={key} role={role} value={value}")
        if role == "advanced":
            self._apply_sos_mode_visibility(key)
            try:
                self._sync_sos_editor_for_mode(key)
            except Exception:
                pass
            self._refresh_sos_preview(key)
            return
        if role != "manual-length":
            return
        self._apply_sos_mode_visibility(key)
        if not value and key in self.sos_preview_payload:
            payload = self.sos_preview_payload[key]
            self._sos_query_one(key, f"#{key}-length", Input).value = f"{len(payload) + 2:04X}"
        self._refresh_sos_preview(key)

    def _handle_sos_textarea_changed(self, key: str, role: str, editor: TextArea) -> None:
        self._sos_debug(
            f"sos textarea_changed key={key} role={role} cursor={getattr(editor, 'cursor_location', None)} "
            f"text_len={len(editor.text)}"
        )
        if role == "struct":
            self._update_sos_active_highlight(key)
        else:
            self.sos_active_highlight.pop(key, None)
        try:
            if not self._sos_query_one(key, f"#{key}-manual-length", Checkbox).value:
                try:
                    payload = self._build_sos_payload(key)
                except Exception:
                    self._set_sos_dirty(key, True)
                else:
                    self._sos_query_one(key, f"#{key}-length", Input).value = f"{len(payload) + 2:04X}"
            self._refresh_sos_preview(key)
        except QUERY_ERRORS:
            return

    def _handle_sos_textarea_selection_changed(self, key: str, role: str, editor: TextArea) -> None:
        self._sos_debug(
            f"sos selection_changed key={key} role={role} cursor={getattr(editor, 'cursor_location', None)}"
        )
        self._update_sos_active_highlight(key)
        try:
            if key in self.sos_segment_info and key in self.sos_preview_payload:
                offset, _, length_field, _ = self.sos_segment_info[key]
                self._render_sos_views(key, self.sos_preview_payload[key], offset, length_field)
        except QUERY_ERRORS:
            return

    def _handle_sos_save(self, key: str) -> None:
        self._sos_debug(f"sos save key={key}")
        err = self._sos_query_one(key, f"#{key}-error", Static)
        err.update("")
        try:
            input_path, payload, length_field = self._sos_save_inputs(key)
            out_path = self._sos_write_file(key, input_path, payload, length_field)
        except Exception as e:
            err.update(f"Error: {e}")
            return
        self._set_sos_dirty(key, False)
        self._sos_save_log(key, out_path, payload, length_field)

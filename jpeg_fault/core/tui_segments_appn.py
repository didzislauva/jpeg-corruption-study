from __future__ import annotations

import ast
from pathlib import Path
from pprint import pformat
from typing import Optional, Tuple

try:
    import piexif
except ImportError:  # pragma: no cover - optional dependency
    piexif = None

from textual import on
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    Label,
    RichLog,
    Select,
    Static,
    TabbedContent,
    TabPane,
    TextArea,
)
from rich.text import Text

from .jpeg_parse import decode_app0


class TuiSegmentsAppnMixin:
    def _add_appn_tab(self) -> None:
        tabs = self.query_one("#info-tabs", TabbedContent)
        tabs.add_pane(TabPane("APPn", self._build_appn_pane()))
        self._reset_appn_tabs([])

    def _build_appn_pane(self) -> Vertical:
        return Vertical(
            Static("APPn segments (APP0, APP1, ...)", classes="field"),
            TabbedContent(id="appn-tabs"),
            id="appn-panel",
        )

    def _build_appn_readonly_pane(self, title: str, log_id: str) -> VerticalScroll:
        return VerticalScroll(
            Static(f"{title} info (hex)", classes="field"),
            RichLog(id=log_id, highlight=True, classes="appn-info"),
        )

    def _build_app1_pane(self, key: str, title: str) -> Horizontal:
        return Horizontal(
            VerticalScroll(
                Static(f"{title} info (decoded + hex)", classes="field"),
                TabbedContent(id=f"{key}-tabs"),
                id=f"{key}-info",
            ),
            VerticalScroll(
                Static("Edit EXIF as Python literal (piexif dict).", classes="field"),
                Button("Save edited file", id=f"{key}-save", variant="success", disabled=True),
                Static("", id=f"{key}-error"),
                TabbedContent(id=f"{key}-edit-tabs"),
                id=f"{key}-edit",
            ),
            id=f"{key}-panel",
        )

    def _build_app2_pane(self, key: str, title: str) -> Horizontal:
        return Horizontal(
            VerticalScroll(
                Static(f"{title} info (decoded + hex)", classes="field"),
                TabbedContent(id=f"{key}-tabs"),
                id=f"{key}-info",
            ),
            VerticalScroll(
                TabbedContent(id=f"{key}-right-tabs"),
                id=f"{key}-right",
            ),
            id=f"{key}-panel",
        )

    @on(TextArea.Changed)
    def _on_app1_textarea_changed(self, event: TextArea.Changed) -> None:
        key = self._app1_key_from_id(event.text_area.id, "-header-hex")
        if key:
            self._on_app1_header_hex_changed(key)
            self._set_app1_dirty(key, True)
            return
        key = self._app1_key_from_id(event.text_area.id, "-ifd0-editor")
        if key:
            self._sync_ifd_editor_to_dict(key, "0th")
            self._set_app1_dirty(key, True)
            return
        key = self._app1_key_from_id(event.text_area.id, "-ifd1-editor")
        if key:
            self._sync_ifd_editor_to_dict(key, "1st")
            self._set_app1_dirty(key, True)
            return
        key = self._app1_key_from_id(event.text_area.id, "-dict-editor")
        if not key:
            return
        self._set_app1_dirty(key, True)

    @on(Button.Pressed)
    def _on_app1_save(self, event: Button.Pressed) -> None:
        key = self._app1_key_from_id(event.button.id, "-save")
        if not key:
            return
        err = self.query_one(f"#{key}-error", Static)
        err.update("")
        try:
            input_path, payload = self._app1_save_inputs(key)
        except Exception as e:
            err.update(f"Error: {e}")
            return
        out_path = self._app1_write_file(input_path, key, payload)
        log = self.query_one(f"#info-{key}", RichLog)
        log.write(f"Saved edited file: {out_path}")
        self._set_app1_dirty(key, False)

    @on(Select.Changed)
    def _on_app2_select_changed(self, event: Select.Changed) -> None:
        key = self._app2_key_from_id(event.select.id, "-desc-preset")
        if key:
            val = event.select.value
            self.query_one(f"#{key}-desc-input", Input).value = val or ""
            self._set_app2_dirty(key, True)
            return
        key = self._app2_key_from_id(event.select.id, "-cprt-preset")
        if key:
            val = event.select.value
            self.query_one(f"#{key}-cprt-input", Input).value = val or ""
            self._set_app2_dirty(key, True)
            return

    @on(Input.Changed)
    def _on_app2_input_changed(self, event: Input.Changed) -> None:
        key = self._app2_key_from_id(event.input.id, "-desc-input")
        if key:
            self._refresh_app2_preview(key)
            return
        key = self._app2_key_from_id(event.input.id, "-cprt-input")
        if key:
            self._refresh_app2_preview(key)
            return
        key = self._app2_key_from_id(event.input.id, "-dmnd-input")
        if key:
            self._refresh_app2_preview(key)
            return
        key = self._app2_key_from_id(event.input.id, "-dmdd-input")
        if key:
            self._refresh_app2_preview(key)
            return
        for suffix in [
            "-wtpt-input",
            "-bkpt-input",
            "-rxyz-input",
            "-gxyz-input",
            "-bxyz-input",
            "-rtrc-input",
            "-gtrc-input",
            "-btrc-input",
        ]:
            key = self._app2_key_from_id(event.input.id, suffix)
            if key:
                self._refresh_app2_preview(key)
                return
            return

    @on(Button.Pressed)
    def _on_app2_save(self, event: Button.Pressed) -> None:
        key = self._app2_key_from_id(event.button.id, "-save")
        if not key:
            return
        err = self.query_one(f"#{key}-error", Static)
        err.update("")
        try:
            input_path, payload = self._app2_save_inputs(key)
        except Exception as e:
            err.update(f"Error: {e}")
            return
        out_path = self._app2_write_file(input_path, key, payload)
        self.query_one(f"#info-{key}-raw", RichLog).write(f"Saved edited file: {out_path}")
        self._set_app2_dirty(key, False)

    def _reset_appn_tabs(self, segments) -> list[Tuple[str, object]]:
        """
        Rebuild APPn sub-tabs based on current segments and return log targets.
        """
        appn_tabs = self.query_one("#appn-tabs", TabbedContent)
        appn_tabs.clear_panes()
        first_pane_id = None

        self.app1_segment_info = {}
        self.app1_original_payload = {}
        self.app1_dirty = {}
        counts: dict[str, int] = {}
        targets: list[Tuple[str, object]] = []
        has_app0 = any(seg.name == "APP0" for seg in segments)
        if has_app0:
            pane = TabPane("APP0", self._build_app0_pane())
            appn_tabs.add_pane(pane)
            first_pane_id = pane.id
            self._apply_app0_mode_visibility()
        for seg in segments:
            if not seg.name.startswith("APP"):
                continue
            counts[seg.name] = counts.get(seg.name, 0) + 1
            if seg.name == "APP0" and counts[seg.name] == 1:
                continue
            label = seg.name if counts[seg.name] == 1 else f"{seg.name} #{counts[seg.name]}"
            if seg.name == "APP1":
                key = f"app1-{seg.offset:08X}"
                pane = TabPane(label, self._build_app1_pane(key, label))
                appn_tabs.add_pane(pane)
                if first_pane_id is None:
                    first_pane_id = pane.id
                self._init_app1_tabs(key)
                targets.append((key, seg))
            elif seg.name == "APP2":
                key = f"app2-{seg.offset:08X}"
                pane = TabPane(label, self._build_app2_pane(key, label))
                appn_tabs.add_pane(pane)
                if first_pane_id is None:
                    first_pane_id = pane.id
                self._init_app2_tabs(key)
                targets.append((key, seg))
            else:
                log_id = f"info-appn-{seg.offset}"
                pane = TabPane(label, self._build_appn_readonly_pane(label, log_id))
                appn_tabs.add_pane(pane)
                if first_pane_id is None:
                    first_pane_id = pane.id
                targets.append((log_id, seg))
        if first_pane_id is None:
            pane = TabPane("APPn", RichLog(id="info-appn-empty", highlight=True))
            appn_tabs.add_pane(pane)
            first_pane_id = pane.id
            self.query_one("#info-appn-empty", RichLog).write("No APPn segments found.")
        if first_pane_id is not None:
            appn_tabs.show_tab(first_pane_id)
        return targets

    def _render_appn_segments(self, data: bytes, targets: list[Tuple[str, object]]) -> None:
        for key, seg in targets:
            if key.startswith("app1-"):
                self._render_app1_segment(data, seg, key)
                continue
            if key.startswith("app2-"):
                self._render_app2_segment(data, seg, key)
                continue
            log = self.query_one(f"#{key}", RichLog)
            log.clear()
            self._render_appn_segment(data, seg, log)

    def _render_appn_segment(self, data: bytes, seg, log: RichLog) -> None:
        if seg.payload_offset is None or seg.payload_length is None:
            log.write(f"{seg.name} has no payload.")
            return
        log.write(
            f"{seg.name} at 0x{seg.offset:08X} length=0x{seg.length_field or 0:04X} payload={seg.payload_length}"
        )
        marker_start = seg.offset
        marker_end = seg.offset + 2
        length_start = seg.payload_offset - 2
        length_end = seg.payload_offset
        payload_start = seg.payload_offset
        payload_end = seg.payload_offset + seg.payload_length
        ranges = [
            (marker_start, marker_end, "bold yellow"),
            (length_start, length_end, "bold cyan"),
            (payload_start, payload_end, "green"),
        ]
        dump = self._hex_dump(data, seg.offset, seg.total_length, ranges)
        for line in dump:
            log.write(line)

    def _init_app1_tabs(self, key: str) -> None:
        tabs = self.query_one(f"#{key}-tabs", TabbedContent)
        tabs.clear_panes()
        tabs.add_pane(TabPane("Raw", RichLog(id=f"info-{key}-raw", highlight=True)))
        tabs.add_pane(TabPane("Hex", RichLog(id=f"info-{key}-hex", highlight=True)))
        tabs.add_pane(TabPane("Table", RichLog(id=f"info-{key}-table", highlight=True)))
        edit_tabs = self.query_one(f"#{key}-edit-tabs", TabbedContent)
        edit_tabs.clear_panes()
        edit_tabs.add_pane(
            TabPane(
                "Header",
                VerticalScroll(
                    Static("APP1 + TIFF header (hex)", classes="field"),
                    TextArea("", id=f"{key}-header-hex", soft_wrap=True, show_line_numbers=False),
                    Static("Decoded header", classes="field"),
                    RichLog(id=f"{key}-header", highlight=True),
                ),
            )
        )
        edit_tabs.add_pane(
            TabPane("IFD0", TextArea("", id=f"{key}-ifd0-editor", soft_wrap=True, show_line_numbers=True))
        )
        edit_tabs.add_pane(
            TabPane("IFD1", TextArea("", id=f"{key}-ifd1-editor", soft_wrap=True, show_line_numbers=True))
        )
        edit_tabs.add_pane(
            TabPane("Dict", TextArea("", id=f"{key}-dict-editor", soft_wrap=True, show_line_numbers=True))
        )

    def _init_app2_tabs(self, key: str) -> None:
        tabs = self.query_one(f"#{key}-tabs", TabbedContent)
        tabs.clear_panes()
        tabs.add_pane(TabPane("Raw", RichLog(id=f"info-{key}-raw", highlight=True)))
        tabs.add_pane(TabPane("Hex", RichLog(id=f"info-{key}-hex", highlight=True)))
        tabs.add_pane(TabPane("Table", RichLog(id=f"info-{key}-table", highlight=True)))
        right = self.query_one(f"#{key}-right-tabs", TabbedContent)
        right.clear_panes()
        right.add_pane(TabPane("Header", RichLog(id=f"{key}-header", highlight=True)))
        right.add_pane(TabPane("Tags", RichLog(id=f"{key}-tags", highlight=True)))
        right.add_pane(TabPane("Tag Table", RichLog(id=f"{key}-tag-table", highlight=True)))
        right.add_pane(
            TabPane(
                "Edit",
                Vertical(
                    Label("Profile description", classes="field"),
                    Select(
                        [
                            ("", ""),
                            ("sRGB IEC61966-2.1", "sRGB IEC61966-2.1"),
                            ("Adobe RGB (1998)", "Adobe RGB (1998)"),
                            ("Display P3", "Display P3"),
                            ("ProPhoto RGB", "ProPhoto RGB"),
                        ],
                        value="",
                        id=f"{key}-desc-preset",
                    ),
                    Input(value="", id=f"{key}-desc-input"),
                    Label("Copyright", classes="field"),
                    Select(
                        [
                            ("", ""),
                            ("Copyright (c)", "Copyright (c)"),
                            ("Copyright (c) Adobe Systems", "Copyright (c) Adobe Systems"),
                        ],
                        value="",
                        id=f"{key}-cprt-preset",
                    ),
                    Input(value="", id=f"{key}-cprt-input"),
                    Label("Device manufacturer", classes="field"),
                    Input(value="", id=f"{key}-dmnd-input"),
                    Label("Device model", classes="field"),
                    Input(value="", id=f"{key}-dmdd-input"),
                    Label("White point (XYZ)", classes="field"),
                    Input(value="", id=f"{key}-wtpt-input"),
                    Label("Black point (XYZ)", classes="field"),
                    Input(value="", id=f"{key}-bkpt-input"),
                    Label("Red/Green/Blue colorants (XYZ)", classes="field"),
                    Input(value="", id=f"{key}-rxyz-input"),
                    Input(value="", id=f"{key}-gxyz-input"),
                    Input(value="", id=f"{key}-bxyz-input"),
                    Label("TRC gamma (r,g,b)", classes="field"),
                    Input(value="", id=f"{key}-rtrc-input"),
                    Input(value="", id=f"{key}-gtrc-input"),
                    Input(value="", id=f"{key}-btrc-input"),
                    Button("Save ICC edited file", id=f"{key}-save", variant="success", disabled=True),
                    Static("", id=f"{key}-error"),
                ),
            )
        )

    def _render_app1_segment(self, data: bytes, seg, key: str) -> None:
        log_hex = self.query_one(f"#info-{key}-hex", RichLog)
        log_raw = self.query_one(f"#info-{key}-raw", RichLog)
        log_table = self.query_one(f"#info-{key}-table", RichLog)
        err = self.query_one(f"#{key}-error", Static)
        header = self.query_one(f"#{key}-header", RichLog)
        header_hex = self.query_one(f"#{key}-header-hex", TextArea)
        ifd0_editor = self.query_one(f"#{key}-ifd0-editor", TextArea)
        ifd1_editor = self.query_one(f"#{key}-ifd1-editor", TextArea)
        dict_editor = self.query_one(f"#{key}-dict-editor", TextArea)
        log_hex.clear()
        log_raw.clear()
        log_table.clear()
        header.clear()
        err.update("")
        header_hex.text = ""
        ifd0_editor.text = ""
        ifd1_editor.text = ""
        dict_editor.text = ""
        if seg.payload_offset is None or seg.payload_length is None:
            log_hex.write("APP1 has no payload.")
            self._set_app1_dirty(key, False)
            return
        self.app1_segment_info[key] = (seg.offset, seg.total_length, seg.length_field or 0, seg.payload_offset)
        payload = data[seg.payload_offset:seg.payload_offset + seg.payload_length]
        self.app1_original_payload[key] = payload
        self.app1_preview_payload[key] = payload
        header_hex.text = self._bytes_to_hex(payload[:14])
        if not payload.startswith(b"Exif\x00\x00"):
            log_hex.write("APP1 payload is not EXIF (missing Exif\\0\\0 header).")
            log_table.write("APP1 payload is not EXIF.")
            self._render_app1_hex(log_hex, data, seg, [])
            self._render_app1_raw_hex(log_raw, data, seg, self._app1_basic_ranges(seg))
            self._set_app1_dirty(key, False)
            return
        exif = self._parse_exif(payload, seg.payload_offset)
        if exif.get("error"):
            log_hex.write(f"EXIF decode error: {exif['error']}")
            log_table.write(f"EXIF decode error: {exif['error']}")
            self._render_app1_hex(log_hex, data, seg, [])
            self._render_app1_raw_hex(log_raw, data, seg, self._app1_basic_ranges(seg))
            self._set_app1_dirty(key, False)
            return
        self._write_app1_header(header, exif, seg)
        self._write_app1_exif_table(log_table, exif)
        ranges = self._app1_hex_ranges(seg, exif)
        preview_data = self._app1_preview_data(data, seg, self.app1_preview_payload[key])
        self._render_app1_hex_sections(log_hex, preview_data, seg, exif, ranges)
        self._render_app1_raw_hex(log_raw, preview_data, seg, ranges, exif)
        if piexif is None:
            log_hex.write("piexif is not installed; editor disabled.")
            header.write("piexif is not installed; editors disabled.")
        else:
            try:
                exif_dict = piexif.load(payload[6:])
                self.app1_exif_dict[key] = exif_dict
                dict_editor.text = self._exif_dict_literal(exif_dict)
                ifd0_editor.text = self._format_ifd_editor(exif_dict.get("0th", {}))
                ifd1_editor.text = self._format_ifd_editor(exif_dict.get("1st", {}))
            except Exception as e:
                err.update(f"Error: {e}")
        self._set_app1_dirty(key, False)

    def _render_app2_segment(self, data: bytes, seg, key: str) -> None:
        log_hex = self.query_one(f"#info-{key}-hex", RichLog)
        log_raw = self.query_one(f"#info-{key}-raw", RichLog)
        log_table = self.query_one(f"#info-{key}-table", RichLog)
        log_header = self.query_one(f"#{key}-header", RichLog)
        log_tags = self.query_one(f"#{key}-tags", RichLog)
        log_table2 = self.query_one(f"#{key}-tag-table", RichLog)
        err = self.query_one(f"#{key}-error", Static)
        desc_input = self.query_one(f"#{key}-desc-input", Input)
        cprt_input = self.query_one(f"#{key}-cprt-input", Input)
        log_hex.clear()
        log_raw.clear()
        log_table.clear()
        log_header.clear()
        log_tags.clear()
        log_table2.clear()
        err.update("")
        if seg.payload_offset is None or seg.payload_length is None:
            log_hex.write("APP2 has no payload.")
            return
        payload = data[seg.payload_offset:seg.payload_offset + seg.payload_length]
        self.app2_segment_info[key] = (seg.offset, seg.total_length, seg.length_field or 0, seg.payload_offset)
        self.app2_original_payload[key] = payload
        self.app2_preview_payload[key] = payload
        icc = self._parse_icc_profile(payload, seg.payload_offset)
        if icc.get("error"):
            log_hex.write(f"ICC decode error: {icc['error']}")
            self._render_app2_raw_hex(log_raw, data, seg)
            return
        self._write_icc_header(log_header, icc)
        self._write_icc_tags(log_tags, icc)
        self._write_icc_table(log_table, icc)
        self._write_icc_tag_table(log_table2, icc, payload)
        ranges = self._icc_hex_ranges(seg, icc)
        self._write_icc_hex_legend(log_hex)
        self._render_icc_hex_sections(log_hex, data, seg, icc, ranges)
        self._render_app2_raw_hex(log_raw, data, seg)
        tag_map = self._icc_tag_data_map(icc, payload)
        desc_text, desc_type = self._decode_icc_text_tag(tag_map.get("desc"))
        cprt_text, cprt_type = self._decode_icc_text_tag(tag_map.get("cprt"))
        desc_input.value = desc_text
        cprt_input.value = cprt_text
        self.query_one(f"#{key}-dmnd-input", Input).value = self._decode_icc_ascii(tag_map.get("dmnd"))
        self.query_one(f"#{key}-dmdd-input", Input).value = self._decode_icc_ascii(tag_map.get("dmdd"))
        self.query_one(f"#{key}-wtpt-input", Input).value = self._decode_icc_xyz(tag_map.get("wtpt"))
        self.query_one(f"#{key}-bkpt-input", Input).value = self._decode_icc_xyz(tag_map.get("bkpt"))
        self.query_one(f"#{key}-rxyz-input", Input).value = self._decode_icc_xyz(tag_map.get("rXYZ"))
        self.query_one(f"#{key}-gxyz-input", Input).value = self._decode_icc_xyz(tag_map.get("gXYZ"))
        self.query_one(f"#{key}-bxyz-input", Input).value = self._decode_icc_xyz(tag_map.get("bXYZ"))
        self.query_one(f"#{key}-rtrc-input", Input).value = self._decode_icc_gamma(tag_map.get("rTRC"))
        self.query_one(f"#{key}-gtrc-input", Input).value = self._decode_icc_gamma(tag_map.get("gTRC"))
        self.query_one(f"#{key}-btrc-input", Input).value = self._decode_icc_gamma(tag_map.get("bTRC"))
        self.app2_tag_types[key] = {"desc": desc_type, "cprt": cprt_type}
        self._set_app2_dirty(key, False)

    def _render_app1_hex(self, log: RichLog, data: bytes, seg, ranges) -> None:
        marker_start = seg.offset
        marker_end = seg.offset + 2
        length_start = seg.payload_offset - 2
        length_end = seg.payload_offset
        payload_start = seg.payload_offset
        payload_end = seg.payload_offset + seg.payload_length
        base_ranges = [
            (marker_start, marker_end, "bold yellow"),
            (length_start, length_end, "bold cyan"),
            (payload_start, payload_end, "green"),
        ]
        for line in self._hex_dump(data, seg.offset, seg.total_length, ranges + base_ranges):
            log.write(line)

    def _render_app1_raw_hex(
        self, log: RichLog, data: bytes, seg, ranges: list[Tuple[int, int, str]], exif: Optional[dict] = None
    ) -> None:
        self._write_header_legend(log)
        if exif:
            self._write_ifd0_legend(log)
        for line in self._hex_dump(data, seg.offset, seg.total_length, ranges):
            log.write(line)
        log.scroll_to(0, animate=False)

    def _render_app2_raw_hex(self, log: RichLog, data: bytes, seg) -> None:
        for line in self._hex_dump(data, seg.offset, seg.total_length, []):
            log.write(line)
        log.scroll_to(0, animate=False)

    def _render_app1_hex_sections(self, log: RichLog, data: bytes, seg, exif: dict, ranges) -> None:
        payload_start = seg.payload_offset
        payload_end = seg.payload_offset + seg.payload_length
        self._write_header_legend(log)
        self._write_hex_section(
            log, "Marker + Length + Exif/TIFF header", data, seg.offset, payload_start + 14, ranges, seg
        )
        ifd0 = next((i for i in exif["ifds"] if i["name"] == "IFD0"), None)
        if ifd0:
            self._write_ifd0_legend(log)
            self._write_ifd_sections(log, data, ifd0, ranges, seg)
        exif_ifd = next((i for i in exif["ifds"] if i["name"] == "ExifIFD"), None)
        if exif_ifd:
            self._write_ifd0_legend(log)
            self._write_ifd_sections(log, data, exif_ifd, ranges, seg)
        gps_ifd = next((i for i in exif["ifds"] if i["name"] == "GPSIFD"), None)
        if gps_ifd:
            self._write_ifd0_legend(log)
            self._write_ifd_sections(log, data, gps_ifd, ranges, seg)
        ifd1 = next((i for i in exif["ifds"] if i["name"] == "IFD1"), None)
        if ifd1:
            self._write_ifd0_legend(log)
            self._write_ifd_sections(log, data, ifd1, ranges, seg)
        remaining = [(payload_start + 14, payload_end)]
        for ifd in [ifd0, exif_ifd, gps_ifd, ifd1]:
            if not ifd:
                continue
            self._subtract_section(remaining, ifd["offset"], ifd["offset"] + 2 + ifd["count"] * 12 + 4)
            for entry in ifd["entries"]:
                if entry["value_len"] <= 4:
                    continue
                self._subtract_section(remaining, entry["value_offset"], entry["value_offset"] + entry["value_len"])
        for start, end in remaining:
            if end > start:
                self._write_hex_section(log, "Other EXIF bytes", data, start, end, ranges, seg)

    def _write_ifd_sections(self, log: RichLog, data: bytes, ifd: dict, ranges, seg) -> None:
        table_start = ifd["offset"]
        table_end = table_start + 2 + ifd["count"] * 12 + 4
        if ifd["name"] == "IFD0":
            self._write_ifd0_entry_sections(log, data, ifd, ranges, seg)
        else:
            self._write_hex_section(log, f"{ifd['name']} table", data, table_start, table_end, ranges, seg)
        for entry in ifd["entries"]:
            if entry["value_len"] <= 4:
                continue
            start = entry["value_offset"]
            end = start + entry["value_len"]
            self._write_hex_section(log, f"{ifd['name']} value @0x{start:08X}", data, start, end, ranges, seg)

    def _write_ifd0_entry_sections(self, log: RichLog, data: bytes, ifd: dict, ranges, seg) -> None:
        table_start = ifd["offset"]
        log.write(f"{ifd['name']} table (split fields)")
        self._write_hex_section(log, "IFD0 entry count", data, table_start, table_start + 2, ranges, seg)
        for idx, entry in enumerate(ifd["entries"]):
            e = entry["entry_offset"]
            tag_name = ""
            if piexif is not None:
                tag_info = piexif.TAGS.get("0th", {}).get(entry["tag"], {})
                tag_name = tag_info.get("name", "")
            tag_label = f" ({tag_name})" if tag_name else ""
            log.write(f"IFD0 entry {idx} tag=0x{entry['tag']:04X}{tag_label}")
            self._write_hex_section(log, "  entry bytes", data, e, e + 12, ranges, seg)
            self._write_ifd_entry_explanation(log, entry, ifd)
        end = table_start + 2 + ifd["count"] * 12
        self._write_hex_section(log, "IFD0 next IFD offset", data, end, end + 4, ranges, seg)
        self._write_next_ifd_explanation(log, ifd)

    def _write_ifd_entry_explanation(self, log: RichLog, entry: dict, ifd: dict) -> None:
        if entry["value_len"] <= 4:
            return
        rel = entry["value_offset"] - ifd["tiff_base"]
        log.write(
            f"    value offset (TIFF-rel)=0x{rel:08X} abs=0x{entry['value_offset']:08X} "
            f"len={entry['value_len']} bytes"
        )

    def _write_next_ifd_explanation(self, log: RichLog, ifd: dict) -> None:
        if not ifd.get("next_offset"):
            log.write("    next IFD offset = 0x00000000 (no IFD1)")
            return
        abs_off = ifd["tiff_base"] + ifd["next_offset"]
        log.write(
            f"    next IFD offset (TIFF-rel)=0x{ifd['next_offset']:08X} abs=0x{abs_off:08X}"
        )

    def _parse_icc_profile(self, payload: bytes, payload_offset: int) -> dict:
        if not payload.startswith(b"ICC_PROFILE\x00"):
            return {"error": "missing ICC_PROFILE header"}
        if len(payload) < 14:
            return {"error": "truncated ICC header"}
        seq = payload[12]
        total = payload[13]
        icc = payload[14:]
        icc_start = payload_offset + 14
        if seq != 1 or total != 1:
            return {"error": f"multi-part ICC not supported (seq {seq}/{total})"}
        if len(icc) < 128:
            return {"error": "truncated ICC profile"}
        header = self._parse_icc_header(icc)
        tags = self._parse_icc_tags(icc)
        return {
            "error": None,
            "seq": seq,
            "total": total,
            "icc_start": icc_start,
            "icc_len": len(icc),
            "tag_count": len(tags),
            "header": header,
            "tags": tags,
        }

    def _parse_icc_header(self, icc: bytes) -> dict:
        return {
            "size": self._icc_u32(icc[0:4]),
            "cmm": icc[4:8].decode(errors="replace"),
            "version": self._icc_u32(icc[8:12]),
            "device_class": icc[12:16].decode(errors="replace"),
            "color_space": icc[16:20].decode(errors="replace"),
            "pcs": icc[20:24].decode(errors="replace"),
            "date": self._icc_date(icc[24:36]),
            "magic": icc[36:40].decode(errors="replace"),
        }

    def _parse_icc_tags(self, icc: bytes) -> list[dict]:
        if len(icc) < 132:
            return []
        count = self._icc_u32(icc[128:132])
        tags = []
        off = 132
        for _ in range(count):
            if off + 12 > len(icc):
                break
            sig = icc[off:off + 4].decode(errors="replace")
            tag_off = self._icc_u32(icc[off + 4:off + 8])
            size = self._icc_u32(icc[off + 8:off + 12])
            tags.append({"sig": sig, "offset": tag_off, "size": size})
            off += 12
        return tags

    def _icc_tag_data_map(self, icc: dict, payload: bytes) -> dict[str, bytes]:
        icc_start = icc["icc_start"]
        icc_bytes = payload[14:]
        out: dict[str, bytes] = {}
        for t in icc["tags"]:
            start = t["offset"]
            end = start + t["size"]
            if end <= len(icc_bytes):
                out[t["sig"]] = icc_bytes[start:end]
        return out

    def _decode_icc_text_tag(self, data: Optional[bytes]) -> tuple[str, str]:
        if not data or len(data) < 8:
            return "", ""
        tag_type = data[0:4].decode(errors="replace")
        if tag_type == "text":
            return data[8:].split(b"\x00", 1)[0].decode(errors="replace"), "text"
        if tag_type == "desc":
            if len(data) < 12:
                return "", "desc"
            count = self._icc_u32(data[8:12])
            text = data[12:12 + max(0, count - 1)]
            return text.decode(errors="replace"), "desc"
        if tag_type == "mluc":
            if len(data) < 16:
                return "", "mluc"
            count = self._icc_u32(data[8:12])
            rec_size = self._icc_u32(data[12:16])
            if count < 1 or len(data) < 16 + rec_size:
                return "", "mluc"
            rec = data[16:16 + rec_size]
            length = self._icc_u32(rec[4:8])
            offset = self._icc_u32(rec[8:12])
            start = offset
            end = start + length
            if end <= len(data):
                return data[start:end].decode("utf-16be", errors="replace"), "mluc"
            return "", "mluc"
        return "", tag_type

    def _decode_icc_ascii(self, data: Optional[bytes]) -> str:
        if not data or len(data) < 8:
            return ""
        tag_type = data[0:4].decode(errors="replace")
        if tag_type == "text":
            return data[8:].split(b"\x00", 1)[0].decode(errors="replace")
        return ""

    def _decode_icc_xyz(self, data: Optional[bytes]) -> str:
        if not data or len(data) < 20:
            return ""
        if data[0:4] != b"XYZ ":
            return ""
        x = self._icc_s15fixed16(data[8:12])
        y = self._icc_s15fixed16(data[12:16])
        z = self._icc_s15fixed16(data[16:20])
        return f"{x:.4f},{y:.4f},{z:.4f}"

    def _decode_icc_gamma(self, data: Optional[bytes]) -> str:
        if not data or len(data) < 14:
            return ""
        if data[0:4] != b"curv":
            return ""
        count = self._icc_u32(data[8:12])
        if count != 1:
            return ""
        gamma = int.from_bytes(data[12:14], "big") / 256.0
        return f"{gamma:.4f}"

    def _icc_s15fixed16(self, data: bytes) -> float:
        if len(data) < 4:
            return 0.0
        val = int.from_bytes(data, "big", signed=True)
        return val / 65536.0

    def _build_icc_text_tag(self, text: str, tag_type: str) -> bytes:
        if tag_type == "mluc":
            encoded = text.encode("utf-16be")
            header = b"mluc" + b"\x00\x00\x00\x00"
            header += (1).to_bytes(4, "big") + (12).to_bytes(4, "big")
            record = b"enUS" + len(encoded).to_bytes(4, "big") + (len(header) + 12).to_bytes(4, "big")
            return header + record + encoded
        if tag_type == "desc":
            encoded = text.encode(errors="replace") + b"\x00"
            header = b"desc" + b"\x00\x00\x00\x00" + len(encoded).to_bytes(4, "big")
            return header + encoded
        # default to 'text'
        encoded = text.encode(errors="replace")
        return b"text" + b"\x00\x00\x00\x00" + encoded

    def _build_icc_xyz_tag(self, text: str) -> bytes:
        parts = [p.strip() for p in text.split(",") if p.strip()]
        if len(parts) != 3:
            raise ValueError("XYZ must be three comma-separated floats.")
        vals = [float(p) for p in parts]
        out = bytearray()
        out.extend(b"XYZ ")
        out.extend(b"\x00\x00\x00\x00")
        for v in vals:
            fixed = int(round(v * 65536.0))
            out.extend(fixed.to_bytes(4, "big", signed=True))
        return bytes(out)

    def _build_icc_gamma_tag(self, text: str) -> bytes:
        gamma = float(text)
        val = int(round(gamma * 256.0))
        out = bytearray()
        out.extend(b"curv")
        out.extend(b"\x00\x00\x00\x00")
        out.extend((1).to_bytes(4, "big"))
        out.extend(val.to_bytes(2, "big"))
        return bytes(out)

    def _icc_u32(self, data: bytes) -> int:
        return int.from_bytes(data, "big")

    def _icc_u16(self, data: bytes) -> int:
        return int.from_bytes(data, "big")

    def _icc_date(self, data: bytes) -> str:
        if len(data) < 12:
            return ""
        y = self._icc_u16(data[0:2])
        mo = self._icc_u16(data[2:4])
        d = self._icc_u16(data[4:6])
        h = self._icc_u16(data[6:8])
        mi = self._icc_u16(data[8:10])
        s = self._icc_u16(data[10:12])
        return f"{y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{s:02d}"

    def _write_icc_header(self, log: RichLog, icc: dict) -> None:
        h = icc["header"]
        log.write(f"ICC profile size: {h['size']} bytes")
        log.write(f"CMM: {h['cmm']}")
        log.write(f"Version: 0x{h['version']:08X}")
        log.write(f"Device class: {h['device_class']}")
        log.write(f"Color space: {h['color_space']}")
        log.write(f"PCS: {h['pcs']}")
        log.write(f"Date: {h['date']}")
        log.write(f"Magic: {h['magic']}")

    def _write_icc_tags(self, log: RichLog, icc: dict) -> None:
        tags = icc["tags"]
        if not tags:
            log.write("No ICC tags.")
            return
        for t in tags:
            log.write(f"{t['sig']} off=0x{t['offset']:08X} size={t['size']}")

    def _write_icc_tag_table(self, log: RichLog, icc: dict, payload: bytes) -> None:
        if not icc["tags"]:
            log.write("No ICC tags.")
            return
        icc_start = icc["icc_start"]
        icc_bytes = payload[14:]
        for t in icc["tags"]:
            abs_off = icc_start + t["offset"]
            tag_type = ""
            if t["offset"] + 4 <= len(icc_bytes):
                tag_type = icc_bytes[t["offset"]:t["offset"] + 4].decode(errors="replace")
            log.write(
                f"{t['sig']} type={tag_type} rel=0x{t['offset']:08X} abs=0x{abs_off:08X} size={t['size']}"
            )

    def _write_icc_table(self, log: RichLog, icc: dict) -> None:
        log.write(f"ICC start: 0x{icc['icc_start']:08X} len={icc['icc_len']}")
        log.write(f"Tag count: {len(icc['tags'])}")
        for t in icc["tags"]:
            abs_off = icc["icc_start"] + t["offset"]
            log.write(f"{t['sig']} rel=0x{t['offset']:08X} abs=0x{abs_off:08X} size={t['size']}")

    def _icc_hex_ranges(self, seg, icc: dict) -> list[Tuple[int, int, str]]:
        ranges: list[Tuple[int, int, str]] = []
        icc_start = icc["icc_start"]
        ranges.append((icc_start, icc_start + 128, "bright_blue"))
        table_start = icc_start + 128
        table_end = table_start + 4 + len(icc["tags"]) * 12
        ranges.append((table_start, table_end, "bright_cyan"))
        for t in icc["tags"]:
            start = icc_start + t["offset"]
            end = start + t["size"]
            ranges.append((start, end, "bright_magenta"))
        return ranges

    def _render_icc_hex_sections(self, log: RichLog, data: bytes, seg, icc: dict, ranges) -> None:
        icc_start = icc["icc_start"]
        icc_end = icc_start + icc["icc_len"]
        self._write_hex_section(log, "ICC header", data, icc_start, icc_start + 128, ranges, seg)
        table_start = icc_start + 128
        table_end = table_start + 4 + len(icc["tags"]) * 12
        self._write_hex_section(log, "Tag table", data, table_start, table_end, ranges, seg)
        for t in icc["tags"]:
            start = icc_start + t["offset"]
            end = start + t["size"]
            self._write_hex_section(log, f"Tag {t['sig']}", data, start, end, ranges, seg)
        if icc_end > table_end:
            self._write_hex_section(log, "ICC data", data, table_end, icc_end, ranges, seg)

    def _write_hex_section(
        self, log: RichLog, title: str, data: bytes, start: int, end: int, ranges, seg
    ) -> None:
        start = max(seg.offset, start)
        end = min(seg.offset + seg.total_length, end)
        if end <= start:
            return
        log.write(f"{title} (0x{start:08X}..0x{end - 1:08X})")
        for line in self._hex_dump(data, start, end - start, ranges):
            log.write(line)

    def _write_header_legend(self, log: RichLog) -> None:
        log.write("Legend (Header):")
        log.write(Text("  Marker", style="bold yellow"))
        log.write(Text("  Length", style="bold cyan"))
        log.write(Text("  Exif header", style="magenta"))
        log.write(Text("  TIFF header", style="bright_blue"))

    def _write_ifd0_legend(self, log: RichLog) -> None:
        log.write("Legend (IFD table):")
        log.write(Text("  Entry count", style="bright_white"))
        log.write(Text("  Tag", style="bright_green"))
        log.write(Text("  Type", style="bright_blue"))
        log.write(Text("  Count", style="bright_cyan"))
        log.write(Text("  Value/Offset", style="bright_yellow"))
        log.write(Text("  Next IFD offset", style="bright_red"))

    def _write_icc_hex_legend(self, log: RichLog) -> None:
        log.write("Legend (ICC):")
        log.write(Text("  ICC header", style="bright_blue"))
        log.write(Text("  Tag table", style="bright_cyan"))
        log.write(Text("  Tag data", style="bright_magenta"))

    def _subtract_section(self, sections: list[Tuple[int, int]], start: int, end: int) -> None:
        if end <= start:
            return
        out: list[Tuple[int, int]] = []
        for s, e in sections:
            if end <= s or start >= e:
                out.append((s, e))
                continue
            if start > s:
                out.append((s, start))
            if end < e:
                out.append((end, e))
        sections[:] = out

    def _write_app1_exif_table(self, log: RichLog, exif: dict) -> None:
        log.write(f"Byte order: {exif['endian']}")
        log.write(f"TIFF header @0x{exif['tiff_base']:08X}")
        for ifd in exif["ifds"]:
            log.write(f"{ifd['name']} @0x{ifd['offset']:08X} entries={ifd['count']}")
            for entry in ifd["entries"]:
                log.write(
                    f"  tag=0x{entry['tag']:04X} type={entry['type_name']} count={entry['count']} "
                    f"val_len={entry['value_len']} val_off=0x{entry['value_offset']:08X} "
                    f"val={entry['preview']}"
                )

    def _format_exif_value(self, value) -> str:
        if isinstance(value, bytes):
            if len(value) <= 64:
                try:
                    text = value.decode("utf-8")
                    return f"{text!r}"
                except Exception:
                    return "0x" + value.hex()
            return f"bytes[{len(value)}]"
        if isinstance(value, tuple):
            return repr(value)
        return str(value)

    def _exif_dict_literal(self, exif_dict) -> str:
        return repr(exif_dict)

    def _set_app1_dirty(self, key: str, dirty: bool) -> None:
        self.app1_dirty[key] = dirty
        self.query_one(f"#{key}-save", Button).disabled = not dirty

    def _app2_key_from_id(self, widget_id: Optional[str], suffix: str) -> Optional[str]:
        if not widget_id or not widget_id.startswith("app2-") or not widget_id.endswith(suffix):
            return None
        return widget_id[: -len(suffix)]

    def _set_app2_dirty(self, key: str, dirty: bool) -> None:
        self.app2_dirty[key] = dirty
        try:
            self.query_one(f"#{key}-save", Button).disabled = not dirty
        except Exception:
            return

    def _write_app1_header(self, log: RichLog, exif: dict, seg) -> None:
        log.write(
            f"APP1 EXIF at 0x{seg.offset:08X} length=0x{seg.length_field or 0:04X} payload={seg.payload_length}"
        )
        log.write(f"Endian: {'II' if exif['endian'] == '<' else 'MM'}")
        log.write(f"TIFF base: 0x{exif['tiff_base']:08X}")
        ifd0 = next((i for i in exif["ifds"] if i["name"] == "IFD0"), None)
        if ifd0:
            log.write(f"IFD0 offset: 0x{ifd0['offset']:08X}")
        ifd1 = next((i for i in exif["ifds"] if i["name"] == "IFD1"), None)
        if ifd1:
            log.write(f"IFD1 offset: 0x{ifd1['offset']:08X}")

    def _format_ifd_editor(self, ifd_dict: dict) -> str:
        lines = []
        for tag in sorted(ifd_dict.keys()):
            lines.append(f"0x{tag:04X} = {ifd_dict[tag]!r}")
        return "\n".join(lines)

    def _parse_ifd_editor(self, text: str) -> dict:
        out: dict[int, object] = {}
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ValueError(f"Invalid line (missing '='): {line}")
            left, right = line.split("=", 1)
            left = left.strip()
            right = right.strip()
            try:
                tag = int(left, 16) if left.lower().startswith("0x") else int(left)
            except ValueError as e:
                raise ValueError(f"Invalid tag '{left}': {e}")
            try:
                value = ast.literal_eval(right)
            except Exception:
                value = right
            out[tag] = value
        return out

    def _sync_ifd_editor_to_dict(self, key: str, ifd_name: str) -> None:
        if self._app1_syncing:
            return
        err = self.query_one(f"#{key}-error", Static)
        editor = self.query_one(f"#{key}-{'ifd0' if ifd_name == '0th' else 'ifd1'}-editor", TextArea)
        try:
            ifd_dict = self._parse_ifd_editor(editor.text)
        except Exception as e:
            err.update(f"Error: {e}")
            return
        err.update("")
        base = self.app1_exif_dict.get(key, {})
        base[ifd_name] = ifd_dict
        for k in ["0th", "Exif", "GPS", "1st", "Interop"]:
            base.setdefault(k, {})
        base.setdefault("thumbnail", b"")
        self.app1_exif_dict[key] = base
        self._app1_syncing = True
        try:
            self.query_one(f"#{key}-dict-editor", TextArea).text = self._exif_dict_literal(base)
        finally:
            self._app1_syncing = False

    def _parse_exif(self, payload: bytes, payload_offset: int) -> dict:
        if not payload.startswith(b"Exif\x00\x00"):
            return {"error": "missing Exif header"}
        tiff = payload[6:]
        tiff_base = payload_offset + 6
        if len(tiff) < 8:
            return {"error": "truncated TIFF header"}
        endian = self._exif_endian(tiff[:2])
        if endian is None:
            return {"error": "invalid TIFF byte order"}
        magic = self._exif_u16(tiff[2:4], endian)
        if magic != 0x002A:
            return {"error": f"bad TIFF magic 0x{magic:04X}"}
        ifd0_off = self._exif_u32(tiff[4:8], endian)
        ifds = self._collect_exif_ifds(tiff, tiff_base, endian, ifd0_off)
        return {"endian": endian, "tiff_base": tiff_base, "ifds": ifds, "error": None}

    def _exif_endian(self, data: bytes) -> Optional[str]:
        if data == b"II":
            return "<"
        if data == b"MM":
            return ">"
        return None

    def _exif_u16(self, data: bytes, endian: str) -> int:
        return int.from_bytes(data, "little" if endian == "<" else "big")

    def _exif_u32(self, data: bytes, endian: str) -> int:
        return int.from_bytes(data, "little" if endian == "<" else "big")

    def _collect_exif_ifds(self, tiff: bytes, tiff_base: int, endian: str, ifd0_off: int) -> list[dict]:
        ifds: list[dict] = []
        seen: set[int] = set()
        ifd0 = self._parse_ifd("IFD0", tiff, tiff_base, endian, ifd0_off, seen)
        if ifd0:
            ifds.append(ifd0)
            self._append_pointer_ifd(ifds, ifd0, "ExifIFD", 0x8769, tiff, tiff_base, endian, seen)
            self._append_pointer_ifd(ifds, ifd0, "GPSIFD", 0x8825, tiff, tiff_base, endian, seen)
        if ifd0 and ifd0["next_offset"]:
            ifd1 = self._parse_ifd("IFD1", tiff, tiff_base, endian, ifd0["next_offset"], seen)
            if ifd1:
                ifds.append(ifd1)
        interop = next((i for i in ifds if i["name"] == "ExifIFD"), None)
        if interop:
            self._append_pointer_ifd(ifds, interop, "InteropIFD", 0xA005, tiff, tiff_base, endian, seen)
        return ifds

    def _append_pointer_ifd(
        self, ifds: list[dict], parent: dict, name: str, tag_id: int, tiff, tiff_base, endian, seen
    ) -> None:
        entry = next((e for e in parent["entries"] if e["tag"] == tag_id), None)
        if not entry:
            return
        ifd = self._parse_ifd(name, tiff, tiff_base, endian, entry["value_offset"], seen)
        if ifd:
            ifds.append(ifd)

    def _parse_ifd(
        self, name: str, tiff: bytes, tiff_base: int, endian: str, offset: int, seen: set[int]
    ) -> Optional[dict]:
        if offset == 0 or offset in seen:
            return None
        if offset + 2 > len(tiff):
            return None
        seen.add(offset)
        count = self._exif_u16(tiff[offset:offset + 2], endian)
        entries = []
        entries_start = offset + 2
        entries_end = entries_start + count * 12
        if entries_end + 4 > len(tiff):
            return None
        for i in range(count):
            e_off = entries_start + i * 12
            entry = self._parse_ifd_entry(tiff, tiff_base, endian, e_off)
            if entry:
                entries.append(entry)
        next_offset = self._exif_u32(tiff[entries_end:entries_end + 4], endian)
        return {
            "name": name,
            "offset": tiff_base + offset,
            "tiff_base": tiff_base,
            "count": count,
            "entries": entries,
            "next_offset": next_offset,
        }

    def _parse_ifd_entry(self, tiff: bytes, tiff_base: int, endian: str, e_off: int) -> Optional[dict]:
        if e_off + 12 > len(tiff):
            return None
        tag = self._exif_u16(tiff[e_off:e_off + 2], endian)
        typ = self._exif_u16(tiff[e_off + 2:e_off + 4], endian)
        count = self._exif_u32(tiff[e_off + 4:e_off + 8], endian)
        value_or_off = self._exif_u32(tiff[e_off + 8:e_off + 12], endian)
        size = self._exif_type_size(typ)
        value_len = count * size if size else 0
        if value_len <= 4:
            value_offset = tiff_base + e_off + 8
        else:
            value_offset = tiff_base + value_or_off
        preview = self._exif_value_preview(tiff, tiff_base, value_offset, value_len, typ, endian)
        return {
            "tag": tag,
            "type": typ,
            "type_name": self._exif_type_name(typ),
            "count": count,
            "value_len": value_len,
            "value_offset": value_offset,
            "preview": preview,
            "entry_offset": tiff_base + e_off,
        }

    def _exif_type_size(self, typ: int) -> int:
        return {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}.get(typ, 0)

    def _exif_type_name(self, typ: int) -> str:
        return {
            1: "BYTE",
            2: "ASCII",
            3: "SHORT",
            4: "LONG",
            5: "RATIONAL",
            7: "UNDEFINED",
            9: "SLONG",
            10: "SRATIONAL",
        }.get(typ, f"TYPE{typ}")

    def _exif_value_preview(
        self, tiff: bytes, tiff_base: int, value_offset: int, value_len: int, typ: int, endian: str
    ) -> str:
        if value_len == 0:
            return ""
        rel = value_offset - tiff_base
        if rel < 0 or rel + value_len > len(tiff):
            return "out-of-bounds"
        raw = tiff[rel:rel + value_len]
        if typ == 2:
            return raw.split(b"\x00", 1)[0].decode(errors="replace")
        if value_len <= 16:
            return "0x" + raw.hex()
        return f"bytes[{value_len}]"

    def _app1_hex_ranges(self, seg, exif: dict) -> list[Tuple[int, int, str]]:
        ranges: list[Tuple[int, int, str]] = []
        payload_start = seg.payload_offset
        ranges.append((seg.offset, seg.offset + 2, "bold yellow"))
        ranges.append((seg.payload_offset - 2, seg.payload_offset, "bold cyan"))
        ranges.append((payload_start, payload_start + 6, "magenta"))
        ranges.append((payload_start + 6, payload_start + 14, "bright_blue"))
        ifd0 = next((i for i in exif["ifds"] if i["name"] == "IFD0"), None)
        if ifd0:
            self._add_ifd0_table_ranges(ranges, ifd0)
        styles = ["green", "bright_cyan", "bright_yellow", "red", "bright_magenta"]
        for idx, ifd in enumerate(exif["ifds"]):
            style = styles[idx % len(styles)]
            ifd_rel = ifd["offset"] - exif["tiff_base"]
            ifd_abs = exif["tiff_base"] + ifd_rel
            count = ifd["count"]
            table_len = 2 + count * 12 + 4
            ranges.append((ifd_abs, ifd_abs + table_len, style))
            for entry in ifd["entries"]:
                if entry["value_len"] <= 4:
                    continue
                start = entry["value_offset"]
                end = start + entry["value_len"]
                ranges.append((start, end, style))
        return ranges

    def _app1_basic_ranges(self, seg) -> list[Tuple[int, int, str]]:
        payload_start = seg.payload_offset
        return [
            (seg.offset, seg.offset + 2, "bold yellow"),
            (seg.payload_offset - 2, seg.payload_offset, "bold cyan"),
            (payload_start, payload_start + 6, "magenta"),
            (payload_start + 6, payload_start + 14, "bright_blue"),
        ]

    def _add_ifd0_table_ranges(self, ranges: list[Tuple[int, int, str]], ifd: dict) -> None:
        table_start = ifd["offset"]
        ranges.append((table_start, table_start + 2, "bright_white"))
        for entry in ifd["entries"]:
            e = entry["entry_offset"]
            ranges.append((e, e + 2, "bright_green"))
            ranges.append((e + 2, e + 4, "bright_blue"))
            ranges.append((e + 4, e + 8, "bright_cyan"))
            ranges.append((e + 8, e + 12, "bright_yellow"))
        end = table_start + 2 + ifd["count"] * 12
        ranges.append((end, end + 4, "bright_red"))

    def _app1_key_from_id(self, widget_id: Optional[str], suffix: str) -> Optional[str]:
        if not widget_id or not widget_id.startswith("app1-") or not widget_id.endswith(suffix):
            return None
        return widget_id[: -len(suffix)]

    def _app1_save_inputs(self, key: str) -> Tuple[str, bytes]:
        input_path = self.query_one("#input-path", Input).value.strip()
        if not input_path:
            raise ValueError("input path is required.")
        if key not in self.app1_segment_info:
            raise ValueError("APP1 not loaded. Click Load Info first.")
        if piexif is None:
            raise ValueError("piexif is not installed.")
        text = self.query_one(f"#{key}-dict-editor", TextArea).text.strip()
        if not text:
            raise ValueError("EXIF editor is empty.")
        exif_dict = self._app1_parse_exif_dict(text)
        exif_bytes = piexif.dump(exif_dict)
        payload = b"Exif\x00\x00" + exif_bytes
        if len(payload) + 2 > 0xFFFF:
            raise ValueError("EXIF payload too large for APP1.")
        return input_path, payload

    def _app1_parse_exif_dict(self, text: str) -> dict:
        try:
            data = ast.literal_eval(text)
        except Exception as e:
            raise ValueError(f"Invalid EXIF dict: {e}")
        if not isinstance(data, dict):
            raise ValueError("EXIF editor must be a dict.")
        for key in ["0th", "Exif", "GPS", "1st", "Interop"]:
            if key not in data:
                data[key] = {}
            if not isinstance(data[key], dict):
                raise ValueError(f"EXIF {key} must be a dict.")
        if "thumbnail" not in data or data["thumbnail"] is None:
            data["thumbnail"] = b""
        if not isinstance(data["thumbnail"], (bytes, bytearray)):
            raise ValueError("EXIF thumbnail must be bytes.")
        return data

    def _app1_write_file(self, input_path: str, key: str, payload: bytes) -> Path:
        offset, total_len, _, _ = self.app1_segment_info[key]
        data = Path(input_path).read_bytes()
        marker = data[offset:offset + 2]
        length_field = len(payload) + 2
        new_seg = marker + length_field.to_bytes(2, "big") + payload
        new_data = data[:offset] + new_seg + data[offset + total_len:]
        out_path = Path(input_path).with_name(Path(input_path).stem + "_app1_edit.jpg")
        idx = 1
        while out_path.exists():
            out_path = Path(input_path).with_name(Path(input_path).stem + f"_app1_edit_{idx}.jpg")
            idx += 1
        out_path.write_bytes(new_data)
        return out_path

    def _app2_save_inputs(self, key: str) -> Tuple[str, bytes]:
        input_path = self.query_one("#input-path", Input).value.strip()
        if not input_path:
            raise ValueError("input path is required.")
        if key not in self.app2_segment_info:
            raise ValueError("APP2 not loaded. Click Load Info first.")
        payload = self.app2_original_payload.get(key, b"")
        icc = self._parse_icc_profile(payload, self.app2_segment_info[key][3])
        if icc.get("error"):
            raise ValueError(f"ICC parse error: {icc['error']}")
        tag_map = self._icc_tag_data_map(icc, payload)
        desc = self.query_one(f"#{key}-desc-input", Input).value.strip()
        cprt = self.query_one(f"#{key}-cprt-input", Input).value.strip()
        dmnd = self.query_one(f"#{key}-dmnd-input", Input).value.strip()
        dmdd = self.query_one(f"#{key}-dmdd-input", Input).value.strip()
        wtpt = self.query_one(f"#{key}-wtpt-input", Input).value.strip()
        bkpt = self.query_one(f"#{key}-bkpt-input", Input).value.strip()
        rxyz = self.query_one(f"#{key}-rxyz-input", Input).value.strip()
        gxyz = self.query_one(f"#{key}-gxyz-input", Input).value.strip()
        bxyz = self.query_one(f"#{key}-bxyz-input", Input).value.strip()
        rtrc = self.query_one(f"#{key}-rtrc-input", Input).value.strip()
        gtrc = self.query_one(f"#{key}-gtrc-input", Input).value.strip()
        btrc = self.query_one(f"#{key}-btrc-input", Input).value.strip()
        tag_types = self.app2_tag_types.get(key, {})
        updates: dict[str, bytes] = {}
        if desc:
            updates["desc"] = self._build_icc_text_tag(desc, tag_types.get("desc", "desc") or "desc")
        if cprt:
            updates["cprt"] = self._build_icc_text_tag(cprt, tag_types.get("cprt", "text") or "text")
        if dmnd:
            updates["dmnd"] = self._build_icc_text_tag(dmnd, "text")
        if dmdd:
            updates["dmdd"] = self._build_icc_text_tag(dmdd, "text")
        if wtpt:
            updates["wtpt"] = self._build_icc_xyz_tag(wtpt)
        if bkpt:
            updates["bkpt"] = self._build_icc_xyz_tag(bkpt)
        if rxyz:
            updates["rXYZ"] = self._build_icc_xyz_tag(rxyz)
        if gxyz:
            updates["gXYZ"] = self._build_icc_xyz_tag(gxyz)
        if bxyz:
            updates["bXYZ"] = self._build_icc_xyz_tag(bxyz)
        if rtrc:
            updates["rTRC"] = self._build_icc_gamma_tag(rtrc)
        if gtrc:
            updates["gTRC"] = self._build_icc_gamma_tag(gtrc)
        if btrc:
            updates["bTRC"] = self._build_icc_gamma_tag(btrc)
        new_icc = self._rebuild_icc_profile(payload[14:], icc["tags"], tag_map, updates)
        new_payload = b"ICC_PROFILE\x00" + bytes([1, 1]) + new_icc
        return input_path, new_payload

    def _rebuild_icc_profile(
        self, icc: bytes, tags: list[dict], tag_map: dict[str, bytes], updates: dict[str, bytes]
    ) -> bytes:
        order = [t["sig"] for t in tags]
        for sig in updates.keys():
            if sig not in order:
                order.append(sig)
        tag_data = {**tag_map, **updates}
        table_size = 4 + len(order) * 12
        data_start = 128 + table_size
        offsets: list[tuple[str, int, int]] = []
        cursor = data_start
        for sig in order:
            data_bytes = tag_data.get(sig, b"")
            size = len(data_bytes)
            offsets.append((sig, cursor, size))
            pad = (4 - (size % 4)) % 4
            cursor += size + pad
        size = cursor
        header = bytearray(icc[:128])
        header[0:4] = size.to_bytes(4, "big")
        out = bytearray()
        out.extend(header)
        out.extend(len(order).to_bytes(4, "big"))
        for sig, off, sz in offsets:
            out.extend(sig.encode("ascii", errors="replace"))
            out.extend(off.to_bytes(4, "big"))
            out.extend(sz.to_bytes(4, "big"))
        for sig, off, sz in offsets:
            data_bytes = tag_data.get(sig, b"")
            out.extend(data_bytes)
            pad = (4 - (len(data_bytes) % 4)) % 4
            if pad:
                out.extend(b"\x00" * pad)
        return bytes(out)

    def _app2_write_file(self, input_path: str, key: str, payload: bytes) -> Path:
        offset, total_len, _, _ = self.app2_segment_info[key]
        data = Path(input_path).read_bytes()
        marker = data[offset:offset + 2]
        length_field = len(payload) + 2
        new_seg = marker + length_field.to_bytes(2, "big") + payload
        new_data = data[:offset] + new_seg + data[offset + total_len:]
        out_path = Path(input_path).with_name(Path(input_path).stem + "_app2_edit.jpg")
        idx = 1
        while out_path.exists():
            out_path = Path(input_path).with_name(Path(input_path).stem + f"_app2_edit_{idx}.jpg")
            idx += 1
        out_path.write_bytes(new_data)
        return out_path

    def _refresh_app2_preview(self, key: str) -> None:
        err = self.query_one(f"#{key}-error", Static)
        err.update("")
        try:
            _, payload = self._app2_save_inputs(key)
        except Exception as e:
            err.update(f"Error: {e}")
            return
        self.app2_preview_payload[key] = payload
        seg_info = self.app2_segment_info.get(key)
        if not seg_info:
            return
        seg = self._app2_seg_from_info(seg_info, payload)
        data = self._app2_preview_data(self.info_data or b"", seg, payload)
        icc = self._parse_icc_profile(payload, seg.payload_offset)
        log_hex = self.query_one(f"#info-{key}-hex", RichLog)
        log_raw = self.query_one(f"#info-{key}-raw", RichLog)
        log_table = self.query_one(f"#info-{key}-table", RichLog)
        log_header = self.query_one(f"#{key}-header", RichLog)
        log_tags = self.query_one(f"#{key}-tags", RichLog)
        log_table2 = self.query_one(f"#{key}-tag-table", RichLog)
        log_hex.clear()
        log_raw.clear()
        log_table.clear()
        log_header.clear()
        log_tags.clear()
        log_table2.clear()
        if icc.get("error"):
            log_hex.write(f"ICC decode error: {icc['error']}")
            self._render_app2_raw_hex(log_raw, data, seg)
            return
        self._write_icc_header(log_header, icc)
        self._write_icc_tags(log_tags, icc)
        self._write_icc_table(log_table, icc)
        self._write_icc_tag_table(log_table2, icc, payload)
        ranges = self._icc_hex_ranges(seg, icc)
        self._write_icc_hex_legend(log_hex)
        self._render_icc_hex_sections(log_hex, data, seg, icc, ranges)
        self._render_app2_raw_hex(log_raw, data, seg)
        self._set_app2_dirty(key, True)

    def _app2_preview_data(self, data: bytes, seg, payload: bytes) -> bytes:
        if not data:
            return payload
        return data[:seg.payload_offset] + payload + data[seg.payload_offset + seg.payload_length:]

    def _app2_seg_from_info(self, seg_info: Tuple[int, int, int, int], payload: bytes):
        offset, total_len, length_field, payload_offset = seg_info
        seg = type("Seg", (), {})()
        seg.offset = offset
        seg.total_length = total_len
        seg.length_field = length_field
        seg.payload_offset = payload_offset
        seg.payload_length = len(payload)
        return seg

    def _app1_preview_data(self, data: bytes, seg, payload: bytes) -> bytes:
        return data[:seg.payload_offset] + payload + data[seg.payload_offset + seg.payload_length:]

    def _app1_seg_from_info(self, seg_info: Tuple[int, int, int, int], payload: bytes):
        offset, total_len, length_field, payload_offset = seg_info
        seg = type("Seg", (), {})()
        seg.offset = offset
        seg.total_length = total_len
        seg.length_field = length_field
        seg.payload_offset = payload_offset
        seg.payload_length = len(payload)
        return seg

    def _on_app1_header_hex_changed(self, key: str) -> None:
        if key not in self.app1_segment_info:
            return
        err = self.query_one(f"#{key}-error", Static)
        header_hex = self.query_one(f"#{key}-header-hex", TextArea).text
        try:
            header = self._parse_hex(header_hex)
        except Exception as e:
            err.update(f"Error: {e}")
            return
        if len(header) != 14:
            err.update("Error: header must be exactly 14 bytes (Exif + TIFF header).")
            return
        err.update("")
        original = self.app1_original_payload.get(key, b"")
        if len(original) < 14:
            return
        preview = header + original[14:]
        self.app1_preview_payload[key] = preview
        self._refresh_app1_hex_preview(key)

    def _refresh_app1_hex_preview(self, key: str) -> None:
        log_hex = self.query_one(f"#info-{key}-hex", RichLog)
        log_raw = self.query_one(f"#info-{key}-raw", RichLog)
        header = self.query_one(f"#{key}-header", RichLog)
        log_hex.clear()
        log_raw.clear()
        header.clear()
        seg_info = self.app1_segment_info.get(key)
        if not seg_info or self.info_data is None:
            return
        offset, total_len, length_field, payload_offset = seg_info
        seg = self._app1_seg_from_info(seg_info, self.app1_preview_payload.get(key, b""))
        payload = self.app1_preview_payload.get(key, b"")
        data = self._app1_preview_data(self.info_data, seg, payload)
        if not payload.startswith(b"Exif\x00\x00"):
            log_hex.write("APP1 payload is not EXIF (missing Exif\\0\\0 header).")
            self._render_app1_hex(log_hex, data, seg, self._app1_basic_ranges(seg))
            self._render_app1_raw_hex(log_raw, data, seg, self._app1_basic_ranges(seg))
            return
        exif = self._parse_exif(payload, payload_offset)
        if exif.get("error"):
            log_hex.write(f"EXIF decode error: {exif['error']}")
            self._render_app1_hex(log_hex, data, seg, self._app1_basic_ranges(seg))
            self._render_app1_raw_hex(log_raw, data, seg, self._app1_basic_ranges(seg))
            return
        self._write_app1_header(header, exif, seg)
        ranges = self._app1_hex_ranges(seg, exif)
        self._render_app1_hex_sections(log_hex, data, seg, exif, ranges)
        self._render_app1_raw_hex(log_raw, data, seg, ranges, exif)


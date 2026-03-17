from __future__ import annotations

import ast
from pathlib import Path
from pprint import pformat
from typing import Optional, Tuple

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

from .jpeg_parse import (
    build_dri_payload,
    build_sof0_payload,
    decode_app0,
    decode_dri,
    decode_sof0,
    decode_sof_components,
)


class TuiSegmentsBasicMixin:
    def _add_sof0_tab(self) -> None:
        tabs = self.query_one("#info-tabs", TabbedContent)
        tabs.add_pane(TabPane("SOF0", self._build_sof0_pane()))

    def _add_dri_tab(self) -> None:
        tabs = self.query_one("#info-tabs", TabbedContent)
        tabs.add_pane(TabPane("DRI", self._build_dri_pane()))

    def _build_sof0_pane(self) -> Horizontal:
        return Horizontal(
            VerticalScroll(
                Static("SOF0 bytes and frame summary", classes="field"),
                RichLog(id="info-sof0-left", highlight=True, classes="sof-log sof-left"),
            ),
            VerticalScroll(
                Static("Views: frame, components, tables, edit", classes="field"),
                TabbedContent(id="sof0-tabs"),
                classes="sof-right",
            ),
            classes="row",
        )

    def _build_dri_pane(self) -> Horizontal:
        return Horizontal(
            VerticalScroll(
                Static("DRI bytes and restart summary", classes="field"),
                RichLog(id="info-dri-left", highlight=True, classes="dri-log dri-left"),
            ),
            VerticalScroll(
                Static("Views: summary, effect, edit", classes="field"),
                TabbedContent(id="dri-tabs"),
                classes="dri-right",
            ),
            classes="row",
        )

    def _init_sof0_tabs(self) -> None:
        tabs = self.query_one("#sof0-tabs", TabbedContent)
        tabs.clear_panes()
        for name in ("Frame", "Components", "Tables"):
            pane_id = name.lower()
            tabs.add_pane(TabPane(name, RichLog(id=f"info-sof0-{pane_id}", highlight=True, classes="sof-log")))
        tabs.add_pane(
            TabPane(
                "Edit",
                VerticalScroll(
                    Static("Edit SOF0 frame fields as Python literal or raw payload hex.", classes="field"),
                    Checkbox("Advanced mode (raw payload hex)", value=False, id="sof0-advanced-mode"),
                    Checkbox("Manual length (dangerous)", value=False, id="sof0-manual-length"),
                    Input(value="", id="sof0-length", placeholder="Length (hex, e.g. 0011)"),
                    Button("Save edited file", id="sof0-save", variant="success", disabled=True),
                    Static("", id="sof0-edit-error"),
                    Static("Structured editor", classes="field", id="sof0-simple-title"),
                    TextArea("", id="sof0-struct-edit", soft_wrap=True, show_line_numbers=True, classes="sof-edit-area"),
                    Static("Raw payload hex", classes="field", id="sof0-adv-title"),
                    TextArea("", id="sof0-raw-hex", soft_wrap=True, show_line_numbers=True, classes="sof-edit-area"),
                ),
            )
        )

    def _init_dri_tabs(self) -> None:
        tabs = self.query_one("#dri-tabs", TabbedContent)
        tabs.clear_panes()
        for name in ("Summary", "Effect"):
            pane_id = name.lower()
            tabs.add_pane(TabPane(name, RichLog(id=f"info-dri-{pane_id}", highlight=True, classes="dri-log")))
        tabs.add_pane(
            TabPane(
                "Edit",
                VerticalScroll(
                    Static("Edit DRI restart interval or raw payload hex.", classes="field"),
                    Checkbox("Advanced mode (raw payload hex)", value=False, id="dri-advanced-mode"),
                    Checkbox("Manual length (dangerous)", value=False, id="dri-manual-length"),
                    Input(value="", id="dri-length", placeholder="Length (hex, e.g. 0004)"),
                    Button("Save edited file", id="dri-save", variant="success", disabled=True),
                    Static("", id="dri-edit-error"),
                    Static("Structured editor", classes="field", id="dri-simple-title"),
                    TextArea("", id="dri-struct-edit", soft_wrap=True, show_line_numbers=True, classes="dri-edit-area"),
                    Static("Raw payload hex", classes="field", id="dri-adv-title"),
                    TextArea("", id="dri-raw-hex", soft_wrap=True, show_line_numbers=True, classes="dri-edit-area"),
                ),
            )
        )

    def _build_app0_pane(self) -> Horizontal:
        return Horizontal(
            VerticalScroll(
                Static("APP0 info (decoded + hex)", classes="field"),
                RichLog(id="info-app0", highlight=True),
                id="app0-info",
            ),
            VerticalScroll(
                Static("Edit APP0 payload in simple or advanced mode.", classes="field"),
                Checkbox("Advanced mode (raw hex)", value=False, id="app0-advanced-mode"),
                Checkbox("Manual length (dangerous)", value=False, id="app0-manual-length"),
                Input(value="", id="app0-length", placeholder="Length (hex, e.g. 0010)"),
                Button("Save edited file", id="app0-save", variant="success", disabled=True),
                Static("", id="app0-edit-error"),
                Static("Simple mode", classes="field", id="app0-simple-title"),
                self._build_app0_simple_editor(),
                Static("Advanced mode", classes="field", id="app0-adv-title"),
                TextArea("", id="app0-raw-hex", soft_wrap=True, show_line_numbers=True),
                id="app0-edit",
            ),
            id="app0-panel",
        )

    def _build_app0_simple_editor(self) -> Vertical:
        return Vertical(
            Horizontal(
                self._build_app0_left_column(),
                self._build_app0_right_column(),
                classes="row",
            ),
            Label("Thumbnail hex (3 * X * Y bytes)", classes="field"),
            TextArea("", id="app0-thumb-hex", soft_wrap=True, show_line_numbers=False),
            id="app0-simple",
        )

    def _build_app0_left_column(self) -> Vertical:
        return Vertical(
            Label("Identifier", classes="field"),
            Select(
                [
                    ("JFIF\\0", "JFIF\\0"),
                    ("JFXX\\0", "JFXX\\0"),
                ],
                value="JFIF\\0",
                id="app0-ident",
            ),
            Label("Version", classes="field"),
            Select(
                [
                    ("1.00", "1.00"),
                    ("1.01", "1.01"),
                    ("1.02", "1.02"),
                ],
                value="1.01",
                id="app0-version",
            ),
            Label("Units", classes="field"),
            Select(
                [
                    ("0 (none)", "0"),
                    ("1 (dpi)", "1"),
                    ("2 (dpcm)", "2"),
                ],
                value="0",
                id="app0-units",
            ),
            Label("X density", classes="field"),
            Input(value="1", id="app0-xden"),
            Label("X thumbnail", classes="field"),
            Input(value="0", id="app0-xthumb"),
            id="app0-col-left",
        )

    def _build_app0_right_column(self) -> Vertical:
        return Vertical(
            Label("Y density", classes="field"),
            Input(value="1", id="app0-yden"),
            Label("Y thumbnail", classes="field"),
            Input(value="0", id="app0-ythumb"),
            id="app0-col-right",
        )

    def _apply_app0_mode_visibility(self) -> None:
        """
        Show/hide APP0 simple or advanced editors based on the mode checkbox.
        """
        try:
            adv = self.query_one("#app0-advanced-mode", Checkbox).value
            self.query_one("#app0-simple", Vertical).display = not adv
            self.query_one("#app0-simple-title", Static).display = not adv
            self.query_one("#app0-adv-title", Static).display = adv
            self.query_one("#app0-raw-hex", TextArea).display = adv

            manual = self.query_one("#app0-manual-length", Checkbox).value
            self.query_one("#app0-length", Input).disabled = not manual
        except Exception:
            # APP0 editor not mounted (no APP0 tab)
            return

    # Shared editor mechanics (SOF0/DRI/DQT/DHT).
    def _apply_sof0_mode_visibility(self) -> None:
        self._apply_editor_mode_visibility(
            advanced_id="sof0-advanced-mode",
            struct_id="sof0-struct-edit",
            simple_title_id="sof0-simple-title",
            raw_id="sof0-raw-hex",
            adv_title_id="sof0-adv-title",
            manual_length_id="sof0-manual-length",
            length_id="sof0-length",
        )

    def _apply_dri_mode_visibility(self) -> None:
        self._apply_editor_mode_visibility(
            advanced_id="dri-advanced-mode",
            struct_id="dri-struct-edit",
            simple_title_id="dri-simple-title",
            raw_id="dri-raw-hex",
            adv_title_id="dri-adv-title",
            manual_length_id="dri-manual-length",
            length_id="dri-length",
        )

    def _serialize_dri_struct_to_payload(self) -> bytes:
        try:
            parsed = ast.literal_eval(self.query_one("#dri-struct-edit", TextArea).text)
        except Exception as e:
            raise ValueError(f"invalid DRI editor content: {e}")
        if not isinstance(parsed, dict):
            raise ValueError("DRI editor must be a dictionary.")
        return build_dri_payload(int(parsed.get("restart_interval", 0)))

    def _sync_dri_editor_for_mode(self) -> None:
        self._sync_editor_for_mode(
            advanced_id="dri-advanced-mode",
            raw_id="dri-raw-hex",
            serialize_struct=self._serialize_dri_struct_to_payload,
            deserialize_payload=lambda payload: self._set_dri_editor_values(payload, len(payload) + 2),
        )

    def _build_dri_payload(self) -> bytes:
        if self.query_one("#dri-advanced-mode", Checkbox).value:
            return self._parse_hex(self.query_one("#dri-raw-hex", TextArea).text)
        return self._serialize_dri_struct_to_payload()

    def _dri_length_from_ui(self, payload: bytes) -> int:
        return self._length_from_ui_hex(
            manual_length_id="dri-manual-length",
            length_id="dri-length",
            payload=payload,
            example="0004",
        )

    def _mark_dri_dirty(self, dirty: bool) -> None:
        self.dri_dirty = dirty
        try:
            self.query_one("#dri-save", Button).disabled = not dirty
        except Exception:
            return

    def _refresh_dri_preview(self) -> None:
        self._refresh_single_segment_preview(
            segment_info=self.dri_segment_info,
            err_id="dri-edit-error",
            build_payload=self._build_dri_payload,
            length_from_ui=self._dri_length_from_ui,
            set_preview=self._set_dri_preview_payload,
            render_views=self._render_dri_views,
            mark_dirty=self._mark_dri_dirty,
        )

    def _set_dri_preview_payload(self, payload: bytes) -> None:
        self.dri_preview_payload = payload

    def _dri_save_inputs(self) -> Tuple[str, bytes, int]:
        input_path = self.query_one("#input-path", Input).value.strip()
        if not input_path:
            raise ValueError("input path is required.")
        if not self.dri_segment_info:
            raise ValueError("DRI not loaded. Click Load Info first.")
        payload = self._build_dri_payload()
        return input_path, payload, self._dri_length_from_ui(payload)

    def _dri_write_file(self, input_path: str, payload: bytes, length_field: int) -> Path:
        offset, total_len, _, _ = self.dri_segment_info
        return self._write_segment_edit_file(
            input_path=input_path,
            offset=offset,
            total_len=total_len,
            payload=payload,
            length_field=length_field,
            suffix="_dri_edit",
        )

    def _dri_save_log(self, out_path: Path, payload: bytes, length_field: int) -> None:
        self._segment_save_log(
            log_id="info-dri-left",
            out_path=out_path,
            payload=payload,
            length_field=length_field,
            manual_length_id="dri-manual-length",
        )

    def _serialize_sof0_struct_to_payload(self) -> bytes:
        parsed = ast.literal_eval(self.query_one("#sof0-struct-edit", TextArea).text)
        if not isinstance(parsed, dict):
            raise ValueError("SOF0 editor must be a dictionary.")
        precision = int(parsed.get("precision_bits", 8))
        width = int(parsed.get("width", 0))
        height = int(parsed.get("height", 0))
        components = parsed.get("components", [])
        if not isinstance(components, list):
            raise ValueError("SOF0 components must be a list.")
        normalized = []
        for idx, comp in enumerate(components, start=1):
            if not isinstance(comp, dict):
                raise ValueError(f"SOF0 component {idx} must be a dictionary.")
            normalized.append({
                "id": int(comp.get("id", 0)),
                "h_sampling": int(comp.get("h_sampling", 1)),
                "v_sampling": int(comp.get("v_sampling", 1)),
                "quant_table_id": int(comp.get("quant_table_id", 0)),
            })
        return build_sof0_payload(precision, width, height, normalized)

    def _sync_sof0_editor_for_mode(self) -> None:
        self._sync_editor_for_mode(
            advanced_id="sof0-advanced-mode",
            raw_id="sof0-raw-hex",
            serialize_struct=self._serialize_sof0_struct_to_payload,
            deserialize_payload=lambda payload: self._set_sof0_editor_values(payload, len(payload) + 2),
        )

    def _build_sof0_payload(self) -> bytes:
        if self.query_one("#sof0-advanced-mode", Checkbox).value:
            return self._parse_hex(self.query_one("#sof0-raw-hex", TextArea).text)
        try:
            return self._serialize_sof0_struct_to_payload()
        except Exception as e:
            raise ValueError(f"invalid SOF0 editor content: {e}")

    def _sof0_length_from_ui(self, payload: bytes) -> int:
        return self._length_from_ui_hex(
            manual_length_id="sof0-manual-length",
            length_id="sof0-length",
            payload=payload,
            example="0011",
        )

    def _mark_sof0_dirty(self, dirty: bool) -> None:
        self.sof0_dirty = dirty
        try:
            self.query_one("#sof0-save", Button).disabled = not dirty
        except Exception:
            return

    def _refresh_sof0_preview(self) -> None:
        self._refresh_single_segment_preview(
            segment_info=self.sof0_segment_info,
            err_id="sof0-edit-error",
            build_payload=self._build_sof0_payload,
            length_from_ui=self._sof0_length_from_ui,
            set_preview=self._set_sof0_preview_payload,
            render_views=self._render_sof0_views,
            mark_dirty=self._mark_sof0_dirty,
        )

    def _set_sof0_preview_payload(self, payload: bytes) -> None:
        self.sof0_preview_payload = payload

    def _sof0_save_inputs(self) -> Tuple[str, bytes, int]:
        input_path = self.query_one("#input-path", Input).value.strip()
        if not input_path:
            raise ValueError("input path is required.")
        if not self.sof0_segment_info:
            raise ValueError("SOF0 not loaded. Click Load Info first.")
        payload = self._build_sof0_payload()
        return input_path, payload, self._sof0_length_from_ui(payload)

    def _sof0_write_file(self, input_path: str, payload: bytes, length_field: int) -> Path:
        offset, total_len, _, _ = self.sof0_segment_info
        return self._write_segment_edit_file(
            input_path=input_path,
            offset=offset,
            total_len=total_len,
            payload=payload,
            length_field=length_field,
            suffix="_sof0_edit",
        )

    def _sof0_save_log(self, out_path: Path, payload: bytes, length_field: int) -> None:
        self._segment_save_log(
            log_id="info-sof0-left",
            out_path=out_path,
            payload=payload,
            length_field=length_field,
            manual_length_id="sof0-manual-length",
        )

    @on(Checkbox.Changed, "#app0-advanced-mode")
    def _on_app0_mode_changed(self) -> None:
        self._apply_app0_mode_visibility()
        self._update_app0_length_field()
        self._refresh_app0_preview()
        self._mark_app0_dirty(True)

    @on(Checkbox.Changed)
    def _on_sof0_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id == "sof0-advanced-mode":
            self._apply_sof0_mode_visibility()
            try:
                self._sync_sof0_editor_for_mode()
            except Exception:
                pass
            self._refresh_sof0_preview()
            return
        if event.checkbox.id != "sof0-manual-length":
            return
        self._apply_sof0_mode_visibility()
        if not event.checkbox.value and self.sof0_preview_payload is not None:
            self.query_one("#sof0-length", Input).value = f"{len(self.sof0_preview_payload) + 2:04X}"
        self._refresh_sof0_preview()

    @on(Checkbox.Changed)
    def _on_dri_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id == "dri-advanced-mode":
            self._apply_dri_mode_visibility()
            try:
                self._sync_dri_editor_for_mode()
            except Exception:
                pass
            self._refresh_dri_preview()
            return
        if event.checkbox.id != "dri-manual-length":
            return
        self._apply_dri_mode_visibility()
        if not event.checkbox.value and self.dri_preview_payload is not None:
            self.query_one("#dri-length", Input).value = f"{len(self.dri_preview_payload) + 2:04X}"
        self._refresh_dri_preview()

    @on(Checkbox.Changed, "#app0-manual-length")
    def _on_app0_manual_length_changed(self) -> None:
        self._apply_app0_mode_visibility()
        if not self.query_one("#app0-manual-length", Checkbox).value:
            self._update_app0_length_field()
        self._refresh_app0_preview()
        self._mark_app0_dirty(True)

    @on(Input.Changed)
    def _on_app0_input_changed(self, event: Input.Changed) -> None:
        if not event.input.id or not event.input.id.startswith("app0-"):
            return
        if event.input.id == "app0-length":
            self._mark_app0_dirty(True)
            return
        self._update_app0_length_field()
        self._refresh_app0_preview()
        self._mark_app0_dirty(True)

    @on(Input.Changed)
    def _on_sof0_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "sof0-length":
            return
        self._mark_sof0_dirty(True)
        if self.query_one("#sof0-manual-length", Checkbox).value:
            self._refresh_sof0_preview()

    @on(Input.Changed)
    def _on_dri_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "dri-length":
            return
        self._mark_dri_dirty(True)
        if self.query_one("#dri-manual-length", Checkbox).value:
            self._refresh_dri_preview()

    @on(TextArea.Changed)
    def _on_app0_textarea_changed(self, event: TextArea.Changed) -> None:
        if not event.text_area.id or not event.text_area.id.startswith("app0-"):
            return
        self._update_app0_length_field()
        self._refresh_app0_preview()
        self._mark_app0_dirty(True)

    @on(TextArea.Changed)
    def _on_sof0_textarea_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id not in {"sof0-struct-edit", "sof0-raw-hex"}:
            return
        if not self.query_one("#sof0-manual-length", Checkbox).value:
            try:
                payload = self._build_sof0_payload()
            except Exception:
                self._mark_sof0_dirty(True)
            else:
                self.query_one("#sof0-length", Input).value = f"{len(payload) + 2:04X}"
        self._refresh_sof0_preview()

    @on(TextArea.Changed)
    def _on_dri_textarea_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id not in {"dri-struct-edit", "dri-raw-hex"}:
            return
        if not self.query_one("#dri-manual-length", Checkbox).value:
            try:
                payload = self._build_dri_payload()
            except Exception:
                self._mark_dri_dirty(True)
            else:
                self.query_one("#dri-length", Input).value = f"{len(payload) + 2:04X}"
        self._refresh_dri_preview()

    @on(Button.Pressed, "#sof0-save")
    def _on_sof0_save(self) -> None:
        err = self.query_one("#sof0-edit-error", Static)
        err.update("")
        try:
            input_path, payload, length_field = self._sof0_save_inputs()
        except Exception as e:
            err.update(f"Error: {e}")
            return
        out_path = self._sof0_write_file(input_path, payload, length_field)
        self._sof0_save_log(out_path, payload, length_field)
        self._mark_sof0_dirty(False)

    @on(Button.Pressed, "#dri-save")
    def _on_dri_save(self) -> None:
        err = self.query_one("#dri-edit-error", Static)
        err.update("")
        try:
            input_path, payload, length_field = self._dri_save_inputs()
        except Exception as e:
            err.update(f"Error: {e}")
            return
        out_path = self._dri_write_file(input_path, payload, length_field)
        self._dri_save_log(out_path, payload, length_field)
        self._mark_dri_dirty(False)

    @on(Select.Changed)
    def _on_app0_select_changed(self, event: Select.Changed) -> None:
        if not event.select.id or not event.select.id.startswith("app0-"):
            return
        self._update_app0_length_field()
        self._refresh_app0_preview()
        self._mark_app0_dirty(True)

    def _render_app0_segment(self, data: bytes, segments) -> None:
        """
        Render a dedicated APP0 view with decoded fields and hex dump.
        """
        app0_log = self.query_one("#info-app0", RichLog)
        app0_log.clear()
        app0 = next((s for s in segments if s.name == "APP0"), None)
        if app0 is None or app0.payload_offset is None or app0.payload_length is None:
            self._clear_app0_editor()
            app0_log.write("No APP0 segment found.")
            return
        self.app0_segment_info = (app0.offset, app0.total_length, app0.length_field or 0, app0.payload_offset)

        payload = data[app0.payload_offset:app0.payload_offset + app0.payload_length]
        self.app0_original_payload = payload
        self._set_app0_editor_values(payload, app0.length_field or 0)
        decoded = decode_app0(payload)
        self._app0_log_header(app0_log, app0.offset, app0.length_field, app0.payload_length, decoded)

        # Highlight regions with distinct green shades for JFIF fields.
        marker_start = app0.offset
        marker_end = app0.offset + 2
        length_start = app0.payload_offset - 2
        length_end = app0.payload_offset
        payload_start = app0.payload_offset
        payload_end = app0.payload_offset + app0.payload_length

        ranges = self._app0_ranges(
            marker_start, marker_end, length_start, length_end, payload_start, payload, payload_end, app0_log
        )

        dump = self._hex_dump(data, app0.offset, app0.total_length, ranges)
        for line in dump:
            app0_log.write(line)

    def _render_sof0_segment(self, data: bytes, segments) -> None:
        left_log = self.query_one("#info-sof0-left", RichLog)
        frame_log = self.query_one("#info-sof0-frame", RichLog)
        comps_log = self.query_one("#info-sof0-components", RichLog)
        tables_log = self.query_one("#info-sof0-tables", RichLog)
        for log in (left_log, frame_log, comps_log, tables_log):
            log.clear()
        seg = next((s for s in segments if s.name == "SOF0"), None)
        if seg is None or seg.payload_offset is None or seg.payload_length is None:
            self._clear_sof0_editor()
            left_log.write("No SOF0 segment found.")
            return
        payload = data[seg.payload_offset:seg.payload_offset + seg.payload_length]
        self.sof0_segment_info = (seg.offset, seg.total_length, seg.length_field or 0, seg.payload_offset)
        self.sof0_original_payload = payload
        self.sof0_preview_payload = payload
        self._set_sof0_editor_values(payload, seg.length_field or 0)
        self._apply_sof0_mode_visibility()
        self._mark_sof0_dirty(False)
        self._render_sof0_views(seg.offset, seg.length_field or 0, payload)

    def _render_sof0_views(self, offset: int, length_field: int, payload: bytes) -> None:
        left_log = self.query_one("#info-sof0-left", RichLog)
        frame_log = self.query_one("#info-sof0-frame", RichLog)
        comps_log = self.query_one("#info-sof0-components", RichLog)
        tables_log = self.query_one("#info-sof0-tables", RichLog)
        for log in (left_log, frame_log, comps_log, tables_log):
            log.clear()
        info = decode_sof0(payload)
        components = decode_sof_components(payload)
        self._write_sof0_left_panel(left_log, offset, length_field, payload, info, components)
        self._write_sof0_frame_tab(frame_log, info)
        self._write_sof0_components_tab(comps_log, components)
        self._write_sof0_tables_tab(tables_log, components)

    def _write_sof0_left_panel(self, log: RichLog, offset: int, length_field: int, payload: bytes, info, components) -> None:
        log.write(f"SOF0 at 0x{offset:08X} length=0x{length_field:04X} payload={len(payload)}")
        if info:
            log.write(
                f"Frame: {info['width']}x{info['height']} precision={info['precision_bits']} components={info['components']}"
            )
        log.write("SOF0 stores the baseline frame header: geometry plus one descriptor per image component.")
        log.write("Legend:")
        for label, style in [
            ("Marker", "bold yellow"),
            ("Length", "bold cyan"),
            ("Sample precision", "magenta"),
            ("Image height/width", "bright_cyan"),
            ("Component count", "bright_yellow"),
            ("Component descriptors", "green"),
        ]:
            log.write(Text("  " + label, style=style))
        for idx, comp in enumerate(components, start=1):
            log.write(
                f"Component {idx}: id={comp['id']} ({self._component_name(comp['id'])}) "
                f"sampling={comp['h_sampling']}x{comp['v_sampling']} qtable={comp['quant_table_id']}"
            )
        segment_bytes = b"\xFF\xC0" + length_field.to_bytes(2, "big") + payload
        for line in self._hex_dump(segment_bytes, 0, len(segment_bytes), self._sof0_ranges(payload)):
            log.write(line)

    def _sof0_ranges(self, payload: bytes) -> list[Tuple[int, int, str]]:
        ranges = [(0, 2, "bold yellow"), (2, 4, "bold cyan")]
        if len(payload) < 6:
            return ranges
        ranges.extend([
            (4, 5, "magenta"),
            (5, 9, "bright_cyan"),
            (9, 10, "bright_yellow"),
        ])
        cursor = 10
        while cursor + 3 <= 4 + len(payload):
            ranges.append((cursor, cursor + 3, "green"))
            cursor += 3
        return ranges

    def _write_sof0_frame_tab(self, log: RichLog, info) -> None:
        if not info:
            log.write("Could not decode SOF0 frame header.")
            return
        log.write("Baseline frame header")
        log.write(f"  Width: {info['width']}")
        log.write(f"  Height: {info['height']}")
        log.write(f"  Precision: {info['precision_bits']} bits/sample")
        log.write(f"  Components: {info['components']}")

    def _write_sof0_components_tab(self, log: RichLog, components: list[dict[str, int]]) -> None:
        if not components:
            log.write("No SOF0 component descriptors found.")
            return
        log.write("Per-component frame descriptors")
        for comp in components:
            log.write("")
            log.write(f"Component {comp['id']} ({self._component_name(comp['id'])})")
            log.write(f"  Sampling factors: H={comp['h_sampling']} V={comp['v_sampling']}")
            log.write(f"  Sampling ratio: {comp['h_sampling']}x{comp['v_sampling']}")
            log.write(f"  Quantization table id: {comp['quant_table_id']}")

    def _write_sof0_tables_tab(self, log: RichLog, components: list[dict[str, int]]) -> None:
        if not components:
            log.write("No SOF0 component descriptors found.")
            return
        log.write("Quantization-table references inferred from SOF0 component descriptors.")
        groups: dict[int, list[dict[str, int]]] = {}
        for comp in components:
            groups.setdefault(comp["quant_table_id"], []).append(comp)
        for qid in sorted(groups):
            log.write("")
            log.write(f"Quantization table id={qid}")
            for comp in groups[qid]:
                log.write(
                    f"  Component {comp['id']} ({self._component_name(comp['id'])}) "
                    f"sampling={comp['h_sampling']}x{comp['v_sampling']}"
                )

    def _clear_sof0_editor(self) -> None:
        self.sof0_segment_info = None
        self.sof0_original_payload = None
        self.sof0_preview_payload = None
        self.query_one("#sof0-raw-hex", TextArea).text = ""
        self.query_one("#sof0-struct-edit", TextArea).text = ""
        self.query_one("#sof0-length", Input).value = ""
        self._mark_sof0_dirty(False)

    def _set_sof0_editor_values(self, payload: bytes, length_field: int) -> None:
        info = decode_sof0(payload) or {
            "precision_bits": "8",
            "width": "0",
            "height": "0",
            "components": "0",
        }
        struct = {
            "precision_bits": int(info["precision_bits"]),
            "width": int(info["width"]),
            "height": int(info["height"]),
            "components": decode_sof_components(payload),
        }
        self.query_one("#sof0-raw-hex", TextArea).text = self._bytes_to_hex(payload)
        self.query_one("#sof0-struct-edit", TextArea).text = pformat(struct, width=100, sort_dicts=False)
        self.query_one("#sof0-length", Input).value = f"{length_field:04X}"

    def _render_dri_segment(self, data: bytes, segments) -> None:
        left_log = self.query_one("#info-dri-left", RichLog)
        summary_log = self.query_one("#info-dri-summary", RichLog)
        effect_log = self.query_one("#info-dri-effect", RichLog)
        for log in (left_log, summary_log, effect_log):
            log.clear()
        seg = next((s for s in segments if s.name == "DRI"), None)
        if seg is None or seg.payload_offset is None or seg.payload_length is None:
            self._clear_dri_editor()
            left_log.write("No DRI segment found.")
            return
        payload = data[seg.payload_offset:seg.payload_offset + seg.payload_length]
        self.dri_segment_info = (seg.offset, seg.total_length, seg.length_field or 0, seg.payload_offset)
        self.dri_original_payload = payload
        self.dri_preview_payload = payload
        self._set_dri_editor_values(payload, seg.length_field or 0)
        self._apply_dri_mode_visibility()
        self._mark_dri_dirty(False)
        self._render_dri_views(seg.offset, seg.length_field or 0, payload)

    def _render_dri_views(self, offset: int, length_field: int, payload: bytes) -> None:
        left_log = self.query_one("#info-dri-left", RichLog)
        summary_log = self.query_one("#info-dri-summary", RichLog)
        effect_log = self.query_one("#info-dri-effect", RichLog)
        for log in (left_log, summary_log, effect_log):
            log.clear()
        info = decode_dri(payload)
        self._write_dri_left_panel(left_log, offset, length_field, payload, info)
        self._write_dri_summary_tab(summary_log, info)
        self._write_dri_effect_tab(effect_log, info)

    def _write_dri_left_panel(self, log: RichLog, offset: int, length_field: int, payload: bytes, info) -> None:
        log.write(f"DRI at 0x{offset:08X} length=0x{length_field:04X} payload={len(payload)}")
        if info:
            log.write(f"Restart interval: {info['restart_interval']} MCUs")
        log.write("DRI sets the restart interval used by restart markers in the entropy-coded stream.")
        log.write("Legend:")
        for label, style in [
            ("Marker", "bold yellow"),
            ("Length", "bold cyan"),
            ("Restart interval", "magenta"),
        ]:
            log.write(Text("  " + label, style=style))
        segment_bytes = b"\xFF\xDD" + length_field.to_bytes(2, "big") + payload
        ranges = [(0, 2, "bold yellow"), (2, 4, "bold cyan"), (4, 6, "magenta")]
        for line in self._hex_dump(segment_bytes, 0, len(segment_bytes), ranges):
            log.write(line)

    def _write_dri_summary_tab(self, log: RichLog, info) -> None:
        if not info:
            log.write("Could not decode DRI payload.")
            return
        interval = int(info["restart_interval"])
        log.write("Define Restart Interval")
        log.write(f"  Restart interval: {interval} MCUs")
        log.write(f"  Enabled: {'yes' if interval > 0 else 'no'}")

    def _write_dri_effect_tab(self, log: RichLog, info) -> None:
        if not info:
            log.write("Could not decode DRI payload.")
            return
        interval = int(info["restart_interval"])
        log.write("Effect on entropy-coded data")
        if interval == 0:
            log.write("  Restart markers are effectively disabled.")
            log.write("  The scan may omit RST markers entirely.")
            return
        log.write(f"  Decoder expects a restart opportunity every {interval} MCUs.")
        log.write("  Restart markers can improve error resynchronization after bitstream damage.")
        log.write("  This segment does not contain the markers; it only configures their spacing.")

    def _clear_dri_editor(self) -> None:
        self.dri_segment_info = None
        self.dri_original_payload = None
        self.dri_preview_payload = None
        self.query_one("#dri-raw-hex", TextArea).text = ""
        self.query_one("#dri-struct-edit", TextArea).text = ""
        self.query_one("#dri-length", Input).value = ""
        self._mark_dri_dirty(False)

    def _set_dri_editor_values(self, payload: bytes, length_field: int) -> None:
        info = decode_dri(payload) or {"restart_interval": "0"}
        struct = {"restart_interval": int(info["restart_interval"])}
        self.query_one("#dri-raw-hex", TextArea).text = self._bytes_to_hex(payload)
        self.query_one("#dri-struct-edit", TextArea).text = pformat(struct, width=100, sort_dicts=False)
        self.query_one("#dri-length", Input).value = f"{length_field:04X}"

    def _app0_log_header(self, app0_log: RichLog, offset: int, length_field: int, payload_len: int, decoded) -> None:
        app0_log.write(f"APP0 at 0x{offset:08X} length=0x{length_field:04X} payload={payload_len}")
        if not decoded:
            app0_log.write("Decoded: None (payload not recognized as JFIF/JFXX)")
            return
        self._write_decoded_lines(app0_log, decoded)

    def _clear_app0_editor(self) -> None:
        self.app0_original_payload = None
        self.app0_segment_info = None
        self.query_one("#app0-raw-hex", TextArea).text = ""
        self.query_one("#app0-thumb-hex", TextArea).text = ""
        self.query_one("#app0-length", Input).value = ""
        self.query_one("#app0-ident", Select).value = "JFIF\\0"
        self.query_one("#app0-version", Select).value = "1.01"
        self.query_one("#app0-units", Select).value = "0"
        self.query_one("#app0-xden", Input).value = "1"
        self.query_one("#app0-yden", Input).value = "1"
        self.query_one("#app0-xthumb", Input).value = "0"
        self.query_one("#app0-ythumb", Input).value = "0"
        self._mark_app0_dirty(False)

    def _app0_ranges(
        self,
        marker_start: int,
        marker_end: int,
        length_start: int,
        length_end: int,
        payload_start: int,
        payload: bytes,
        payload_end: int,
        app0_log: RichLog,
    ):
        ranges = [
            (marker_start, marker_end, "bold yellow"),
            (length_start, length_end, "bold cyan"),
        ]
        if len(payload) < 14:
            return ranges
        app0_log.write("Legend:")
        for label, style in [
            ("Identifier (JFIF\\0)", "green"),
            ("Version", "bright_blue"),
            ("Units", "magenta"),
            ("X density", "bright_cyan"),
            ("Y density", "bright_cyan"),
            ("X thumbnail", "bright_yellow"),
            ("Y thumbnail", "bright_yellow"),
            ("Thumbnail data", "red"),
        ]:
            app0_log.write(Text("  " + label, style=style))
        ranges.extend(
            [
                (payload_start, payload_start + 5, "green"),
                (payload_start + 5, payload_start + 7, "bright_blue"),
                (payload_start + 7, payload_start + 8, "magenta"),
                (payload_start + 8, payload_start + 10, "bright_cyan"),
                (payload_start + 10, payload_start + 12, "bright_cyan"),
                (payload_start + 12, payload_start + 13, "bright_yellow"),
                (payload_start + 13, payload_start + 14, "bright_yellow"),
            ]
        )
        thumb_w = payload[12]
        thumb_h = payload[13]
        thumb_bytes = 3 * thumb_w * thumb_h
        thumb_start = payload_start + 14
        thumb_end = min(payload_end, thumb_start + thumb_bytes)
        if thumb_bytes > 0:
            ranges.append((thumb_start, thumb_end, "red"))
        return ranges

    def _set_app0_editor_values(self, payload: bytes, length_field: int) -> None:
        """
        Populate APP0 editor inputs from the current payload.
        """
        # Raw hex view
        self.query_one("#app0-raw-hex", TextArea).text = self._bytes_to_hex(payload)

        # Simple fields (JFIF header if present)
        if len(payload) >= 14:
            ident = payload[:5].decode(errors="ignore")
            if ident == "JFIF\x00":
                self.query_one("#app0-ident", Select).value = "JFIF\\0"
            elif ident == "JFXX\x00":
                self.query_one("#app0-ident", Select).value = "JFXX\\0"
            ver_major = payload[5]
            ver_minor = payload[6]
            units = payload[7]
            xden = int.from_bytes(payload[8:10], "big")
            yden = int.from_bytes(payload[10:12], "big")
            xthumb = payload[12]
            ythumb = payload[13]
            thumb_len = 3 * xthumb * ythumb
            thumb_bytes = payload[14:14 + thumb_len]
            self.query_one("#app0-version", Select).value = f"{ver_major}.{ver_minor:02d}"
            self.query_one("#app0-units", Select).value = str(units)
            self.query_one("#app0-xden", Input).value = str(xden)
            self.query_one("#app0-yden", Input).value = str(yden)
            self.query_one("#app0-xthumb", Input).value = str(xthumb)
            self.query_one("#app0-ythumb", Input).value = str(ythumb)
            self.query_one("#app0-thumb-hex", TextArea).text = self._bytes_to_hex(thumb_bytes)

        self.query_one("#app0-length", Input).value = f"{length_field:04X}"
        self._apply_app0_mode_visibility()

    def _update_app0_length_field(self) -> None:
        """
        Update the length field if manual length is not enabled.
        """
        manual = self.query_one("#app0-manual-length", Checkbox).value
        if manual:
            return
        try:
            payload = self._build_app0_payload()
        except Exception:
            return
        length_field = len(payload) + 2
        self.query_one("#app0-length", Input).value = f"{length_field:04X}"

    def _mark_app0_dirty(self, dirty: bool) -> None:
        """
        Update dirty state and save button enabled status.
        """
        self.app0_dirty = dirty
        try:
            self.query_one("#app0-save", Button).disabled = not dirty
        except Exception:
            # APP0 editor not mounted.
            return

    def _build_app0_payload(self) -> bytes:
        """
        Build APP0 payload from the current editor mode.
        """
        adv = self.query_one("#app0-advanced-mode", Checkbox).value
        if adv:
            return self._parse_hex(self.query_one("#app0-raw-hex", TextArea).text)

        # Simple mode fields
        def _byte(value: str, label: str) -> int:
            v = int(value)
            if v < 0 or v > 255:
                raise ValueError(f"{label} must be 0-255.")
            return v

        def _u16(value: str, label: str) -> int:
            v = int(value)
            if v < 0 or v > 65535:
                raise ValueError(f"{label} must be 0-65535.")
            return v

        ident = self.query_one("#app0-ident", Select).value
        version = self.query_one("#app0-version", Select).value
        if "." not in str(version):
            raise ValueError("Version must be in major.minor format.")
        ver_major_s, ver_minor_s = str(version).split(".", 1)
        ver_major = _byte(ver_major_s, "Version major")
        ver_minor = _byte(ver_minor_s, "Version minor")
        units = _byte(str(self.query_one("#app0-units", Select).value), "Units")
        xden = _u16(self.query_one("#app0-xden", Input).value, "X density")
        yden = _u16(self.query_one("#app0-yden", Input).value, "Y density")
        xthumb = _byte(self.query_one("#app0-xthumb", Input).value, "X thumbnail")
        ythumb = _byte(self.query_one("#app0-ythumb", Input).value, "Y thumbnail")

        thumb_hex = self.query_one("#app0-thumb-hex", TextArea).text.strip()
        thumb_bytes = b""
        if thumb_hex:
            thumb_bytes = self._parse_hex(thumb_hex)

        expected = 3 * xthumb * ythumb
        if expected != len(thumb_bytes):
            raise ValueError(f"Thumbnail data length must be {expected} bytes.")

        payload = bytearray()
        if ident == "JFXX\\0":
            payload.extend(b"JFXX\x00")
        else:
            payload.extend(b"JFIF\x00")
        payload.append(ver_major)
        payload.append(ver_minor)
        payload.append(units)
        payload.extend(xden.to_bytes(2, "big"))
        payload.extend(yden.to_bytes(2, "big"))
        payload.append(xthumb)
        payload.append(ythumb)
        payload.extend(thumb_bytes)
        return bytes(payload)

    @on(Button.Pressed, "#app0-save")
    def _on_app0_save(self) -> None:
        """
        Save the edited APP0 payload to a new file.
        """
        err = self.query_one("#app0-edit-error", Static)
        err.update("")
        try:
            input_path, payload, length_field = self._app0_save_inputs()
        except Exception as e:
            err.update(f"Error: {e}")
            return
        out_path = self._app0_write_file(input_path, payload, length_field)
        self._app0_save_log(out_path, payload, length_field)
        self._mark_app0_dirty(False)

    def _app0_save_inputs(self) -> Tuple[str, bytes, int]:
        input_path = self.query_one("#input-path", Input).value.strip()
        if not input_path:
            raise ValueError("input path is required.")
        if not self.app0_segment_info:
            raise ValueError("APP0 not loaded. Click Load Info first.")
        payload = self._build_app0_payload()
        length_field = self._app0_length_from_ui(payload)
        return input_path, payload, length_field

    def _app0_length_from_ui(self, payload: bytes) -> int:
        if not self.query_one("#app0-manual-length", Checkbox).value:
            return len(payload) + 2
        length_text = self.query_one("#app0-length", Input).value.strip()
        if not length_text:
            raise ValueError("length is required in manual mode.")
        try:
            length_field = int(length_text, 16)
        except ValueError:
            raise ValueError("length must be hex (e.g., 0010).")
        if length_field < 2:
            raise ValueError("length must be >= 2.")
        return length_field

    def _app0_write_file(self, input_path: str, payload: bytes, length_field: int) -> Path:
        offset, total_len, _, _ = self.app0_segment_info
        data = Path(input_path).read_bytes()
        marker = data[offset:offset + 2]
        new_seg = marker + length_field.to_bytes(2, "big") + payload
        new_data = data[:offset] + new_seg + data[offset + total_len:]
        out_path = Path(input_path).with_name(Path(input_path).stem + "_app0_edit.jpg")
        idx = 1
        while out_path.exists():
            out_path = Path(input_path).with_name(Path(input_path).stem + f"_app0_edit_{idx}.jpg")
            idx += 1
        out_path.write_bytes(new_data)
        return out_path

    def _app0_save_log(self, out_path: Path, payload: bytes, length_field: int) -> None:
        log = self.query_one("#info-app0", RichLog)
        log.write(f"Saved edited file: {out_path}")
        if self.query_one("#app0-manual-length", Checkbox).value:
            expected = len(payload) + 2
            if length_field != expected:
                log.write(f"Warning: manual length {length_field} does not match payload ({expected}).")

    def _refresh_app0_preview(self) -> None:
        """
        Re-render APP0 decoded and hex views based on current editor state.
        """
        if not self.app0_segment_info:
            return
        offset, total_len, _, payload_offset = self.app0_segment_info
        app0_log = self.query_one("#info-app0", RichLog)
        err = self.query_one("#app0-edit-error", Static)
        try:
            payload = self._build_app0_payload()
        except Exception as e:
            err.update(f"Error: {e}")
            return
        err.update("")
        length_field = self._preview_length_from_ui(payload, err)
        if length_field is None:
            return
        app0_log.clear()
        self._write_app0_preview_header(app0_log, offset, length_field, payload)
        ranges = self._preview_ranges(payload)
        segment_bytes = self._preview_segment_bytes(payload, length_field)
        for line in self._hex_dump(segment_bytes, 0, len(segment_bytes), ranges):
            app0_log.write(line)

    def _preview_length_from_ui(self, payload: bytes, err: Static) -> Optional[int]:
        length_field = len(payload) + 2
        if not self.query_one("#app0-manual-length", Checkbox).value:
            return length_field
        length_text = self.query_one("#app0-length", Input).value.strip()
        if not length_text:
            return length_field
        try:
            return int(length_text, 16)
        except ValueError:
            err.update("Error: length must be hex (e.g., 0010).")
            return None

    def _write_app0_preview_header(self, app0_log: RichLog, offset: int, length_field: int, payload: bytes) -> None:
        app0_log.write("Legend:")
        for label, style in [
            ("Identifier (JFIF\\0)", "green"),
            ("Version", "bright_blue"),
            ("Units", "magenta"),
            ("X density", "bright_cyan"),
            ("Y density", "bright_cyan"),
            ("X thumbnail", "bright_yellow"),
            ("Y thumbnail", "bright_yellow"),
            ("Thumbnail data", "red"),
        ]:
            app0_log.write(Text("  " + label, style=style))
        decoded = decode_app0(payload)
        app0_log.write(f"APP0 at 0x{offset:08X} length=0x{length_field:04X} payload={len(payload)}")
        if decoded:
            self._write_decoded_lines(app0_log, decoded)
        else:
            app0_log.write("Decoded: None (payload not recognized as JFIF/JFXX)")

    def _write_decoded_lines(self, app0_log: RichLog, decoded) -> None:
        app0_log.write("Decoded:")
        if "type" in decoded:
            ident = decoded["type"]
            if ident in {"JFIF", "JFXX"}:
                ident = ident + "\\0"
            app0_log.write(Text(f"  Identifier: {ident}", style="green"))
        if "version" in decoded:
            app0_log.write(Text(f"  Version: {decoded['version']}", style="bright_blue"))
        if "units" in decoded:
            units_map = {"0": "none", "1": "dpi", "2": "dpcm"}
            units_label = units_map.get(decoded["units"], "unknown")
            app0_log.write(Text(f"  Units: {decoded['units']} ({units_label})", style="magenta"))
        if "x_density" in decoded:
            app0_log.write(Text(f"  X density: {decoded['x_density']}", style="bright_cyan"))
        if "y_density" in decoded:
            app0_log.write(Text(f"  Y density: {decoded['y_density']}", style="bright_cyan"))

    def _preview_ranges(self, payload: bytes):
        # Synthetic segment layout: [marker][length][payload]
        marker_start, marker_end = 0, 2
        length_start, length_end = 2, 4
        payload_start = 4
        payload_end = payload_start + len(payload)
        ranges = [
            (marker_start, marker_end, "bold yellow"),
            (length_start, length_end, "bold cyan"),
        ]
        if len(payload) < 14:
            return ranges
        ranges.extend(
            [
                (payload_start, payload_start + 5, "green"),
                (payload_start + 5, payload_start + 7, "bright_blue"),
                (payload_start + 7, payload_start + 8, "magenta"),
                (payload_start + 8, payload_start + 10, "bright_cyan"),
                (payload_start + 10, payload_start + 12, "bright_cyan"),
                (payload_start + 12, payload_start + 13, "bright_yellow"),
                (payload_start + 13, payload_start + 14, "bright_yellow"),
            ]
        )
        thumb_w = payload[12]
        thumb_h = payload[13]
        thumb_bytes = 3 * thumb_w * thumb_h
        thumb_start = payload_start + 14
        thumb_end = min(payload_end, thumb_start + thumb_bytes)
        if thumb_bytes > 0:
            ranges.append((thumb_start, thumb_end, "red"))
        return ranges

    def _preview_segment_bytes(self, payload: bytes, length_field: int) -> bytes:
        header = bytearray()
        header.extend(b"\xFF\xE0")
        header.extend(length_field.to_bytes(2, "big"))
        return bytes(header) + payload

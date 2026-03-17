from __future__ import annotations

from textual import on
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Label, ListItem, ListView, RichLog, Static
from rich.text import Text


class TuiHexMixin:
    def _build_full_hex_pane(self) -> Vertical:
        return Vertical(
            Horizontal(
                Button("Prev", id="hex-prev"),
                Button("Next", id="hex-next"),
                Label("Page", classes="field"),
                Input(value="1", id="hex-page"),
                Label("Jump", classes="field"),
                Input(value="", id="hex-jump", placeholder="Page #"),
                Button("Go", id="hex-go"),
                Static("", id="hex-page-info"),
                classes="row",
            ),
            Horizontal(
                RichLog(id="info-hex", highlight=True),
                ListView(id="info-hex-legend"),
                classes="row",
            ),
            id="hex-panel",
        )

    @on(Button.Pressed, "#hex-prev")
    def _on_hex_prev(self) -> None:
        if self.info_data is None:
            return
        if self.hex_page > 0:
            self.hex_page -= 1
            self._render_full_hex_page()

    @on(Button.Pressed, "#hex-next")
    def _on_hex_next(self) -> None:
        if self.info_data is None:
            return
        total = self._hex_total_pages()
        if self.hex_page + 1 < total:
            self.hex_page += 1
            self._render_full_hex_page()

    @on(Input.Changed, "#hex-page")
    def _on_hex_page_changed(self, event: Input.Changed) -> None:
        if self.info_data is None:
            return
        text = event.input.value.strip()
        if not text:
            return
        try:
            page = int(text) - 1
        except ValueError:
            return
        total = self._hex_total_pages()
        if 0 <= page < total:
            self.hex_page = page
            self._render_full_hex_page()

    @on(ListView.Selected, "#info-hex-legend")
    def _on_hex_legend_selected(self, event: ListView.Selected) -> None:
        if self.info_data is None:
            return
        item_id = event.item.id if event.item else None
        if not item_id or item_id not in self.hex_legend_offsets:
            return
        offset = self.hex_legend_offsets[item_id]
        page = offset // 512
        total = self._hex_total_pages()
        if 0 <= page < total:
            self.hex_page = page
            self._render_full_hex_page()

    @on(Button.Pressed, "#hex-go")
    def _on_hex_go(self) -> None:
        if self.info_data is None:
            return
        text = self.query_one("#hex-jump", Input).value.strip()
        if not text:
            return
        try:
            page = int(text) - 1
        except ValueError:
            return
        total = self._hex_total_pages()
        if 0 <= page < total:
            self.hex_page = page
            self._render_full_hex_page()

    def _hex_total_pages(self) -> int:
        if not self.info_data:
            return 0
        return max(1, (len(self.info_data) + 511) // 512)

    def _hex_segment_ranges(self) -> list[Tuple[int, int, str]]:
        if not self.info_segments:
            return []
        ranges: list[Tuple[int, int, str]] = []
        for idx, seg in enumerate(self.info_segments):
            start = seg.offset
            end = seg.offset + seg.total_length
            ranges.append((start, end, self._segment_color(idx)))
        return ranges

    def _segment_color(self, idx: int) -> str:
        # Deterministic bright colors with good separation.
        hue = (idx * 0.61803398875) % 1.0
        sat = 0.65
        val = 0.95
        r, g, b = self._hsv_to_rgb(hue, sat, val)
        return f"#{r:02X}{g:02X}{b:02X}"

    def _hsv_to_rgb(self, h: float, s: float, v: float) -> tuple[int, int, int]:
        i = int(h * 6.0)
        f = (h * 6.0) - i
        p = v * (1.0 - s)
        q = v * (1.0 - f * s)
        t = v * (1.0 - (1.0 - f) * s)
        i = i % 6
        if i == 0:
            r, g, b = v, t, p
        elif i == 1:
            r, g, b = q, v, p
        elif i == 2:
            r, g, b = p, v, t
        elif i == 3:
            r, g, b = p, q, v
        elif i == 4:
            r, g, b = t, p, v
        else:
            r, g, b = v, p, q
        return int(r * 255), int(g * 255), int(b * 255)

    def _render_full_hex_page(self) -> None:
        if self.info_data is None:
            return
        legend = self.query_one("#info-hex-legend", ListView)
        log = self.query_one("#info-hex", RichLog)
        legend.clear()
        log.clear()
        page = max(0, self.hex_page)
        total = self._hex_total_pages()
        page = min(page, total - 1)
        self.hex_page = page
        start = page * 512
        end = min(start + 512, len(self.info_data))
        info = self.query_one("#hex-page-info", Static)
        info.update(f"Page {page + 1}/{total}  0x{start:08X}..0x{end - 1:08X}")
        self.query_one("#hex-page", Input).value = str(page + 1)
        ranges = self._hex_segment_ranges()
        self._write_hex_legend(legend, ranges)
        for line in self._hex_dump(self.info_data, start, end - start, ranges):
            log.write(line)
        log.scroll_to(0, animate=False)

    def _write_hex_legend(self, legend: ListView, ranges: list[Tuple[int, int, str]]) -> None:
        if not self.info_segments:
            return
        self.hex_legend_counter += 1
        self.hex_legend_offsets = {}
        for idx, ((start, end, style), seg) in enumerate(zip(ranges, self.info_segments)):
            item_id = f"hex-seg-{self.hex_legend_counter}-{idx}"
            label = f"{seg.name} 0x{start:08X}..0x{end - 1:08X} ({end - start} bytes)"
            legend.append(ListItem(Label(Text(label, style=style)), id=item_id))
            self.hex_legend_offsets[item_id] = start

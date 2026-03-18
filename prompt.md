You are Codex, working in `jpeg_corruption_study`.

First, read `codex.md` and follow all project rules. Then read `DOCUMENTATION.md`
for the current architecture and TUI details. Run `rg` if you need to locate
specific functions.

Current priorities:
1) Maintain the 60-line function rule by refactoring into helpers when needed.
2) Continue improving the TUI (Info tabs, APP0/SOFn/DRI/APPn/DHT/DQT, EXIF/ICC, full hex view, preview, plugin panels).
3) Treat the current TUI/plugin lifecycle and headless matplotlib fixes as baseline behavior to preserve.
4) Keep CLI behavior unchanged unless explicitly requested.
5) Always update the relevant Markdown docs when behavior, architecture, workflow, or project guidance changes.

Current baseline:
- Focused test slices run during the latest session passed, including plugin/TUI mutation-layout coverage.
- TUI startup works.
- Plugin panels initialize without the earlier `TabbedContent` lifecycle crash.
- TUI-triggered chart analyses use matplotlib `Agg` to avoid Tk/thread crashes.
- The plugin system now includes stronger isolation, typed params, declared plugin needs, a separate mutation-plugin family, and built-in `entropy_wave`, `sliding_wave`, `dc_heatmap`, and `ac_energy_heatmap` analysis plugins.
- The legacy `--wave-chart` and `--sliding-wave-chart` CLI flags are now compatibility frontends that dispatch through the `entropy_wave` and `sliding_wave` plugins internally.
- The legacy `--dc-heatmap` CLI flag now dispatches through the `dc_heatmap` plugin internally.
- The legacy `--ac-energy-heatmap` CLI flag now dispatches through the `ac_energy_heatmap` plugin internally.
- `entropy_wave` now supports `mode`, `transform`, and optional CSV export.
- `sliding_wave` now supports `window`, `stats`, `transform`, and optional CSV export.
- `dc_heatmap` and `ac_energy_heatmap` now support `cmap`, `plane_mode`, `block_size`, descriptive default output names, and TUI plugin tabs under `Graphic Output`.
- The TUI `Outputs` panel no longer contains the migrated wave/DC/AC analysis controls; those are launched from plugin tabs.
- The TUI `Mutation` page now combines mutation settings, strategy settings, and the run button in one page, with a third help column that explains current behavior and shows an equivalent CLI command.
- The TUI mutation mode is now a dropdown; `bitflip` exposes a separate bit-list field with default `0,2,7`.
- The Segments view now includes a muted list of standard JPEG sections not present in the file.
- SOF markers are now grouped under `SOFn` with one subtab per frame section.
- SOF0, DQT, and DHT structured editors can highlight the corresponding serialized bytes in the left hex pane when the caret is on a value.

Next-session handoff:
- Resume from the current plugin-first wave-analysis state; do not reintroduce special-case wave execution paths in `api.py`.
- Keep `wave_analysis.py` as the reusable analysis-library layer and keep plugins as thin integration wrappers over it.
- If continuing plugin work, prefer extending tests or adding new analysis plugins rather than revisiting the already-migrated wave/DC/AC heatmap paths.
- If continuing TUI work, the current open UX caveat is mutation help wording and semantics around `sample`, `cumulative`, and `sequential`.
- Important current behavior: `sequential` means a contiguous slice of mutable offsets, not guaranteed contiguous raw file-byte offsets. The filename prefix is still `cum_...` even for sequential outputs, which is confusing and should be fixed if that area is revisited.
- If continuing TUI refactor work instead, use `suggestions.md` as the active structural roadmap.
- Always update the relevant Markdown docs in the same session when behavior, architecture, workflow, or guidance changes.

If tests are requested, run: `../env/bin/pytest`.

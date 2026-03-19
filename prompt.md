You are Codex, working in `jpeg_corruption_study`.

First, read `codex.md` and follow all project rules. Then read `DOCUMENTATION.md`
for the current architecture and TUI details. Run `rg` if you need to locate
specific functions.

Current priorities:
1) Maintain the 60-line function rule by refactoring into helpers when needed.
2) Continue improving the TUI (Info tabs, APP0/SOFn/SOS/DRI/APPn/DHT/DQT/Trace, EXIF/ICC, full hex view, preview, plugin panels).
3) Treat the current TUI/plugin lifecycle and headless matplotlib fixes as baseline behavior to preserve.
4) Keep CLI behavior unchanged unless explicitly requested.
5) Always update the relevant Markdown docs when behavior, architecture, workflow, or project guidance changes.

Current baseline:
- The latest focused TUI/plugin verification passed. Recent slices:
  - `71 passed` for `tests/test_tui_segments.py tests/test_tui_plugins.py tests/test_tui_app2.py tests/test_mutation_plugins_builtin.py`
  - `20 passed` for `tests/test_tui_plugins.py tests/test_tui_options.py tests/test_tui_app2.py`
- TUI startup works.
- Plugin panels initialize without the earlier `TabbedContent` lifecycle crash.
- The TUI Trace workspace now guards against stale-widget crashes during rapid image switching and Info-panel rebuilds.
- TUI-triggered chart analyses use matplotlib `Agg` to avoid Tk/thread crashes.
- The plugin system now includes stronger isolation, typed params, declared plugin needs, a separate mutation-plugin family, and built-in `entropy_wave`, `sliding_wave`, `dc_heatmap`, and `ac_energy_heatmap` analysis plugins.
- Built-in mutation plugins `55`, `aa`, and `insert_appn` now exist, live under `jpeg_fault/core/plugins/`; `55` and `aa` are exposed in the TUI under `Plugin Mutations`, while `insert_appn` is exposed under the plugin-hosted `Tools` panel.
- Mutation plugins now receive shared strategy context (`mutation_apply`, `repeats`, `step`) through `MutationContext`.
- The built-in fixed-byte mutation plugins now honor shared strategy instead of behaving as independent-only writers.
- Mutation-plugin TUI tabs now use a dedicated two-panel layout: params/run controls on the left, explanatory help text on the right.
- The legacy `--wave-chart` and `--sliding-wave-chart` CLI flags are now compatibility frontends that dispatch through the `entropy_wave` and `sliding_wave` plugins internally.
- The legacy `--dc-heatmap` CLI flag now dispatches through the `dc_heatmap` plugin internally.
- The legacy `--ac-energy-heatmap` CLI flag now dispatches through the `ac_energy_heatmap` plugin internally.
- `entropy_wave` now supports `mode`, `transform`, and optional CSV export.
- `sliding_wave` now supports `window`, `stats`, `transform`, and optional CSV export.
- `dc_heatmap` and `ac_energy_heatmap` now support `cmap`, `plane_mode`, `block_size`, descriptive default output names, and TUI plugin tabs under `Graphic Output`.
- A new built-in `entropy_trace` analysis plugin now exists and is backed by a reusable `jpeg_fault/core/entropy_trace.py` baseline scan tracer.
- The first `entropy_trace` slice writes text or JSON artifacts per JPEG, one trace stream per `SOS`, with block-level bit spans, file-byte provenance, table provenance, and decoded coefficient traces for baseline sequential scans.
- The TUI Info panel now includes a `Trace` workspace with one tab per scan, a paged block list, and selected-block detail pages backed by `entropy_trace.py`.
- Progressive/refinement scans are recognized structurally by `entropy_trace` but are not yet fully block-traced.
- The TUI `Outputs` panel no longer contains the migrated wave/DC/AC analysis controls; those are launched from plugin tabs.
- The TUI `Core Mutations` page now combines mutation settings, strategy settings, and the run button in one page, with a third help column that explains current behavior and shows an equivalent CLI command.
- The TUI mutation mode is now a dropdown; `bitflip` exposes a separate bit-list field with default `0,2,7`.
- The old dedicated `Tools` APPn writer path was removed; APPn insertion now goes through the `insert_appn` mutation plugin while `jpg_fault_tools.py insert-appn` remains as a compatibility CLI helper.
- The generic `Plugins` panel is now a read-only clickable analysis inventory; it no longer selects analysis plugins for the main run flow.
- The Segments view now includes a muted list of standard JPEG sections not present in the file.
- Entropy-coded scan ranges now live inside the `Segments` view instead of a standalone `Entropy` tab.
- SOF markers are now grouped under `SOFn` with one subtab per frame section.
- SOS markers now have a dedicated editable workspace with header/components/flow/links/edit views.
- SOF0, SOS, DQT, and DHT structured editors can highlight the corresponding serialized bytes in the left hex pane when the caret is on a value.
- The SOF0 structured editor now exposes `component_count`, and the SOS structured editor now exposes `ns`, so count bytes and first component ids highlight separately.
- The real TUI implementation lives under `jpeg_fault/core/tui/`; imports and tests should target that package directly.
- Shared plugin context building now lives outside `api.py` so both the API layer and TUI can use it without reaching into API-private helpers.
- Plugin discovery/loading now goes through a shared helper used by both analysis and mutation registries.
- APP2 editor plumbing now centralizes ICC field collection/update generation, and APP2 preview refresh is wired consistently across all edit inputs.
- JPEG/EXIF/ICC protocol constants now live under `jpeg_fault/core/constants/` and should be reused instead of reintroducing inline magic mappings.
- The old TUI compatibility shims, old mutation plugin tree, and unused debug instrumentation scaffolding have all been removed.
- JPEG selection now defers the expensive Info-panel rebuild until after the selection event/refresh cycle and uses a tokenized latest-selection guard.
- Dynamic Info-panel `TabPane` ids now include a rebuild generation to reduce duplicate-id collisions while old nested tabs are still tearing down.
- Important verification rule: when changing Info-panel or Trace workspace code, explicitly test rapid JPEG switching and repeated Info/Trace navigation so stale widget events do not crash the TUI with `NoMatches`.
- Important verification rule: when changing SOFn or SOS panes, explicitly test image reloads after switching files so pane-scoped widget lookup and nested-tab mounting still target the current root.
- When `Debug logging` is enabled, targeted diagnostics can write to `/tmp/jpeg_trace_debug.log`, `/tmp/jpeg_sos_debug.log`, and `/tmp/jpeg_sof_debug.log`.

Next-session handoff:
- Resume from the current plugin-first wave-analysis state; do not reintroduce special-case wave execution paths in `api.py`.
- Keep `wave_analysis.py` as the reusable analysis-library layer and keep plugins as thin integration wrappers over it.
- Keep `entropy_trace.py` as the reusable entropy tracing library layer and keep the `entropy_trace` plugin as a thin integration wrapper over it.
- Keep all built-in plugin implementations under `jpeg_fault/core/plugins/<plugin_name>/plugin.py`.
- Keep the TUI implementation in `jpeg_fault/core/tui/`.
- If continuing plugin work, prefer extending tests or adding new analysis plugins rather than revisiting the already-migrated wave/DC/AC heatmap paths.
- If continuing entropy-trace work, the next high-value steps are byte-boundary highlighting polish, better block navigation UX, and broader progressive JPEG support on top of the existing TUI Trace workspace.
- If continuing TUI work, the highest-value unfinished correctness refactor is still the nested `TabbedContent` rebuild model in the Info panel. The code is more defensive now, but the long-term fix is to stop destructively rebuilding those nested tab trees on image switch.
- If continuing TUI work, keep regression coverage around stale-event races in both APP0 and Trace workspace rendering paths during rapid image switching.
- If continuing TUI/plugin work, preserve the current panel split:
  - `Plugin Mutations` hosts entropy-byte mutation plugins like `55` and `aa`
  - plugin-hosted `Tools` currently hosts `insert_appn`
  - the generic `Plugins` panel is informational/clickable only
- The current open mutation-plugin UX caveat is right-panel help wording and explanatory depth around `sample`, staged outputs, `cumulative`, and `sequential`.
- Important current behavior: `sequential` means a contiguous slice of mutable offsets, not guaranteed contiguous raw file-byte offsets. The filename prefix is still `cum_...` even for sequential outputs, which is confusing and should be fixed if that area is revisited.
- If continuing TUI refactor work instead, use `suggestions.md` as the active structural roadmap.
- Always update the relevant Markdown docs in the same session when behavior, architecture, workflow, or guidance changes.

If tests are requested, run: `../env/bin/pytest`.

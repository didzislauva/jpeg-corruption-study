# Refactor Suggestions For Next Codex Session

You are working in `jpeg_corruption_study`.

Your goal in this session is still structural improvement first, not feature growth first. The difference from earlier sessions is that some of the original refactor work has already been done, so this note focuses on what is still actually worth doing now.

## Current Situation

The repository already has a decent high-level split in `jpeg_fault/core/`:

- `jpeg_parse.py` for parsing and payload encode/decode helpers
- `report.py` for textual JPEG reporting
- `mutate.py` for entropy-byte mutation logic
- `api.py` for orchestration
- `cli.py` for CLI wiring
- `tui/` package for the real Textual UI implementation

Recent baseline that should be preserved:

- Plugin menu insertion matches the real `ListView` API.
- Plugin panel initialization respects Textual's widget lifecycle.
- Chart-producing analyses force matplotlib to `Agg`, preventing TUI-thread Tk crashes.
- Mutation plugins now receive shared strategy fields (`mutation_apply`, `repeats`, `step`) in `MutationContext`.
- Built-in fixed-byte mutation plugins now honor shared strategy instead of behaving as independent-only writers.
- Mutation-plugin TUI tabs now use a dedicated two-column layout: params on the left, explanatory help on the right.
- The wave-analysis path is now plugin-first: `--wave-chart` and `--sliding-wave-chart` dispatch through `entropy_wave` and `sliding_wave` internally.
- `entropy_wave` supports `mode`, `transform`, and optional CSV export.
- `sliding_wave` supports `window`, `stats`, `transform`, and optional CSV export.
- Behavior, architecture, and workflow changes should always be reflected in the relevant Markdown docs in the same session.

Recent architecture work that is now done:

- the real TUI implementation was moved into `jpeg_fault/core/tui/`
- built-in plugins now live under `jpeg_fault/core/plugins/<plugin_name>/plugin.py`
- built-in mutation plugins `55` and `aa` exist and are exposed in the TUI under `Plugin Mutations`
- the main built-in mutation page in the TUI is now labeled `Core Mutations`
- the old TUI compatibility alias modules are gone
- the old `jpeg_fault/core/mutation_plugins/` tree is gone
- unused debug instrumentation scaffolding is gone

## What Changed Since The Earlier Refactor Note

Some of the earlier suggestions are no longer aspirational; they are already partly implemented.

These shared helpers now exist in `jpeg_fault/core/tui/app.py` and should be treated as the baseline abstraction layer:

- shared manual-length parsing
- shared edited-file writing
- shared save logging
- shared preview refresh for single-segment editors
- shared preview refresh for keyed/multi-segment editors
- shared structured-to-raw and raw-to-structured mode sync helpers

That means the biggest problem is no longer "everything is duplicated equally." The actual remaining issue is uneven adoption of those helpers across the TUI code.

The plugin architecture also changed meaningfully:

- analysis plugins now declare typed params and explicit host-data needs
- mutation plugins now have a separate family/registry
- built-in wave analyses have already been migrated onto the plugin execution path
- built-in plugin placement is now folder-per-plugin under the shared `jpeg_fault/core/plugins/` root
- plugin context building now lives in a shared helper layer instead of API-private functions
- plugin package scanning/import logic is now centralized instead of duplicated across registries
- JPEG/EXIF/ICC protocol constants now live under `jpeg_fault/core/constants/` and should be extended there instead of being copied inline

That means the next session should not spend time redesigning plugin basics again unless a real blocker appears.

## Primary Objective

Continue the TUI refactor by moving the remaining bespoke editors and save/preview flows onto the shared helper patterns that already exist.

Do this without changing visible behavior unless the refactor exposes a real bug.

Preserve:

- current CLI behavior
- current tests
- current TUI features
- current save-as-new-file behavior
- current live preview behavior
- current plugin lifecycle behavior
- current headless matplotlib behavior

## What Is Still True

The TUI is still the main maintainability risk.

These files are still large and still cost too much context to edit safely:

- `jpeg_fault/core/tui/app.py`
- `jpeg_fault/core/tui/segments_basic.py`
- `jpeg_fault/core/tui/segments_tables.py`
- `jpeg_fault/core/tui/segments_appn.py`

APP1 and APP2 are still more custom than the SOF0/DRI/DQT editors.

DHT is only partially on the shared path because its preview flow still has a lenient raw-hex fallback that is not expressed through the generic keyed preview helper.

TUI test coverage is better than before, but it is still mostly fake-widget and unit-style coverage rather than true runtime-heavy Textual coverage.

Recent TUI cleanup has improved consistency in a few places that should now be treated as baseline:

- SOF markers are grouped under a keyed `SOFn` pane instead of assuming a single `SOF0` workspace.
- SOF0, DQT, and DHT now support value-to-byte highlighting in their structured editors.
- the Segments pane now shows unused standard JPEG sections in a muted list under the detected segments.
- APP2 ICC field collection/update generation is now grouped through dedicated helpers instead of being spread inline across the save path.
- APP2 preview refresh is now wired consistently for all edit inputs, including XYZ and TRC fields.
- JPEG/EXIF/ICC protocol mappings now live under `jpeg_fault/core/constants/`.
- image-driven Info-panel reload work is now deferred until after the selection event/refresh cycle.
- dynamic nested Info-pane `TabPane` ids now include a rebuild generation to reduce duplicate-id collisions.
- the latest focused TUI/plugin suite is green at `56 passed`.

## Constraints

- Follow the project’s 60-line function guideline where practical.
- Keep behavior stable unless a bug must be fixed.
- Prefer extracting small helpers over introducing a new framework.
- Avoid abstractions that are more complex than the repeated code they replace.
- Use `apply_patch` for edits.
- Run tests with `../env/bin/pytest` when tests are requested or when the change materially affects behavior.
- Update the relevant Markdown docs whenever the code changes meaningfully.

## Recommended Work

### 1. Replace Destructive Nested-Tab Rebuilds

The main remaining correctness risk is the nested `TabbedContent` rebuild pattern itself.

Current code is more defensive than before:

- many missing-widget paths are now guarded
- image switching is tokenized/deferred
- dynamic pane ids are generation-scoped

But the long-term correct fix is still:

- stop destroying and recreating nested Info-panel tab trees on every image switch
- keep stable workspace containers per segment family
- refresh content inside them instead of repeatedly calling `clear_panes()` and remounting everything

If a future session continues TUI stabilization, prioritize this over more one-off `NoMatches` / `DuplicateIds` patches.

### 2. Finish Normalizing Segment Editor Mechanics

The next structural target after the nested-tab fix is to make APP1 and DHT look more like the already-refactored SOF0/DRI/DQT and now-cleaner APP2 flows.

Recent progress that should now be treated as baseline:

- APP1 and APP2 edited-file saves now use the shared segment rewrite helper instead of rebuilding files manually.
- APP2 preview refresh now goes through the keyed preview helper path.
- APP2 ICC update collection is now centralized instead of being built inline in `_app2_save_inputs`.
- DHT lenient raw-hex recovery now plugs into the keyed preview helper via a warning-producing fallback hook.

Focus on:

- common input-path validation
- common segment-loaded validation
- common save logging
- common preview refresh structure

The goal is not to force every editor into the exact same mold. The goal is to eliminate avoidable plumbing differences.

### 3. Keep Normalizing APP1/APP2 Plumbing

APP1 no longer rewrites files manually, and APP2 cleanup progressed, but `jpeg_fault/core/tui/segments_appn.py` is still heavy.

The next useful extractions are likely:

- EXIF dict parsing/validation
- more APP1-oriented preview-data/render helper grouping
- preview-data/render helper grouping

### 4. Keep DHT Recovery On The Shared Preview Path

DHT no longer needs a bespoke preview refresh function just to support lenient raw-hex recovery.

That behavior is useful and should not be removed casually.

The remaining work here is mostly regression resistance:

- keep strict-mode errors intact
- keep lenient preview warnings intelligible
- keep tests around raw-hex typing edge cases

### 5. Reduce Size Pressure In `jpeg_fault/core/tui/segments_appn.py`

`jpeg_fault/core/tui/segments_appn.py` remains one of the heaviest modules.

Before adding more APPn features, consider extracting focused helpers for:

- EXIF dict parsing and validation
- ICC tag update collection
- ICC profile rebuild logic
- APP1/APP2 payload-build plumbing

Do not split blindly. Extract only where the helper becomes easier to test and easier to reason about than the inlined version.

### 6. Keep The TUI Package As The Only Import Path

The real code now lives only in `jpeg_fault/core/tui/`, and tests/imports should stay on `jpeg_fault.core.tui.*`.

Guardrails:

- keep new tests and internal imports on `jpeg_fault.core.tui.*`
- avoid reintroducing flat `jpeg_fault.core.tui_*` shims

This cleanup is complete and should stay complete.

### 7. Improve Internal Grouping In The TUI Modules

The TUI mixins are split, but related methods are still spread out enough that maintenance is expensive.

Prefer grouping methods in this order where practical:

1. widget construction
2. tab initialization
3. render helpers
4. payload parse/serialize helpers
5. preview/update helpers
6. save helpers
7. event handlers

This matters because the next engineer should be able to find the full workflow for one editor without jumping around the file excessively.

### 8. Keep Pushing Encode/Decode Logic Out Of The TUI

`jpeg_parse.py` already acts as more than a parser; it is also a lightweight payload encode/decode layer for editable segments.

Continue leaning into that when it reduces UI complexity.

Good candidates:

- more normalization helpers for APP1/APP2 payload structures
- validation helpers that are currently embedded directly in TUI event paths

Bad candidates:

- moving UI-specific state transitions into parser code

### 9. Mutation Plugin UX Follow-Through

Now that mutation plugins support shared strategy and have dedicated two-panel TUI tabs, the next worthwhile polish is:

- improve right-panel help text so it explains staged outputs more concretely
- decide whether mutation-plugin tabs should eventually surface shared strategy controls directly or continue to read them only from the `Core Mutations` page
- consider showing example output naming for `independent`, `cumulative`, and `sequential`

The architectural direction should remain:

- strategy is shared host/framework behavior
- mutation plugins should not each reinvent their own strategy model

### 10. Add Higher-Value TUI Tests

The current tests cover many helper flows, but the next testing gains are probably in behavior-oriented integration checks rather than more fake-widget plumbing tests.

Good targets:

- mode switch behavior under invalid editor states
- save flow for APP1/APP2 after refactors
- plugin panel behavior with real-ish widget lifecycles
- end-to-end preview/save behavior for more than one segment type in one session

## Plugin Cleanup Notes

The plugin implementation layout is now in a better place than before.

Recent cleanup that should be treated as baseline:

- shared fixed-byte mutation support code now lives in `jpeg_fault/core/mutation_plugin_helpers.py`
- the stale `jpeg_fault/core/mutation_plugins/` tree has been removed

Keep watching for any no-longer-used plugin loader paths or empty directories left behind by the refactor.

## What Not To Spend Time On First

- Do not re-split the TUI modules again unless a very clear seam appears.
- Do not rewrite the plugin system just because it exists; it is not the main bottleneck right now.
- Do not change CLI behavior unless explicitly requested.
- Do not add a new feature first if the same session could remove a chunk of structural duplication instead.

## Practical Next Step

If starting a refactor session from this note, the best next move is usually:

1. inspect the nested Info-panel rebuild paths for `SOF`, `APPn`, `DQT`, and `DHT`
2. replace destructive nested-tab recreation with stable workspaces/content refresh where practical
3. preserve DHT lenient preview coverage while avoiding new special cases
4. add or update tests around those changes before moving on

If starting a plugin-extension session instead, the best next move is usually:

1. leave `wave_analysis.py` and plugin-shared helpers like `plugins/_shared/dct_heatmap.py` as reusable analysis-library layers
2. add another optional analysis through the existing plugin path instead of adding a special-case CLI branch
3. register a TUI plugin tab only if the analysis has a clear interactive workflow
4. keep the plugin implementation under `jpeg_fault/core/plugins/<plugin_name>/plugin.py`
5. update `README.md` and `DOCUMENTATION.md` in the same session

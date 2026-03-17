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
- `tui_app.py` plus TUI mixin modules for the Textual UI

Recent baseline that should be preserved:

- Plugin menu insertion matches the real `ListView` API.
- Plugin panel initialization respects Textual's widget lifecycle.
- Chart-producing analyses force matplotlib to `Agg`, preventing TUI-thread Tk crashes.
- The repo currently passes `94` tests via `../env/bin/pytest -q`.
- The wave-analysis path is now plugin-first: `--wave-chart` and `--sliding-wave-chart` dispatch through `entropy_wave` and `sliding_wave` internally.
- `entropy_wave` supports `mode`, `transform`, and optional CSV export.
- `sliding_wave` supports `window`, `stats`, `transform`, and optional CSV export.
- Behavior, architecture, and workflow changes should always be reflected in the relevant Markdown docs in the same session.

## What Changed Since The Earlier Refactor Note

Some of the earlier suggestions are no longer aspirational; they are already partly implemented.

These shared helpers now exist in `tui_app.py` and should be treated as the baseline abstraction layer:

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

- `jpeg_fault/core/tui_app.py`
- `jpeg_fault/core/tui_segments_basic.py`
- `jpeg_fault/core/tui_segments_tables.py`
- `jpeg_fault/core/tui_segments_appn.py`

APP1 and APP2 are still more custom than the SOF0/DRI/DQT editors.

DHT is only partially on the shared path because its preview flow still has a lenient raw-hex fallback that is not expressed through the generic keyed preview helper.

TUI test coverage is better than before, but it is still mostly fake-widget and unit-style coverage rather than true runtime-heavy Textual coverage.

## Constraints

- Follow the project’s 60-line function guideline where practical.
- Keep behavior stable unless a bug must be fixed.
- Prefer extracting small helpers over introducing a new framework.
- Avoid abstractions that are more complex than the repeated code they replace.
- Use `apply_patch` for edits.
- Run tests with `../env/bin/pytest` when tests are requested or when the change materially affects behavior.
- Update the relevant Markdown docs whenever the code changes meaningfully.

## Recommended Work

### 1. Finish Normalizing Segment Editor Mechanics

The main remaining target is to make APP1, APP2, and DHT look more like the already-refactored SOF0/DRI/DQT flows.

Focus on:

- common input-path validation
- common segment-loaded validation
- common edited-file writing
- common save logging
- common preview refresh structure

The goal is not to force every editor into the exact same mold. The goal is to eliminate avoidable plumbing differences.

### 2. Extract A Shared Helper For APPn Write Flows

APP1 and APP2 still each rebuild output files manually.

That should probably become a shared helper that handles:

- lookup of segment offset and total length
- marker preservation
- replacement segment assembly
- collision-safe output naming

SOF0/DRI/DQT/DHT already lean on a common file-writing helper. APP1/APP2 should move in that direction unless there is a concrete reason not to.

### 3. Unify DHT Preview Logic If Possible

DHT still has a partially custom preview path because it supports lenient recovery when the raw hex editor is temporarily invalid while typing.

That behavior is useful and should not be removed casually.

But the current structure should be revisited to see whether the generic keyed preview helper can support:

- strict mode
- lenient preview mode with warning text

If that can be done cleanly, DHT can stop being a special case.

### 4. Reduce Size Pressure In `tui_segments_appn.py`

`tui_segments_appn.py` remains one of the heaviest modules.

Before adding more APPn features, consider extracting focused helpers for:

- EXIF dict parsing and validation
- ICC tag update collection
- ICC profile rebuild logic
- APP1/APP2 file-save plumbing

Do not split blindly. Extract only where the helper becomes easier to test and easier to reason about than the inlined version.

### 5. Improve Internal Grouping In The TUI Modules

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

### 6. Keep Pushing Encode/Decode Logic Out Of The TUI

`jpeg_parse.py` already acts as more than a parser; it is also a lightweight payload encode/decode layer for editable segments.

Continue leaning into that when it reduces UI complexity.

Good candidates:

- more normalization helpers for APP1/APP2 payload structures
- validation helpers that are currently embedded directly in TUI event paths

Bad candidates:

- moving UI-specific state transitions into parser code

### 7. Add Higher-Value TUI Tests

The current tests cover many helper flows, but the next testing gains are probably in behavior-oriented integration checks rather than more fake-widget plumbing tests.

Good targets:

- mode switch behavior under invalid editor states
- save flow for APP1/APP2 after refactors
- plugin panel behavior with real-ish widget lifecycles
- end-to-end preview/save behavior for more than one segment type in one session

## What Not To Spend Time On First

- Do not re-split the TUI modules again unless a very clear seam appears.
- Do not rewrite the plugin system just because it exists; it is not the main bottleneck right now.
- Do not change CLI behavior unless explicitly requested.
- Do not add a new feature first if the same session could remove a chunk of structural duplication instead.

## Practical Next Step

If starting a refactor session from this note, the best next move is usually:

1. inspect APP1/APP2 save and preview flows
2. decide whether they can adopt the existing shared file-write/save-log helpers
3. see whether DHT lenient preview can be folded into the keyed preview helper
4. add or update tests around those changes before moving on

If starting a plugin-migration session instead, the best next move is usually:

1. leave `wave_analysis.py` as the reusable library layer
2. migrate another built-in optional analysis onto the plugin path
3. prefer `dc_heatmap` first and `ac_energy_heatmap` second
4. update `README.md` and `DOCUMENTATION.md` in the same session

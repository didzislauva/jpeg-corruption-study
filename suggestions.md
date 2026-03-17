# Refactor Suggestions For Next Codex Session

You are working in `/home/didzis/Projects/jpgInvestigation`.

Your goal in this session is not to add another feature first. Your goal is to improve the codebase structure so future feature work becomes faster, safer, and less repetitive.

Focus on modularity, quality, less repetition, and better orchestration.

## Current Situation

The repository has a good high-level split in `jpeg_fault/core/`:

- `jpeg_parse.py` for parsing and payload decode helpers
- `report.py` for textual JPEG reporting
- `mutate.py` for entropy-byte mutation logic
- `api.py` for orchestration
- `cli.py` for CLI wiring
- `tui_app.py` plus TUI mixin modules for the Textual UI

Recent fixes completed:

- Plugin menu insertion now matches the real `ListView` API.
- Plugin panel initialization now respects Textual's widget lifecycle.
- Chart-producing analyses force matplotlib to `Agg`, preventing TUI-thread Tk crashes.
- Current automated baseline is `88 passed` via `../env/bin/pytest`.

The main structural problem is now the combined TUI surface:

- `jpeg_fault/core/tui_app.py`
- `jpeg_fault/core/tui_segments_basic.py`
- `jpeg_fault/core/tui_segments_tables.py`
- `jpeg_fault/core/tui_segments_appn.py`

These files are still large and have grown by copy-adaptation:

- APP0 has its own editor/workflow
- APP1 and APP2 have their own editor/workflow
- SOF0 has its own editor/workflow
- DRI has its own editor/workflow
- DHT has its own editor/workflow
- DQT has its own editor/workflow

Those workspaces are useful and correct, but they repeat the same lifecycle patterns many times:

- build pane
- init tabs
- render left panel
- render right tabs
- parse structured editor
- parse raw editor
- sync mode switch
- preview updated payload
- manual length handling
- save inputs
- write new file
- save log / warning

This repetition is now the biggest maintainability risk in the repo.

## Primary Objective

Refactor the TUI so it becomes a composition of reusable workspace helpers instead of one giant hand-wired file.

Do this without changing the visible behavior unless the refactor exposes a clear bug.

Preserve:

- current CLI behavior
- current tests
- current TUI features
- current save-as-new-file behavior
- current live preview behavior

## Constraints

- Follow the project’s 60-line function guideline where practical.
- Keep behavior stable unless a bug must be fixed.
- Prefer extracting helpers and small abstractions over large framework rewrites.
- Avoid introducing abstract patterns that are more complex than the duplicated code they replace.
- Use `apply_patch` for edits.
- Run tests with `../env/bin/pytest`.

## What To Improve

### 1. Introduce a Generic Segment Workspace Pattern In The TUI

Create a reusable internal pattern for “segment workspace with left bytes/info and right tabs”.

Candidate abstraction:

- a small dataclass or protocol-like structure describing a workspace
- helper methods for:
  - creating the split layout
  - creating tab sets
  - resolving widget ids from a workspace key
  - common save / preview / manual-length logic

The repeated workspaces that should move toward this pattern:

- SOF0
- DRI
- DHT
- DQT

APP0 can remain somewhat custom because it has a richer field editor, but even APP0 can probably reuse some shared save/preview helpers later.

### 2. Separate “Editor Mechanics” From “Segment Semantics”

Right now, `tui.py` mixes:

- widget plumbing
- structured payload parsing
- payload serialization
- preview update logic
- file write logic

Split these responsibilities.

Suggested direction:

- keep segment-specific payload encode/decode in `jpeg_parse.py` or a new helper module
- keep UI state transitions in `tui.py`
- extract generic editor mechanics into helper methods or a new TUI support module

Examples of mechanics that should be centralized:

- raw vs structured mode visibility
- manual length handling
- save button dirty-state toggling
- preview refresh flow
- save target file naming pattern

### 3. Reduce Duplication In Save / Preview Flows

The following patterns are repeated for SOF0 / DRI / DHT / DQT:

- `_build_*_payload`
- `_*_length_from_ui`
- `_refresh_*_preview`
- `_*_save_inputs`
- `_*_write_file`
- `_*_save_log`

These should become a shared segment-editor flow with only segment-specific payload builders and panel renderers swapped in.

Possible shape:

- one generic helper that:
  - reads current payload from segment-specific builder
  - computes manual or automatic length
  - re-renders preview
  - handles save

Keep the abstraction simple.

Do not build a massive inheritance hierarchy.

### 4. Introduce Shared “Structured Editor <-> Raw Hex” Sync Helpers

The current DHT/DQT mode-switch sync behavior is correct, but the implementation is still repeated and easy to drift.

Create one shared helper for:

- switching from structured view to raw hex
- switching from raw hex to structured view
- explicitly avoiding rewriting the active editor while typing

The only variable should be:

- structured -> payload function
- payload -> structured function

### 5. Improve Internal Naming And Grouping In `tui.py`

The TUI file would benefit from clearer sections grouped by responsibility.

Suggested ordering:

1. widget construction
2. info-tab initialization
3. file browser / input loading
4. generic TUI helpers
5. APP0 workspace
6. SOF0 workspace
7. DRI workspace
8. APP1 / APP2 workspaces
9. DHT workspace
10. DQT workspace
11. hex view
12. save / preview utilities

Right now related methods are spread out enough that it costs too much context to make safe edits.

### 6. Keep The TUI Split Coherent

The old `tui.py` split has already happened. The next step is to make the split cleaner internally, not to split again blindly.

Current split targets already in place:

- `tui_app.py` for `JpegFaultTui`
- `tui_segments_basic.py` for APP0/SOF0/DRI
- `tui_segments_tables.py` for DHT/DQT
- `tui_segments_appn.py` for APP1/APP2
- `tui_hex.py` for full hex pane

What still matters:

- reduce coupling between `tui_app.py` and mixins
- move more common mechanics out of per-segment code
- avoid growing test-only compatibility hacks into the main flow

### 7. Add Better Parser-Level Structures For Segment Editors

`jpeg_parse.py` is already evolving into a useful encode/decode layer.

Keep leaning into that.

Potential improvements:

- add lightweight typed dicts or dataclasses for decoded payloads
- replace generic `Dict[str, object]` where practical in new code
- centralize roundtrip helpers:
  - DQT decode/build
  - DHT decode/build
  - SOF0 decode/build
  - DRI decode/build

This will reduce TUI-side dict juggling.

### 8. Improve Test Structure For TUI Behaviors

There is now real TUI-oriented coverage, but the tests rely on fake widgets and direct method calls.

That is acceptable, but improve the structure:

- centralize fake widget classes into test helpers
- centralize widget-map builders for workspaces
- reduce boilerplate in `tests/test_tui_segments.py`

Possible new helper file:

- `tests/tui_test_helpers.py`

Add clearer categories in tests:

- render tests
- preview tests
- mode-switch sync tests
- save tests
- validation tests
- missing-segment tests

### 9. Review Repetition In Parser And Report Layers Too

The parser and report layers are much healthier than the TUI, but still inspect for easy wins:

- repeated marker/payload slicing
- repeated segment summary formatting
- repeated “decode if payload exists” patterns

Only refactor these if it is clearly helpful.

The TUI is still the main target.

### 10. Preserve User-Facing Documentation Accuracy

After refactoring, update all relevant Markdown docs if behavior or internal organization changes:

- `README.md`
- `DOCUMENTATION.md`
- `codex.md`
- `prompt.md`

Keep them aligned with actual code.

## Suggested Next Session Focus

Do not spend the next session re-fixing the plugin/Tk crash unless it reproduces again with a new traceback. That specific problem has been addressed.

The best next work is:

1. Extract more shared editor/save/preview mechanics from the TUI segment mixins.
2. Add a few more plugin panels or analysis actions now that the plugin shell is stable.
3. Add stronger runtime-oriented TUI tests where possible, especially around plugin execution and panel switching.

## Concrete Deliverables

Aim to finish with:

1. noticeably smaller and better-organized `tui.py`, or a justified split into smaller TUI modules
2. shared helpers removing obvious repetition across SOF0/DRI/DHT/DQT
3. no visible regression in current TUI behavior
4. cleaner tests with less widget boilerplate
5. updated docs if necessary
6. full test pass

## Recommended Execution Order

1. Map repeated TUI workspace patterns.
2. Extract generic editor/save/preview helpers.
3. Refactor SOF0 and DRI onto the shared path first.
4. Refactor DHT and DQT onto the same shared path.
5. Only then consider splitting `tui.py` if still justified.
6. Clean up tests into shared helpers.
7. Run full test suite.
8. Update docs.

## Things To Avoid

- Do not rewrite the TUI into a new architecture in one leap.
- Do not introduce deep inheritance trees.
- Do not change CLI behavior.
- Do not weaken tests just to make refactoring easier.
- Do not remove the live preview/edit-save behavior that already exists.

## Minimum Validation

Run:

```bash
python3 -m py_compile jpeg_fault/core/tui.py jpeg_fault/core/jpeg_parse.py
../env/bin/pytest -q
```

If you split files, update the `py_compile` command accordingly.

## Final Output Expected From Next Session

In the final answer:

- summarize the refactor at a high level
- call out what repetition was removed
- mention any abstractions introduced
- mention whether `tui.py` was split or kept whole
- report test results
- explicitly mention any remaining structural debt that was intentionally deferred

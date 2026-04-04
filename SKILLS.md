# Skills And Lessons From Building This App

This document records the concrete engineering skills, debugging heuristics, and implementation lessons that emerged while building and refining this JPEG investigation tool.

The emphasis is practical:

- what patterns worked in this repository
- what broke repeatedly
- how those bugs were diagnosed
- how similar work should be approached next time

## 1. Architectural Skills

### Keep Frontends Thin

The repo is healthiest when these boundaries stay intact:

- `cli.py` parses arguments
- `api.py` orchestrates workflows
- parser/analysis modules do JPEG-domain work
- the TUI presents and edits state, but does not reimplement core algorithms

This mattered during the Trace work. The right approach was to reuse:

- `jpeg_fault/core/entropy_trace.py`
- `jpeg_fault/core/jpeg_parse.py`
- core quantization/decode helpers

instead of rebuilding entropy or coefficient logic directly in the TUI.

### Separate Domain Logic From Widget Logic

Good split:

- domain logic: coefficient interpretation, IDCT preview math, quant-table lookup
- widget logic: tab population, page state, event handling, redraw timing

This is important because UI bugs and JPEG bugs look similar in the Trace workspace but come from different places.

## 2. Textual/TUI Skills

### Respect Widget Lifecycle

One of the biggest practical skills in this codebase is knowing that Textual lifecycle rules are real constraints.

Reliable pattern:

- create containers first
- populate nested tab structures after mount
- use `call_after_refresh(...)` when structure must exist before content is added

Unreliable pattern:

- constructing nested `TabbedContent` and immediately calling `add_pane(...)` during early build time

That exact mistake caused a live runtime crash around nested visual tabs.

### Prefer Explicit Tabs Over Hidden Mode State

The first Trace visualization attempt used a mode selector. It worked in principle, but UI timing and event-shape issues made it harder to trust.

The more stable version was:

- one main `Visualisations` tab
- inside it: `Reconstruction` and `Wave Composition`

Lesson:

- in this TUI, explicit tabs are usually more robust than one widget controlling multiple invisible render modes

### Defensive Querying Matters

This app rebuilds Info-panel state and switches files often. During those transitions, stale widget lookups are expected.

Useful pattern:

- catch `QUERY_ERRORS`
- return early if widgets are not mounted yet

That kept rapid reloads and Trace rebuilds from crashing the app.

## 3. Trace Workspace Lessons

### Interpretation Beats Raw Terminology

The raw coefficient matrix was technically correct, but not self-explanatory. What users needed was interpretation:

- what `DC` means
- what AC terms mean
- why negative values are normal
- how zigzag order differs from the natural `8x8` layout

This led to the Trace `Coefficients` tab gaining interpretation text instead of more protocol-heavy wording.

### Separate Representation Levels Clearly

The Trace workspace now works better because it separates:

- bit/byte provenance
- Huffman/value decoding
- signed quantized coefficients
- visualization of the reconstructed block or cosine composition

Without those separations, encoded-domain data is easy to misread.

## 4. JPEG/DCT Skills Learned

### Entropy Bytes Are Not Coefficients

Users naturally conflate:

- entropy-coded bytes
- decoded Huffman/value bits
- signed quantized DCT coefficients
- reconstructed pixel values

The Trace UI became easier to understand once those representations were kept in distinct tabs.

### Signed Coefficients Need Plain-English Explanation

Values such as:

- `DC = -57`
- `AC[1] = -26`

are correct and normal. But without explanation they look suspicious.

Useful interpretation:

- `DC` is the low-frequency base level
- AC terms add directional/frequency variation
- negative values mean opposite phase, not corruption

### There Are Two Valid Visualizations

For the selected traced block there are two different useful visual views:

- `Reconstruction`
  - JPEG-style dequantize + inverse DCT preview
- `Wave Composition`
  - smooth summed cosine field for intuition

They answer different questions:

- what the decoder reconstructs
- what the basis functions mean

Both are worth keeping separate.

## 5. Specific Bugs And What They Taught

### Bug: Method Naming Drift

Symptom:

- Trace block click crashed because the code called `_entropy_trace_visual_mode(...)`
- the actual helper was named `_trace_visual_mode(...)`

Fix:

- unify names and search call sites immediately

Lesson:

- in mixins with many related helpers, naming drift is easy to introduce and hard to notice without explicit searches

### Bug: Wrong Textual Event Property

Symptom:

- changing a select did not update the preview until another interaction occurred

Cause:

- the installed Textual version exposed the changed widget on `event.control`
- the code read `event.select`

Fix:

- inspect the installed Textual version directly
- read the right event attribute for that version

Lesson:

- do not assume UI framework event shapes across versions

### Bug: Nested `TabbedContent` Crash

Symptom:

- Textual raised a `NoMatches` error for internal tab widgets

Cause:

- nested `TabbedContent.add_pane(...)` happened before the nested tab widget was fully mounted

Fix:

- stop relying on fragile nested early population
- settle on a simpler `Visualisations` structure that fits the existing Trace workspace better

Lesson:

- nested tab trees are one of the higher-risk UI patterns in this codebase

### Bug: Worker Thread Reading Widgets

Symptom:

- direct export logic worked, but button-driven export behavior was unclear and not trustworthy

Cause:

- background work was too tightly coupled to live widget state

Fix:

- capture data on the main thread first
- pass plain values into workers

Final outcome:

- the experimental Trace export button was removed for now

Lesson:

- if a background feature is not yet robust enough, remove it rather than leaving a flaky control in the UI

## 6. Testing Skills

### Fake-Widget Tests And Runtime Validation Catch Different Bugs

The existing focused TUI tests were still valuable and stayed green, but some runtime lifecycle issues only appeared in the live TUI.

Lesson:

- use tests for logic
- manually verify lifecycle-heavy TUI changes too

### Direct Invocation Is A Strong Isolation Tool

When the Trace export button was unclear, directly calling the underlying export logic showed that file generation itself worked.

That separated:

- pure implementation correctness
- from event/lifecycle correctness

Lesson:

- when a UI-triggered action is suspect, call the pure method directly first

## 7. Implementation Heuristics For Future Work

### Start With Read-Only Versions

The Trace visualization work would have been simpler if the order had been:

1. stable read-only visualization
2. interpretation text
3. interaction controls
4. exports

Instead of adding several layers of state at once.

### Remove Unstable Features Quickly

The export button was a good idea, but it was not solid enough. Removing it was the right decision because:

- it kept the Trace UI trustworthy
- it reduced debugging surface area
- it preserved the stable parts of the visualization work

### Keep Docs Updated With Behavior

This repo changes through iterative UI and architecture refinement, not only by backend algorithm additions.

That means the docs need to track:

- actual Trace tabs
- current stable TUI behavior
- which features are present now, not which features were attempted temporarily

## 8. Short Version

The main skills this app reinforced are:

- keep core JPEG logic out of the UI
- reuse entropy tracing and parser helpers instead of duplicating them
- treat Textual widget lifecycle as a design constraint
- prefer explicit tabs over hidden render modes
- interpret transform-domain values for users
- debug UI-triggered actions by isolating pure logic from event/lifecycle paths
- remove experimental controls if they are not robust enough

Those are the highest-value lessons to carry into the next round of work on this app.

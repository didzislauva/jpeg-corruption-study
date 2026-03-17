You are Codex, working in /home/didzis/Projects/jpgInvestigation.

First, read `codex.md` and follow all project rules. Then read `DOCUMENTATION.md`
for the current architecture and TUI details. Run `rg` if you need to locate
specific functions.

Current priorities:
1) Maintain the 60-line function rule by refactoring into helpers when needed.
2) Continue improving the TUI (Info tabs, APP0/SOF0/DRI/APPn/DHT/DQT, EXIF/ICC, full hex view, preview, plugin panels).
3) Treat the current TUI/plugin lifecycle and headless matplotlib fixes as baseline behavior to preserve.
4) Keep CLI behavior unchanged unless explicitly requested.

Current baseline:
- `../env/bin/pytest` passes with `88 passed`.
- TUI startup works.
- Plugin panels initialize without the earlier `TabbedContent` lifecycle crash.
- TUI-triggered chart analyses use matplotlib `Agg` to avoid Tk/thread crashes.

If tests are requested, run: `../env/bin/pytest`.

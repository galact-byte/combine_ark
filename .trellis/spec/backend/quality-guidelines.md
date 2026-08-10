# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

<!--
Document your project's quality standards here.

Questions to answer:
- What patterns are forbidden?
- What linting rules do you enforce?
- What are your testing requirements?
- What code review standards apply?
-->

This local desktop tool separates pure image/pattern transformations from Windows mouse automation. The latter is safety-critical: it must be deterministic under test and must reject uncertain targets rather than trying a best-effort click.

---

## Forbidden Patterns

- Do not hard-code a user directory, a display resolution, or absolute screen coordinates as an automation prerequisite.
- Do not treat whatever window is foreground at countdown expiry as the game. An automated click target must be the captured `HWND` **and** current process ID.
- Do not persist a calibration rectangle or scroll point outside its reference client area.
- Do not infer the bottom 16 colors from a fixed wheel value; persist the lower color-panel rectangle and user-confirmed wheel amount.
- Do not touch tkinter widgets or call `root.after()` from an automation worker thread; workers publish plain events and the main loop consumes them.

---

## Required Patterns

### Automated Input Safety Contract

`Calibration` must contain a validated client area, 24×24 grid, top palette, lower palette, scroll anchor, wheel amount, `target_window`, and `target_process_id` before automated filling begins.

```python
if not is_calibrated_window_foreground(calibration):
    return False  # send no click
```

Before every select, scroll, or cell click, the runner checks cancellation and re-reads the foreground `HWND`/PID. The UI worker only queues `("countdown" | "progress" | "finish", value)`; `PixelHelperApp._process_ui_events()` owns widget mutation.


---

## Testing Requirements

- Pure palette, image, export, calibration and step-planning behavior requires pytest coverage.
- Tests for mouse behavior inject `MouseDriver`; they must never move the real pointer.
- Calibration tests must reject out-of-client geometry and test at least two client sizes.
- Test the full 40-value RGB tuple, not only its length or endpoints.
- GUI changes require `compileall` and a tkinter create/destroy smoke test; real game clicking remains a manual opt-in acceptance check.

---

## Code Review Checklist

- [ ] No hard-coded user path or single-resolution runtime dependency.
- [ ] White index 3 is skipped; colors 24–39 require lower-palette calibration.
- [ ] Cancel and foreground/PID validation occur before every click step.
- [ ] UI worker has no direct tkinter calls.
- [ ] Pattern is the single source for preview, exports, and automatic drawing.

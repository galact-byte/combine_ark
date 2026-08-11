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

### Manual Image Crop Contract

#### 1. Scope / Trigger

Image import changes must preserve the current `Pattern` until the user confirms a visible square crop. This prevents background/clothing composition from silently replacing an already usable pattern.

#### 2. Signatures

```python
@dataclass(frozen=True)
class CropBox:
    left: int
    top: int
    side: int

    def validate_for(self, image_size: tuple[int, int]) -> None: ...

@dataclass
class ImageOptions:
    crop_box: CropBox | None = None
```

#### 3. Contracts

- `CropBox` is in original-image pixel coordinates, has `side > 0`, and must be wholly inside the source image.
- `prepare_square()` uses `crop_box` before legacy crop/contain/stretch options.
- `CropDialog` returns a validated `CropBox` only through its confirm callback. Cancel, close, preview failure, or invalid crop leaves `source_image`, `source_path`, remembered directory, and `Pattern` unchanged.
- `PixelHelperApp` persists the confirmed box in `crop_box`; reopening the dialog receives that same box.

#### 4. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| Negative position, zero side, or out-of-range side | `CropBox.validate_for()` raises `ValueError`. |
| File unreadable or preview/dialog unavailable | Show Chinese status; retain current pattern and source state. |
| User cancels/closes crop dialog | Invoke no commit callback; retain state. |
| Conversion after a confirmed crop fails | Retain source and crop box so the user can retry. |

#### 5. Good / Base / Bad Cases

- Good: `CropBox(100, 50, 400)` for a `600×500` image crops exactly `(100, 50, 500, 450)`.
- Base: `crop_box=None` retains legacy crop/contain/stretch behavior for compatibility.
- Bad: committing a selected file before the crop confirmation means cancel can replace the current pattern.

#### 6. Tests Required

- Test valid and invalid `CropBox` boundaries, exact prepared image pixels, 24×24 output, and palette indices `0..39`.
- Test canvas-to-source mapping plus clamped move, resize, and zoom behavior.
- Test import cancel/preview failure keeps the existing `Pattern`; test confirmation stores the box and re-crop reopens it.
- GUI work requires `compileall` and a tkinter create/destroy smoke test; automation tests must remain mouse-driver injected.

#### 7. Wrong vs Correct

```python
# Wrong: mutates live application state before user confirmation.
self.source_image = candidate_image
self.apply_conversion()

# Correct: only the dialog confirm callback commits state.
CropDialog(self.root, candidate_image, commit, None)
```


---

## Testing Requirements

- Pure palette, image, export, calibration and step-planning behavior requires pytest coverage.
- Tests for mouse behavior inject `MouseDriver`; they must never move the real pointer.
- Calibration tests must reject out-of-client geometry and test at least two client sizes.
- Test the full 40-value RGB tuple, not only its length or endpoints.
- GUI changes require `compileall` and a tkinter create/destroy smoke test; real game clicking remains a manual opt-in acceptance check.
- Image import changes must test the manual crop contract: direct original-coordinate crop, cancel rollback, re-crop persistence, and valid 24×24/40-color output.

---

## Automation Injection & Grid Detection

- Mouse injection uses Win32 `SendInput` (dual path: relative move to feed Unity Raw Input, then absolute virtual-desktop coordinate to align the system cursor). `pyautogui`/`mouse_event` is a swallowed-input fallback, never the default — a foreground game switched to Raw Input ignores `mouse_event`.
- Autofill requires administrator rights: without elevation UIPI blocks input to an elevated game. Elevate at startup via `should_elevate(is_admin(), already_tried)`; the `already_tried` marker (`--elevated` argv) MUST guard against a UAC-decline relaunch loop.
- Canvas geometry comes from screenshot grid-line detection (`detect_grid` / `detect_grid_rect`), not hand-typed rectangles. `viewport_seed` (centered 1280×720 model) is only the ROI seed; when detection confidence is below threshold, fall back to the seed geometry and tell the user — never silently use wrong coordinates.
- Palette geometry MUST NOT be derived by fixed ratio or by anchoring to the canvas: the palette is an edge-anchored panel that reflows independently under the in-game UI-scale slider (measured: canvas center stays ~45%, palette center 85%→82.5% at UI-scale 90). Detect it by color: `palette_locate.detect_palette_rect` matches the known 40 palette RGBs in the region right of the detected canvas (excluding the canvas), assigns each pixel to its nearest palette color, and least-squares-fits the 4×6 grid using the fixed `col=k%4, row=k//4` layout (skipping ambiguous indices 0–3). `calibration_from_capture` produces grid + palette from one screenshot; both fall back to seed on failure.
- Two-page palette is confirmed: top page shows color numbers 1–24 (indices 0–23); scrolled-to-bottom shows 17–40 (indices 16–39, offset 16 — matches `palette_center`'s `color-16`). The panel swaps content in place, so `lower_palette == palette`.
- Color SELECTION during fill MUST NOT rely on a fixed scroll offset: real scrolling does not land exactly at the assumed page, so a fixed `color-16` bottom-page offset mis-selects every scrolled color (dark-purple hair drawn as olive). Instead select live: before each color, screenshot and locate that color's swatch by its known RGB inside the calibrated palette ROI (`palette_locate.swatch_centers`, passed to `AutoFillRunner.run` as `select_color`), scrolling until it appears. When `select_color` is used, the explicit geometric scroll steps are skipped and a color that cannot be located is skipped (never blind-clicked).
- Swatch color-matching MUST exclude the panel background: the dark panel bg (~58,58,60) is near the dark navy/black swatches and, taken as nearest-palette, smears their centroid across the whole panel. `swatch_centers` takes the ROI modal color as background and drops any pixel closer to bg than to its nearest palette color.
- Palette scroll to colors 25–40 is emitted as N single-tick `scroll(-1, …)` calls with re-anchor each tick, not one large scroll, so Unity does not collapse it into a single step.
- Emergency stop is F8 (`f8_pressed`), which replaces the pointer-to-top-left failsafe (relative-move injection would false-trigger the corner). Foreground/PID re-validation and the cancel button remain.
- All `windll` access stays inside functions guarded by `os.name == 'nt'`; module top level (pure functions, ctypes struct defs) must import cleanly on any platform so image/pattern features and unit tests run cross-platform. No new third-party dependency (pywin32 etc.) — ctypes + Pillow only.
- Testability seam: `to_absolute`, `relative_delta`, `should_elevate`, `detect_grid`, `detect_grid_rect`, `viewport_seed` are pure and unit-tested; real `SendInput`/elevation/capture are never exercised in CI.

---

## Code Review Checklist

- [ ] No hard-coded user path or single-resolution runtime dependency.
- [ ] White index 3 is skipped; colors 24–39 require lower-palette calibration.
- [ ] Cancel and foreground/PID validation occur before every click step.
- [ ] UI worker has no direct tkinter calls.
- [ ] Pattern is the single source for preview, exports, and automatic drawing.
- [ ] Mouse injection uses SendInput dual path; grid geometry comes from detection with seed fallback + user notice.
- [ ] Palette geometry comes from color-match detection (not ratio/canvas-anchor); lower_palette == palette.
- [ ] Fill-time color selection is live color-match (`select_color`), not fixed scroll offset; swatch matching excludes the panel background color.
- [ ] Startup elevation guards against a UAC-decline relaunch loop; `windll` calls are Windows-guarded.
- [ ] Palette scroll is single-tick with re-anchor; F8 emergency stop is wired.

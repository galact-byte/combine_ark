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

## Code Review Checklist

- [ ] No hard-coded user path or single-resolution runtime dependency.
- [ ] White index 3 is skipped; colors 24–39 require lower-palette calibration.
- [ ] Cancel and foreground/PID validation occur before every click step.
- [ ] UI worker has no direct tkinter calls.
- [ ] Pattern is the single source for preview, exports, and automatic drawing.

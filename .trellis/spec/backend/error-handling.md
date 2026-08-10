# Error Handling

> Error-handling conventions for the local Python desktop tool.

---

## Overview

This application has no server boundary. Each module raises a focused exception with a recovery-oriented message; the tkinter orchestration layer catches expected errors, keeps the current editable `Pattern`, and shows a Chinese cause plus next step in the status area.

Do not let a failed optional automation dependency make image conversion, manual editing, or export unavailable.

---

## Error Types

- `ValueError`: invalid in-memory user values or data contracts, such as an invalid 24×24 grid, color index, or image option.
- `ExportError`: an export destination cannot be created or written. The message tells the user to choose another location or check file locks and permissions.
- `CalibrationError`: a saved calibration is malformed, a measured rectangle is invalid, or the Windows client area cannot be read. The recovery action is recalibration with the game editor visible.
- `RuntimeError`: an optional runtime dependency needed only for automation is unavailable.

---

## Error Handling Patterns

1. Validate at the module boundary. `Pattern`, `ImageOptions`, `Calibration`, and export functions reject invalid input before producing side effects.
2. Preserve the last valid `Pattern` when import, conversion, export, or calibration fails.
3. Catch expected I/O and PIL failures at the UI operation boundary and provide a Chinese explanation with a corrective action.
4. Keep platform integrations lazily imported. `pyautogui` is imported only after the user confirms automatic filling.
5. Treat automatic clicks as a safety-critical side effect: check cancellation and target-window foreground status before every step; stop instead of guessing coordinates or sending clicks to a different window.
6. Do not log image paths, account data, or calibration details beyond what the local user explicitly needs to see.

---

## Common Mistakes

- Hard-coding a screen resolution or a user image directory instead of using a current client area and `Path.home()` candidates.
- Catching an error in the automation worker without restoring disabled UI controls.
- Continuing to click after cancellation or after the target game window loses foreground focus.
- Coupling image conversion and export to Windows automation dependencies.

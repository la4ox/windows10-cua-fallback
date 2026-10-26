# Architecture and trust boundaries

## Primary path

The official Computer Use path hosted by the ChatGPT/Codex desktop app remains authoritative:

1. `@oai/sky` inventories apps and returns a window object.
2. Native accessibility and screenshot APIs are attempted.
3. Guarded official input is used for any interaction.

The fallback begins only when steps 1 and 3 work but native screenshot capture repeatedly fails.

The presence of a `codex-cli` executable beneath a desktop installation is not evidence that standalone CLI can host the plugin, native helper, app approvals or `node_repl`. This project does not support that configuration.

## Components

### `cua_fallback.mjs`

This module orchestrates the official window object and local capture helper. It activates and refreshes the target, invokes Python in a hidden child process, binds verification to the currently observed window, calls guarded `sky.click`, refreshes state, and captures the result.

### `window_snapshot.py`

This helper contains no input injection. It uses Win32 APIs to inspect and capture one HWND, writes the PNG and metadata atomically, and validates metadata before optional input.

Capture choices:

1. Default: `PrintWindow(PW_RENDERFULLCONTENT)` into a DIB sized from the full `GetWindowRect` frame.
2. Explicit-only: crop the DWM visible frame from the desktop while the target remains foreground and stable.

The helper never changes from `PrintWindow` to screen pixels automatically. A visible crop can contain foreign non-activating overlays inside its rectangle; foreground equality cannot detect every such overlap.

## Snapshot binding

Metadata records:

- schema and timestamp;
- HWND and PID;
- title for diagnostics;
- visibility and foreground state;
- raw `GetWindowRect`, visible DWM geometry and the method-specific capture rectangle/origin;
- DPI;
- capture method;
- image dimensions, path and SHA-256.

Verification rejects mismatched target identity, changed geometry or DPI, missing or modified files, future or expired timestamps and invalid coordinates. A screen-crop snapshot additionally requires foreground continuity. Coordinate input is authorized only when raw and DWM frames are identical; otherwise capture remains available but input fails closed.

## Residual race

No external screenshot can eliminate the small interval between verification and input. An overlay can appear inside the same HWND without changing geometry. Therefore coordinate input remains limited to narrow, reversible, user-authorized actions followed by immediate capture. A failure after attempted input is always an unknown outcome.

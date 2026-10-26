# Security policy

## Supported versions

Security fixes are applied to the current `main` branch. This project has not yet published a stable release series.

## Reporting a vulnerability

Do not attach screenshots, metadata JSON, local paths, tokens, credentials, session logs or other sensitive material to a public issue.

If GitHub private vulnerability reporting is available, use it. Otherwise open a minimal public issue requesting a private contact channel and include no exploit details or private data.

## Security invariants

- The target must originate from the current official `@oai/sky` app/window inventory.
- Screen crop is explicit-only and foreground-only. Foreign non-activating overlays remain a documented residual risk.
- Optional coordinate input must bind to the same live HWND, PID, geometry and DPI as the snapshot, and raw Win32/DWM frames must be identical.
- Changed, missing, future-dated, expired or tampered snapshots fail closed.
- Input uses the official guarded Computer Use path; the Python helper never injects input.
- Failures after attempted input are reported as unknown outcomes and must not be retried automatically.
- The project never asks for or stores authentication secrets.

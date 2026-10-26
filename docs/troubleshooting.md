# Troubleshooting

## Official capture works

Stop and use it. The fallback is not a preferred renderer and should not remain active merely because it is installed.

## `Window.id` is not a live HWND

The tested runtime exposed HWND values as window IDs, but this is not a public API guarantee. Re-inventory once. If `IsWindow` still rejects the current returned ID, stop and report the runtime incompatibility.

## `PrintWindow` is blank

GPU, protected and custom-rendered windows may not support `PrintWindow`. There is no automatic screen fallback. Request `method: "screen"` only when the exact target is foreground, stable and visibly unobscured. Do not use full-desktop capture or approximate another window.

## Coordinate input reports `ambiguous_frame`

Windows can expose a full raw frame with invisible resize borders and a smaller visible DWM frame. Because the official `sky.click` origin is not a public cross-version contract, the fallback refuses coordinate input when these frames differ. Keep the capture, use an accessibility element action, or stop. Do not add an offset by guesswork.

## Screen fallback says foreground changed

Expose the target and make a new capture. Do not bypass the check. Input or another app may have changed the foreground. Non-activating notifications and overlays can overlap a target without changing foreground; close them and inspect the resulting image.

## Geometry or DPI changed

Make a new capture after moving, resizing, maximizing, changing display scaling or moving the window between monitors.

## Snapshot is stale, future-dated or modified

Discard both PNG and metadata and capture again. Do not edit metadata to make it pass.

## Python or Pillow is missing

Prefer the Python returned by Codex workspace dependencies. Otherwise choose a known Python 3.10+ interpreter and install Pillow yourself after reviewing its source and destination. The skill never installs dependencies automatically.

## Input outcome is unknown

Do not repeat the click. Re-inventory the app, refresh state, make a new capture and inspect the visible result first.

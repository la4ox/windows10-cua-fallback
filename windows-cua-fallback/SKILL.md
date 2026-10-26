---
name: windows-cua-fallback
description: Capture and inspect one native Windows 10 app window when desktop-hosted Codex Computer Use can enumerate or control it but native screenshot capture repeatedly fails. Use only after a confirmed native capture failure; use browser control for browser tasks.
---

# Windows CUA Fallback

Restore visual observation without replacing the official `@oai/sky` inventory, accessibility or guarded input path.

This skill supports Codex desktop app `26.1021.3705.0` with the official Computer Use plugin.

Read the installed `computer-use` skill first. Its target selection, confirmation policy, forbidden surfaces, observe/action/refresh loop and recovery rules remain authoritative. Try official native capture first and retry it only as that skill allows. A working official capture ends this fallback workflow.

## Boundaries

- Native Windows apps only. Use Chrome or the in-app browser for browser tasks.
- Desktop-hosted Computer Use only, using supported Codex desktop app version `26.1021.3705.0`.
- Never use this fallback for terminals, ChatGPT/Codex, authentication, password managers, Windows security/privacy settings, protected content or another surface forbidden by `computer-use`.
- Capture exactly one window returned by the current `sky.list_apps()` or `sky.list_windows()` result. Never invent or reuse a stale window object.
- Do not patch or replace the signed OpenAI helper.

## Runtime

Prefer the Python executable returned by `mcp__codex_app__load_workspace_dependencies`; it includes Pillow. If unavailable, use an explicitly verified Python 3.10+ interpreter with Pillow. Never install packages silently.

Resolve absolute paths for this installed skill and a task-specific local output directory. Screenshots can contain sensitive information; do not place them in a synced or public folder by default.

## Capture

1. Initialize `@oai/sky` in `node_repl`, inventory apps, select exactly one returned window, activate it, and refresh text-only state.
2. Import `scripts/cua_fallback.mjs` from this skill using its resolved absolute path.
3. Call `captureWindow(...)` with the exact current window, Python path, helper path, PNG path and metadata path.
4. Inspect the PNG locally with `view_image`.
5. Prefer accessibility element actions whenever available.

```js
globalThis.snapshot = await cuaFallback.captureWindow({
  sky,
  window: targetWindow,
  pythonPath: "<absolute-python-path>",
  scriptPath: "<absolute-skill-path>\\scripts\\window_snapshot.py",
  outputPath: "<task-directory>\\window.png",
  metadataPath: "<task-directory>\\window.json",
});
globalThis.targetWindow = snapshot.window;
globalThis.state = snapshot.state;
nodeRepl.write(JSON.stringify(snapshot.capture));
```

The default and preferred method is `PrintWindow`. Never fall through to visible screen pixels automatically. Use `method: "screen"` only after the target is known to be unobscured; the same target must remain foreground before and after capture. A non-activating overlay or notification can still contaminate visible pixels without stealing foreground, so inspect the PNG.

## Optional coordinate input

External PNG coordinates require immediate revalidation. Use `clickAndCapture(...)`; never call an unguarded coordinate click based on the saved image.

```js
globalThis.clickResult = await cuaFallback.clickAndCapture({
  sky,
  window: targetWindow,
  pythonPath: "<absolute-python-path>",
  scriptPath: "<absolute-skill-path>\\scripts\\window_snapshot.py",
  metadataPath: "<task-directory>\\window.json",
  x: <x>,
  y: <y>,
  outputPathAfter: "<task-directory>\\window-after.png",
  metadataPathAfter: "<task-directory>\\window-after.json",
});
globalThis.targetWindow = clickResult.window;
globalThis.state = clickResult.state;
```

The operation rejects stale or tampered images, a different HWND/PID, changed geometry or DPI, out-of-bounds points, a non-foreground screen-crop target, and windows whose raw Win32 and visible DWM frames differ. The latter remain available for capture, but their coordinate origin is ambiguous and input fails closed. Inspect the returned post-click image immediately.

If any error occurs after input may have started, the outcome is unknown. Do not retry automatically. Re-inventory, re-observe and capture the target before deciding what to do.

`Window.id` is treated as an HWND because that contract was observed on tested Windows runtimes; it is not a public promise of `@oai/sky`. Stop if `IsWindow` rejects it.

## Limits

`PrintWindow` can return blank content for protected, GPU-only, UWP or custom-rendered surfaces. Screen crop is never automatic and may include overlapping visible UI. The fallback stops when neither method is safe. Mixed-DPI and multi-monitor behavior must be observed rather than assumed.

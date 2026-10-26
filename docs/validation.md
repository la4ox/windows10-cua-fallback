# Validation evidence

## Historical Windows 10 test

Environment:

- Windows 10 22H2, build 19045;
- official native inventory and guarded input available;
- native screenshot path failed with `SetIsBorderRequired` / `0x80004002`;
- Windows Calculator at DPI 96.

Observed results:

- `PrintWindow` produced a visible `1202×934` image;
- guarded coordinate input entered `1` in the original implementation;
- a second guarded input cleared the display to `0`;
- post-click images visually confirmed both results;
- an out-of-bounds point and non-finite age were rejected before input;
- forced screen crop with another foreground window was rejected.

Those live receipts belong to the original implementation. The public revision adds stricter raw/DWM frame binding, explicit-only screen capture and additional fail-closed checks. Its automated contracts pass, but that hardened revision has not yet received a fresh live Windows 10 run.

The exact Codex AppX, Computer Use runtime and `@oai/sky` versions used on 16 September 2026 were not recorded. They must not be inferred from a later installation.

A separate observation immediately before the 26 October 2026 in-place operating-system upgrade confirmed that Codex AppX `26.1021.3705.0` was already running on Windows 10 22H2. The same AppX version remained installed afterward. This records Codex application continuity; it does not identify the September Computer Use runtime and does not replace a fresh live test of the hardened public revision on Windows 10.

## Other Windows versions

No compatibility claim is made. The hardened code records raw and DWM frames, uses the full raw frame for `PrintWindow`, makes screen crop explicit-only, and rejects coordinate authorization when coordinate origins are ambiguous. These defenses reduce risk but do not establish support on an untested operating-system/runtime combination.

## Maintainer toolchain snapshot

Repository validation on 27 October 2026 used:

- Codex Windows AppX `26.1021.3705.0`;
- Computer Use runtime/app marker `26.1021.31345`;
- `@oai/sky` `0.7.13`;
- desktop-bundled `codex-cli 0.164.0-alpha.11.1`.

This is a dated maintenance receipt, not a rolling “latest” declaration, an operating-system compatibility claim, or evidence of standalone CLI support. All Computer Use validation was hosted by the desktop app.

## CI boundary

GitHub-hosted Windows runners do not provide a trustworthy interactive desktop for this workflow. CI therefore checks source syntax, pure validation contracts, packaging and privacy residue. It must not be presented as proof of live GUI capture.

## Live acceptance procedure

1. Choose Calculator or another harmless pre-existing app.
2. Prove the official capture path fails; otherwise stop.
3. Inventory and bind exactly one returned window.
4. Capture it through the fallback and inspect the PNG.
5. If needed, choose one reversible coordinate action.
6. Run `clickAndCapture` and inspect the post-click PNG.
7. Restore the harmless app state.

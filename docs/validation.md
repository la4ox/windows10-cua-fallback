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

Beyond the formal Calculator receipt, the fallback was used regularly on the same Windows 10 22H2 workstation over an extended period, including routine work across two monitors. No monitor-specific fallback failure was observed.

The hardened public revision preserves the tested `PrintWindow`/official-input path and adds stricter raw/DWM frame binding, explicit-only screen capture and additional fail-closed checks. Those added guards are covered by automated contracts; a separate end-to-end replay of the exact final commit on Windows 10 was not recorded.

Immediately before the 26 October 2026 in-place operating-system upgrade, Codex AppX `26.1021.3705.0` was confirmed running on Windows 10 22H2. This is the supported Codex desktop version recorded for the project. The exact Computer Use runtime and `@oai/sky` versions used for the first 16 September receipt were not recorded.

## Other Windows versions

No compatibility claim is made. The hardened code records raw and DWM frames, uses the full raw frame for `PrintWindow`, makes screen crop explicit-only, and rejects coordinate authorization when coordinate origins are ambiguous. These defenses reduce risk but do not establish support on an untested operating-system/runtime combination.

## Supported Codex version

Supported and tested Codex desktop app version:

- `26.1021.3705.0`

This version was present on Windows 10 immediately before the in-place operating-system upgrade and was used for repository validation on 27 October 2026.

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

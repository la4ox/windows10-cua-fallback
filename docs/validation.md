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

## Other Windows versions

No compatibility claim is made. The hardened code records raw and DWM frames, uses the full raw frame for `PrintWindow`, makes screen crop explicit-only, and rejects coordinate authorization when coordinate origins are ambiguous. These defenses reduce risk but do not establish support on an untested operating-system/runtime combination.

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

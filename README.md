# windows10-cua-fallback

[![Validate](https://github.com/la4ox/windows10-cua-fallback/actions/workflows/validate.yml/badge.svg)](https://github.com/la4ox/windows10-cua-fallback/actions/workflows/validate.yml)

An unofficial, fail-closed screenshot fallback for Computer Use in the ChatGPT/Codex desktop app on Windows 10 when the official native app inventory and input path work, but native window capture fails.

It was created for a reproducible Windows 10 22H2 failure (`SetIsBorderRequired`, `0x80004002`). It does **not** patch, replace, inject into, or redistribute the signed OpenAI Computer Use helper.

> [!WARNING]
> This is a community workaround, not an OpenAI product or supported repair. Read [DISCLAIMER.md](DISCLAIMER.md) before using it. Always try the official Computer Use capture path first.

## What it does

- Selects one exact native window already returned by the official `@oai/sky` inventory.
- Captures only that HWND through `PrintWindow(PW_RENDERFULLCONTENT)`.
- Can perform a visible screen crop only when that method is requested explicitly and the same target remains foreground.
- Stores a local PNG plus metadata binding the snapshot to HWND, PID, geometry, DPI, timestamp and image hash.
- Verifies that binding immediately before any optional coordinate click and rejects input when raw Win32 and visible DWM coordinate frames differ.
- Uses the official guarded `sky.click` for input and captures the result immediately afterward.

## What it does not do

- It does not bypass app approvals, UAC, authentication, HTTPS warnings or OS security barriers.
- It does not automate terminals, ChatGPT/Codex, password managers, authentication dialogs, or Windows security/privacy settings.
- It does not provide full-desktop capture.
- It does not make protected, GPU-only or custom-rendered windows capturable.
- It does not guarantee that an external PNG remains current; every input is revalidated and may still be rejected.

## Compatibility

Supported and tested Codex desktop app version: **`26.1021.3705.0`** with Windows 10 22H2, build 19045.

No compatibility claim is made for Windows 11 or other Windows releases. Use the official native capture path whenever it works. See [docs/validation.md](docs/validation.md).

## Install the skill

Prerequisites:

- ChatGPT/Codex desktop with the official Computer Use plugin enabled.
- Codex desktop app `26.1021.3705.0`.
- Windows 10 22H2, build 19045. Other builds are not claimed as supported.
- Python 3.10+ with Pillow. Prefer the Python returned by Codex workspace dependencies when available.

From PowerShell:

```powershell
.\scripts\Install-WindowsCuaFallback.ps1 -WhatIf
.\scripts\Install-WindowsCuaFallback.ps1
```

If a copy already exists, inspect it first, then use `-Force`. The installer keeps a timestamped rollback copy under the selected Codex home.

Restart Codex if the new skill is not discovered. Invoke it as `$windows-cua-fallback` only after official native capture has failed for one specific app.

## Make fallback routing persistent (optional)

Installing the skill makes it available, but does not guarantee that Codex will select it automatically after a native capture failure. After you have verified the fallback on a harmless app, review and copy the [optional routing snippet](windows-cua-fallback/references/agent-routing.md) into the instruction scope you want:

- `~/.codex/AGENTS.md` for a personal default across projects; or
- the repository-root `AGENTS.md` for one project only.

Start a new Codex run or session after editing the instructions, then confirm that the expected guidance was loaded. The installer never creates or modifies `AGENTS.md` automatically.

## Validate the project

```powershell
.\scripts\Test-Project.ps1
```

CI and the local validation script cover syntax, unit/contract tests, packaging and privacy residue. They cannot prove GUI capture on a headless runner. The live procedure is documented in [docs/validation.md](docs/validation.md).

## Legacy Win10 workspace runtime recovery

`legacy/install-codex-workspace-runtime-win10.mjs` is a separate, conservative recovery tool for an old Windows 10 failure where Codex Workspace Dependencies could not install its runtime bundle. It is **not** a Codex installer and **not** sandbox provisioning.

The legacy tool performs only a manifest preflight by default. Applying an installation requires `--apply`, a bootstrap Python interpreter, a verified archive and an explicit acknowledgement of the unsupported recovery path. Prefer the current official Codex workflow whenever it works. Read [docs/legacy-runtime-installer.md](docs/legacy-runtime-installer.md) first.

## Documentation

- [Architecture and trust boundaries](docs/architecture.md)
- [Validation evidence and live test](docs/validation.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Legacy runtime recovery](docs/legacy-runtime-installer.md)
- [Optional AGENTS.md routing snippet](windows-cua-fallback/references/agent-routing.md)
- [Security policy](SECURITY.md)

## License

MIT. See [LICENSE](LICENSE). The warranty disclaimer in the license and the project-specific [DISCLAIMER.md](DISCLAIMER.md) both apply.

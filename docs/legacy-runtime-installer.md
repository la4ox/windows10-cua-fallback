# Legacy workspace-runtime recovery

This optional helper recovers the **workspace-dependencies bundle** used by Codex
for documents, images, spreadsheets and similar tools. It does not install the
Codex desktop app or CLI and does not configure a Windows sandbox.

The original Windows 10 repair was made in June 2026. It fetched the official
runtime bundle manually because the desktop installation path did not work on
that machine. Its `tar.xz` extraction failed when Windows `tar` could not launch
`xz`; Python `tarfile` supplied the working extraction path. The desktop app then
recognized bundle `26.601.10930`. That observation is historical evidence, not a
promise that a current desktop build will recognize every manually placed bundle.

## Prefer the current app workflow

Try the desktop app's normal workspace-dependencies installation first. Current
[OpenAI Windows guidance](https://learn.chatgpt.com/docs/windows/windows-sandbox)
recommends Windows 11, treats recent Windows 10 as best effort, and documents the
native sandbox separately. A dependency bundle cannot fix an incompatible capture
API, an app registration problem, or a sandbox-policy failure.

This tool depends on a public CDN's **internal manifest and filesystem layout**.
They are not a supported installation API. Future layout changes are expected to
fail validation. Do not relax the validation to make an unknown bundle install.

## Inspect before installing

Use an independent Node.js 20+ installation. Installation additionally requires
an independent Python 3.10+ with gzip/xz support; do not use executables from the
runtime you are replacing. No npm or pip packages are required.

```powershell
node .\legacy\install-codex-workspace-runtime-win10.mjs --dry-run
```

Default mode fetches only the fixed official manifest, validates it and prints the
bundle version, archive size, SHA-256, URL and proposed destination. It does not
download the archive, create a staging folder, or change the installed runtime.
As checked on 27 October 2026, the manifest used `tar.gz`; both it and historical
`tar.xz` are accepted. The manifest is mutable, so inspect the actual output.

After closing Codex and other consumers of that runtime, run from an ordinary
external terminal, substituting the version reviewed in the dry-run:

```powershell
node .\legacy\install-codex-workspace-runtime-win10.mjs --apply --expected-version 26.1025.11240 --python C:\Path\To\Python\python.exe
```

The example version is dated, not pinned as the project default. If the manifest
changes, `--expected-version` refuses the install. This flag is required with
`--apply`. Review a fresh dry-run before
choosing the new value. Do not add administrator privileges just to overcome a
locked runtime; close its consumers or resolve the exact filesystem permission.

## What the apply path does

1. Accepts only the exact HTTPS host `persistent.oaistatic.com`, the runtime's
   versioned CDN directory and the expected Windows x64 archive name. Redirects,
   query strings and alternate hosts are rejected.
2. Creates an exclusive install lock below `~/.cache/codex-runtimes`. It never
   automatically removes an existing lock as stale.
3. Downloads into a unique staging directory, with a time limit, exact compressed
   byte count and SHA-256 check against the manifest.
4. Inspects the entire tar before extraction. Only regular files/directories
   inside `codex-primary-runtime` are accepted. Traversal, absolute/drive paths,
   ADS, Windows device names, case collisions, links, sparse and special files are
   rejected. Expanded data is limited to 24 GiB and 250,000 entries.
5. Extracts new files into staging without `extractall`, then validates
   `runtime.json`, Node, Python, `node_modules` and the `bin` directory.
   It executes only the candidate Node/Python `--version` checks.
6. Preserves an existing runtime as `codex-primary-runtime.previous-<uuid>`, moves
   the candidate into place, and repeats validation at its final path.
7. On final validation/install failure, retains the new candidate as
   `codex-primary-runtime.failed-<uuid>` when necessary and restores the previous
   runtime. If rollback itself fails, it preserves staging and reports recovery
   paths rather than deleting evidence. Successful backups are retained.

The installer does not edit Codex config, registry, PATH, services, firewall rules,
user accounts or sandbox identities. Download and extraction still consume disk
space and perform local writes. SHA-256 verifies the archive against the fetched
manifest; it is not an independent publisher signature. The verified bundle is
still executable vendor code, and version validation executes its binaries.

## Verify and recover

```powershell
node .\legacy\install-codex-workspace-runtime-win10.mjs --doctor
```

Doctor reads the existing runtime, checks required paths and launches its Node and
Python with `--version`; it does not fetch or install a bundle. Reopen Codex and
ask it to load workspace dependencies. A doctor success does not prove the app
recognizes that bundle or that every bundled tool works.

If reverting a successful install, close all runtime consumers first, preserve the
current directory under a different name, and rename the matching
`.previous-<uuid>` directory back to `codex-primary-runtime`. Re-run doctor and the
app's workspace-dependencies check. Do not merge trees, remove unrelated backups,
or delete the lock while another install is active.

## Validation limits

Automated tests exercise synthetic gzip/xz archives, malicious tar entries,
manifest restrictions, integrity failures, install-lock contention and rollback
after final-path validation failure. They do not download a production bundle or
replace a real installed runtime. A legacy installation must be verified on its
actual Windows 10 machine and desktop build. This helper is provided as-is under
the project's license and disclaimer.

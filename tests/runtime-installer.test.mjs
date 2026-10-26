import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import * as fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { DEFAULT_MANIFEST_URL, RUNTIME_NAME, fetchManifest, installRuntime, parseArgs,
  validateCdnUrl, validateManifest, validateRuntime, verifyArchiveFile } from "../legacy/install-codex-workspace-runtime-win10.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const helper = path.resolve(here, "../legacy/extract_runtime_tar.py");
const python = process.env.TEST_PYTHON ?? (process.platform === "win32" ? "python" : "python3");

function manifest(overrides = {}) {
  return { targetPlatform: "win32", targetArch: "x64", bundleVersion: "26.1025.11240",
    bundleFormatVersion: 2, format: "tar.gz", runtimeRootDirectoryName: RUNTIME_NAME,
    archiveName: "codex-primary-runtime-win32-x64-26.1025.11240.tar.gz",
    archiveUrl: "https://persistent.oaistatic.com/codex-primary-runtime/26.1025.11240/codex-primary-runtime-win32-x64-26.1025.11240.tar.gz",
    archiveSizeBytes: 1, archiveSha256: "a".repeat(64), ...overrides };
}

async function temporary(t) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "cua-runtime-test-"));
  t.after(async () => {
    assert.ok(root.startsWith(path.join(os.tmpdir(), "cua-runtime-test-")));
    await fs.rm(root, { recursive: true, force: true });
  });
  return root;
}

// A separate fixture program avoids multiline Python code crossing shell quoting.
const fixtureProgram = `import io, json, sys, tarfile\nfrom pathlib import Path\na=json.loads(Path(sys.argv[1]).read_text())\nwith tarfile.open(sys.argv[2], 'w:gz' if sys.argv[3]=='tar.gz' else 'w:xz') as tf:\n for item in a:\n  info=tarfile.TarInfo(item['name'])\n  kind=item.get('kind','file')\n  if kind=='dir': info.type=tarfile.DIRTYPE\n  elif kind=='symlink': info.type=tarfile.SYMTYPE; info.linkname='../../escape'\n  elif kind=='hardlink': info.type=tarfile.LNKTYPE; info.linkname='../../escape'\n  elif kind=='fifo': info.type=tarfile.FIFOTYPE\n  elif kind=='device': info.type=tarfile.CHRTYPE\n  data=item.get('data','').encode() if kind=='file' else b''\n  info.size=len(data)\n  tf.addfile(info,io.BytesIO(data) if kind=='file' else None)\n`;

async function makeArchive(root, members, format = "tar.gz") {
  const script = path.join(root, "make_fixture.py");
  const spec = path.join(root, "members.json");
  const archive = path.join(root, `fixture.${format}`);
  await fs.writeFile(script, fixtureProgram);
  await fs.writeFile(spec, JSON.stringify(members));
  const result = spawnSync(python, [script, spec, archive, format], { encoding: "utf8", shell: false });
  assert.equal(result.status, 0, result.stderr || result.error?.message);
  return archive;
}

function runHelper(args) { return spawnSync(python, [helper, ...args], { encoding: "utf8", shell: false }); }

test("default CLI is a dry-run and apply/timeout flags are explicit", () => {
  assert.equal(parseArgs([]).apply, false);
  assert.equal(parseArgs(["--dry-run"]).apply, false);
  assert.equal(parseArgs(["--apply", "--expected-version", "26.1025.11240"]).apply, true);
  for (const args of [["--apply"], ["--apply", "--dry-run"], ["--doctor", "--apply"], ["--timeout-seconds", "NaN"], ["--download-timeout-seconds", "0"], ["--manifest-url", "https://example.com"]]) {
    assert.throws(() => parseArgs(args));
  }
});

test("manifest validation binds target, names, version, size, digest and exact CDN path", () => {
  assert.equal(validateManifest(manifest()).format, "tar.gz");
  const xz = manifest({ format: "tar.xz", archiveName: "codex-primary-runtime-win32-x64-26.1025.11240.tar.xz",
    archiveUrl: "https://persistent.oaistatic.com/codex-primary-runtime/26.1025.11240/codex-primary-runtime-win32-x64-26.1025.11240.tar.xz" });
  assert.equal(validateManifest(xz).format, "tar.xz");
  for (const change of [{ targetArch: "arm64" }, { runtimeRootDirectoryName: "../escape" }, { archiveName: "../x" },
    { bundleVersion: "../x" }, { bundleFormatVersion: 3 }, { archiveSizeBytes: 0 }, { archiveSizeBytes: Infinity },
    { archiveSha256: "bad" }, { archiveUrl: manifest().archiveUrl.replace("oaistatic.com", "oaistatic.com.evil.invalid") },
    { archiveUrl: `${manifest().archiveUrl}?token=x` }, { archiveUrl: manifest().archiveUrl.replace("https:", "http:") }]) {
    assert.throws(() => validateManifest(manifest(change)));
  }
  assert.throws(() => validateManifest(manifest(), "26.1.1"));
  assert.throws(() => validateCdnUrl("https://user@persistent.oaistatic.com/x", "/x"));
});

test("manifest fetch uses fixed URL and refuses HTTP/redirect/oversize results", async () => {
  let called;
  const result = await fetchManifest({ fetchImpl: async (url, options) => {
    called = { url, options };
    return new Response(JSON.stringify(manifest()));
  } });
  assert.equal(result.bundleVersion, "26.1025.11240");
  assert.equal(called.url, DEFAULT_MANIFEST_URL);
  assert.equal(called.options.redirect, "error");
  await assert.rejects(fetchManifest({ fetchImpl: async () => new Response("bad", { status: 500 }) }));
  await assert.rejects(fetchManifest({ fetchImpl: async () => new Response(" ".repeat(65537)) }));
});

test("archive integrity detects size and digest mismatches", async t => {
  const root = await temporary(t);
  const archive = path.join(root, "data.bin");
  await fs.writeFile(archive, "payload");
  const correct = manifest({ archiveSizeBytes: 7, archiveSha256: createHash("sha256").update("payload").digest("hex") });
  await verifyArchiveFile(archive, correct);
  await assert.rejects(verifyArchiveFile(archive, { ...correct, archiveSizeBytes: 8 }));
  await assert.rejects(verifyArchiveFile(archive, { ...correct, archiveSha256: "b".repeat(64) }));
});

test("gzip and xz extraction reproduce files without tar extractall", async t => {
  for (const format of ["tar.gz", "tar.xz"]) {
    const root = await temporary(t);
    const archive = await makeArchive(root, [{ name: RUNTIME_NAME, kind: "dir" },
      { name: `${RUNTIME_NAME}/runtime.json`, data: "fixture" }, { name: `${RUNTIME_NAME}/nested/a.txt`, data: "hello" }], format);
    const output = path.join(root, "output");
    const extracted = runHelper(["extract", "--archive", archive, "--format", format, "--output", output]);
    assert.equal(extracted.status, 0, extracted.stderr);
    assert.equal(JSON.parse(extracted.stdout).members, 3);
    assert.equal(await fs.readFile(path.join(output, RUNTIME_NAME, "nested/a.txt"), "utf8"), "hello");
    const overwrite = runHelper(["extract", "--archive", archive, "--format", format, "--output", output]);
    assert.notEqual(overwrite.status, 0);
  }
});

test("unsafe tar entries fail before creating extraction output", async t => {
  const cases = [
    { name: "../escape" }, { name: "/absolute" }, { name: "C:/escape" }, { name: `${RUNTIME_NAME}/../escape` },
    { name: `${RUNTIME_NAME}/C:escape` }, { name: `${RUNTIME_NAME}/a\\b` }, { name: `${RUNTIME_NAME}/NUL.txt` },
    { name: `${RUNTIME_NAME}/trailing.` }, { name: `${RUNTIME_NAME}/a`, kind: "symlink" },
    { name: `${RUNTIME_NAME}/a`, kind: "hardlink" }, { name: `${RUNTIME_NAME}/a`, kind: "fifo" },
    { name: `${RUNTIME_NAME}/a`, kind: "device" },
  ];
  for (const unsafe of cases) {
    const root = await temporary(t);
    const archive = await makeArchive(root, [{ name: `${RUNTIME_NAME}/good`, data: "ok" }, unsafe]);
    const output = path.join(root, "output");
    const result = runHelper(["extract", "--archive", archive, "--format", "tar.gz", "--output", output]);
    assert.notEqual(result.status, 0, JSON.stringify(unsafe));
    await assert.rejects(fs.stat(output), { code: "ENOENT" });
  }
});

test("case collisions, file parents and expansion limits are rejected", async t => {
  for (const members of [
    [{ name: `${RUNTIME_NAME}/a` }, { name: `${RUNTIME_NAME}/A` }],
    [{ name: `${RUNTIME_NAME}/a` }, { name: `${RUNTIME_NAME}/a/b` }],
    [{ name: `${RUNTIME_NAME}/a`, data: "xx" }],
  ]) {
    const root = await temporary(t);
    const archive = await makeArchive(root, members);
    const result = runHelper(["inspect", "--archive", archive, "--format", "tar.gz", "--max-bytes", "1"]);
    assert.notEqual(result.status, 0);
  }
});

test("extraction refuses an output junction or symlink", async t => {
  const root = await temporary(t);
  const archive = await makeArchive(root, [{ name: `${RUNTIME_NAME}/file`, data: "hello" }]);
  const destination = path.join(root, "destination");
  const linkedOutput = path.join(root, "linked-output");
  await fs.mkdir(destination);
  try { await fs.symlink(destination, linkedOutput, process.platform === "win32" ? "junction" : "dir"); }
  catch (error) { if (["EPERM", "ENOTSUP", "EACCES"].includes(error.code)) { t.skip("test host cannot create a temporary link"); return; } throw error; }
  const result = runHelper(["extract", "--archive", archive, "--format", "tar.gz", "--output", linkedOutput]);
  assert.notEqual(result.status, 0);
  assert.deepEqual(await fs.readdir(destination), []);
});

async function fixtureRuntime(directory, version = "26.1025.11240") {
  await fs.mkdir(path.join(directory, "dependencies/node/bin"), { recursive: true });
  await fs.mkdir(path.join(directory, "dependencies/node/node_modules"), { recursive: true });
  await fs.mkdir(path.join(directory, "dependencies/python"), { recursive: true });
  await fs.mkdir(path.join(directory, "dependencies/bin"), { recursive: true });
  await fs.writeFile(path.join(directory, "runtime.json"), JSON.stringify({ targetPlatform: "win32", targetArch: "x64", bundleFormatVersion: 2, bundleVersion: version }));
  await fs.writeFile(path.join(directory, "dependencies/node/bin/node.exe"), "fixture");
  await fs.writeFile(path.join(directory, "dependencies/python/python.exe"), "fixture");
}

test("runtime validation checks metadata/structure and runs intended version commands", async t => {
  const root = await temporary(t);
  await fixtureRuntime(root);
  const calls = [];
  const run = (executable, args) => { calls.push({ executable, args }); return executable.endsWith("node.exe") ? "v24.18.0" : "Python 3.12.6"; };
  const result = await validateRuntime(root, validateManifest(manifest()), { run });
  assert.equal(result.bundleFormatVersion, 2);
  assert.equal(calls.length, 2);
  assert.deepEqual(calls.map(item => item.args), [["--version"], ["--version"]]);
  const metadata = JSON.parse(await fs.readFile(path.join(root, "runtime.json"), "utf8"));
  await fs.writeFile(path.join(root, "runtime.json"), JSON.stringify({ ...metadata, nodeVersion: "v99.0.0" }));
  await assert.rejects(validateRuntime(root, undefined, { run }), /Node version differs/);
  await fs.writeFile(path.join(root, "runtime.json"), JSON.stringify(metadata));
  await assert.rejects(validateRuntime(root, validateManifest(manifest({ bundleVersion: "26.1.1", archiveName: "codex-primary-runtime-win32-x64-26.1.1.tar.gz", archiveUrl: "https://persistent.oaistatic.com/codex-primary-runtime/26.1.1/codex-primary-runtime-win32-x64-26.1.1.tar.gz" })), { run }));
  await fs.unlink(path.join(root, "dependencies/node/bin/node.exe"));
  await assert.rejects(validateRuntime(root, undefined, { run }));
});

async function transactionOptions(root, validate) {
  const data = Buffer.from("fixture archive");
  return { installRoot: root, manifest: manifest({ archiveSizeBytes: data.length, archiveSha256: createHash("sha256").update(data).digest("hex") }),
    download: async (info, destination) => fs.writeFile(destination, data, { flag: "wx" }),
    extract: async (info, archive, destination) => { await fs.mkdir(path.join(destination, RUNTIME_NAME), { recursive: true }); await fs.writeFile(path.join(destination, RUNTIME_NAME, "marker"), "new"); },
    validate, log: () => {} };
}

test("transaction retains previous runtime on success and releases lock/staging", async t => {
  const root = await temporary(t);
  const finalRoot = path.join(root, RUNTIME_NAME);
  await fs.mkdir(finalRoot);
  await fs.writeFile(path.join(finalRoot, "marker"), "old");
  let validations = 0;
  const options = await transactionOptions(root, async () => { validations++; return { bundleVersion: "26.1025.11240" }; });
  const result = await installRuntime(options);
  assert.equal(validations, 2);
  assert.equal(await fs.readFile(path.join(finalRoot, "marker"), "utf8"), "new");
  assert.equal(await fs.readFile(path.join(result.backupRoot, "marker"), "utf8"), "old");
  const names = await fs.readdir(root);
  assert.equal(names.some(name => name.startsWith("manual-runtime-install-")), false);
  assert.equal(names.includes(`.${RUNTIME_NAME}.install.lock`), false);
});

test("final-path failure restores previous runtime and retains failed candidate", async t => {
  const root = await temporary(t);
  const finalRoot = path.join(root, RUNTIME_NAME);
  await fs.mkdir(finalRoot);
  await fs.writeFile(path.join(finalRoot, "marker"), "old");
  let validations = 0;
  const options = await transactionOptions(root, async () => { if (++validations === 2) throw new Error("simulated locked or broken final runtime"); return {}; });
  await assert.rejects(installRuntime(options), /previous runtime was restored/);
  assert.equal(await fs.readFile(path.join(finalRoot, "marker"), "utf8"), "old");
  const failed = (await fs.readdir(root)).find(name => name.startsWith(`${RUNTIME_NAME}.failed-`));
  assert.ok(failed);
  assert.equal(await fs.readFile(path.join(root, failed, "marker"), "utf8"), "new");
});

test("lock contention and integrity failure never replace an existing runtime", async t => {
  const root = await temporary(t);
  const finalRoot = path.join(root, RUNTIME_NAME);
  await fs.mkdir(finalRoot);
  await fs.writeFile(path.join(finalRoot, "marker"), "old");
  const lock = path.join(root, `.${RUNTIME_NAME}.install.lock`);
  await fs.writeFile(lock, "existing installer");
  const options = await transactionOptions(root, async () => ({}));
  await assert.rejects(installRuntime(options), /lock exists/);
  assert.equal(await fs.readFile(lock, "utf8"), "existing installer");
  await fs.unlink(lock);
  await assert.rejects(installRuntime({ ...options, download: async (info, destination) => fs.writeFile(destination, "bad") }));
  assert.equal(await fs.readFile(path.join(finalRoot, "marker"), "utf8"), "old");
});

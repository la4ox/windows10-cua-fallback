#!/usr/bin/env node
/** Legacy recovery of the Codex workspace-dependencies bundle for Windows x64.
 * Default mode fetches the manifest and prints a plan. Only --apply installs.
 */
import { createHash, randomUUID } from "node:crypto";
import { createReadStream, createWriteStream } from "node:fs";
import * as fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { Readable, Transform } from "node:stream";
import { pipeline } from "node:stream/promises";

export const DEFAULT_MANIFEST_URL = "https://persistent.oaistatic.com/codex-primary-runtime/latest/win32-x64/LATEST.json";
export const RUNTIME_NAME = "codex-primary-runtime";
const USER_AGENT = "windows10-cua-fallback-legacy-runtime-installer";
const MAX_ARCHIVE_BYTES = 8 * 1024 ** 3;
const MAX_MANIFEST_BYTES = 64 * 1024;
const HERE = path.dirname(fileURLToPath(import.meta.url));
const HELPER = path.join(HERE, "extract_runtime_tar.py");

export function validateCdnUrl(value, expectedPath) {
  const url = new URL(value);
  if (url.protocol !== "https:" || url.hostname !== "persistent.oaistatic.com" ||
      url.port || url.username || url.password || url.search || url.hash ||
      url.pathname !== expectedPath || url.href !== `https://persistent.oaistatic.com${expectedPath}`) {
    throw new Error("URL is outside the exact official runtime CDN location");
  }
  return url.href;
}

export function validateManifest(input, expectedVersion) {
  if (!input || typeof input !== "object" || Array.isArray(input)) throw new Error("Manifest must be an object");
  if (input.targetPlatform !== "win32" || input.targetArch !== "x64") throw new Error("Manifest target must be win32-x64");
  if (!/^\d+(?:\.\d+){2,3}$/.test(input.bundleVersion ?? "")) throw new Error("Unsafe or unsupported bundle version");
  if (expectedVersion && input.bundleVersion !== expectedVersion) throw new Error("Manifest bundle differs from --expected-version");
  if (![1, 2].includes(input.bundleFormatVersion ?? 1)) throw new Error("Unsupported internal bundle format version");
  if (!["tar.gz", "tar.xz"].includes(input.format)) throw new Error("Archive format must be tar.gz or tar.xz");
  if ((input.runtimeRootDirectoryName ?? RUNTIME_NAME) !== RUNTIME_NAME) throw new Error("Unexpected runtime root name");
  const expectedName = `${RUNTIME_NAME}-win32-x64-${input.bundleVersion}.${input.format}`;
  if (input.archiveName !== expectedName) throw new Error("Unsafe or unexpected archive name");
  const archiveUrl = validateCdnUrl(input.archiveUrl, `/codex-primary-runtime/${input.bundleVersion}/${expectedName}`);
  if (!Number.isSafeInteger(input.archiveSizeBytes) || input.archiveSizeBytes <= 0 || input.archiveSizeBytes > MAX_ARCHIVE_BYTES) {
    throw new Error("Manifest archive size is invalid or exceeds 8 GiB");
  }
  if (!/^[a-fA-F0-9]{64}$/.test(input.archiveSha256 ?? "")) throw new Error("Manifest SHA-256 is invalid");
  return Object.freeze({ bundleVersion: input.bundleVersion, bundleFormatVersion: input.bundleFormatVersion ?? 1,
    targetPlatform: "win32", targetArch: "x64", runtimeRootDirectoryName: RUNTIME_NAME,
    format: input.format, archiveName: expectedName, archiveUrl,
    archiveSizeBytes: input.archiveSizeBytes, archiveSha256: input.archiveSha256.toLowerCase() });
}

export function parseArgs(args) {
  const options = { apply: false, doctor: false, help: false, pythonPath: "python", timeoutMs: 30_000,
    downloadTimeoutMs: 15 * 60_000, expectedVersion: undefined };
  const values = new Map([["--python", "pythonPath"], ["--expected-version", "expectedVersion"],
    ["--timeout-seconds", "timeoutMs"], ["--download-timeout-seconds", "downloadTimeoutMs"]]);
  for (let index = 0; index < args.length; index++) {
    const arg = args[index];
    if (arg === "--apply") options.apply = true;
    else if (arg === "--doctor") options.doctor = true;
    else if (arg === "--help" || arg === "-h") options.help = true;
    else if (arg === "--dry-run") { /* Default; accepted for explicit invocation. */ }
    else if (values.has(arg)) {
      const value = args[++index];
      if (!value || value.startsWith("--")) throw new Error(`Missing value for ${arg}`);
      const key = values.get(arg);
      if (key.endsWith("Ms")) {
        const seconds = Number(value);
        if (!Number.isInteger(seconds) || seconds < 1 || seconds > 3600) throw new Error(`${arg} must be 1..3600`);
        options[key] = seconds * 1000;
      } else options[key] = value;
    } else throw new Error(`Unknown argument: ${arg}`);
  }
  if (options.apply && (options.doctor || args.includes("--dry-run"))) throw new Error("--apply cannot be combined with --doctor or --dry-run");
  if (options.expectedVersion && !/^\d+(?:\.\d+){2,3}$/.test(options.expectedVersion)) throw new Error("Invalid --expected-version");
  if (options.apply && !options.expectedVersion) throw new Error("--apply requires --expected-version from a reviewed dry-run");
  return options;
}

async function fetchResponse(url, timeoutMs, fetchImpl, consume) {
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), timeoutMs);
  try {
    const response = await fetchImpl(url, { redirect: "error", signal: abort.signal, headers: { "User-Agent": USER_AGENT } });
    if (!response.ok) throw new Error(`Runtime CDN returned HTTP ${response.status}`);
    if (response.url && response.url !== url) throw new Error("Runtime CDN response URL changed");
    return await consume(response);
  } finally { clearTimeout(timer); }
}

export async function fetchManifest({ timeoutMs = 30_000, expectedVersion, fetchImpl = fetch } = {}) {
  validateCdnUrl(DEFAULT_MANIFEST_URL, "/codex-primary-runtime/latest/win32-x64/LATEST.json");
  const raw = await fetchResponse(DEFAULT_MANIFEST_URL, timeoutMs, fetchImpl, async response => {
    if (!response.body) throw new Error("Manifest response has no body");
    const pieces = [];
    let bytes = 0;
    for await (const piece of response.body) {
      bytes += piece.byteLength;
      if (bytes > MAX_MANIFEST_BYTES) throw new Error("Manifest exceeds 64 KiB");
      pieces.push(Buffer.from(piece));
    }
    return JSON.parse(Buffer.concat(pieces).toString("utf8"));
  });
  return validateManifest(raw, expectedVersion);
}

export async function downloadArchive(manifest, archivePath, { timeoutMs = 15 * 60_000, fetchImpl = fetch } = {}) {
  await fetchResponse(manifest.archiveUrl, timeoutMs, fetchImpl, async response => {
    if (!response.body) throw new Error("Archive response has no body");
    const contentLength = response.headers.get("content-length");
    if (contentLength && Number(contentLength) !== manifest.archiveSizeBytes) throw new Error("Archive Content-Length differs from manifest");
    let bytes = 0;
    const limiter = new Transform({ transform(chunk, encoding, callback) {
      bytes += chunk.length;
      callback(bytes > manifest.archiveSizeBytes ? new Error("Archive exceeds manifest byte size") : null, chunk);
    } });
    await pipeline(Readable.fromWeb(response.body), limiter, createWriteStream(archivePath, { flags: "wx", mode: 0o600 }));
    if (bytes !== manifest.archiveSizeBytes) throw new Error("Downloaded archive byte size differs from manifest");
  });
}

export async function verifyArchiveFile(archivePath, manifest) {
  const info = await fs.lstat(archivePath);
  if (!info.isFile() || info.isSymbolicLink() || info.size !== manifest.archiveSizeBytes) throw new Error("Archive size or file type differs from manifest");
  const hash = createHash("sha256");
  for await (const chunk of createReadStream(archivePath)) hash.update(chunk);
  if (hash.digest("hex") !== manifest.archiveSha256) throw new Error("Archive SHA-256 mismatch");
}

function runExecutable(command, args, timeoutMs = 30_000) {
  const result = spawnSync(command, args, { encoding: "utf8", windowsHide: true, timeout: timeoutMs,
    maxBuffer: 2 * 1024 * 1024, shell: false });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`Child command failed (${result.status}): ${(result.stderr || result.stdout || "").trim()}`);
  return (result.stdout || result.stderr || "").trim();
}

export function runPythonHelper(pythonPath, args, timeoutMs = 30_000) {
  const output = runExecutable(pythonPath, [HELPER, ...args], timeoutMs);
  const result = JSON.parse(output);
  if (result.ok !== true) throw new Error("Python archive helper did not succeed");
  return result;
}

export function extractArchive(manifest, archivePath, outputPath, pythonPath) {
  return runPythonHelper(pythonPath, ["extract", "--archive", archivePath, "--format", manifest.format,
    "--root-name", manifest.runtimeRootDirectoryName, "--output", outputPath], 10 * 60_000);
}

async function requireType(filePath, type) {
  const info = await fs.lstat(filePath);
  if (info.isSymbolicLink() || (type === "file" ? !info.isFile() : !info.isDirectory())) throw new Error(`Runtime entry has wrong type: ${path.basename(filePath)}`);
}

export async function validateRuntime(runtimeRoot, manifest, { run = runExecutable } = {}) {
  const metadataPath = path.join(runtimeRoot, "runtime.json");
  await requireType(runtimeRoot, "directory");
  await requireType(metadataPath, "file");
  const metadata = JSON.parse(await fs.readFile(metadataPath, "utf8"));
  const formatVersion = manifest?.bundleFormatVersion ?? metadata.bundleFormatVersion ?? 1;
  if (![1, 2].includes(formatVersion) || (metadata.bundleFormatVersion ?? 1) !== formatVersion) throw new Error("Runtime bundle format mismatch");
  if (metadata.targetPlatform !== "win32" || metadata.targetArch !== "x64") throw new Error("Runtime metadata target mismatch");
  if (!/^\d+(?:\.\d+){2,3}$/.test(metadata.bundleVersion ?? "")) throw new Error("Runtime metadata version is invalid");
  if (manifest && metadata.bundleVersion !== manifest.bundleVersion) throw new Error("Runtime metadata version differs from manifest");
  const dependencyRoot = formatVersion >= 2 ? path.join(runtimeRoot, "dependencies") : runtimeRoot;
  await requireType(dependencyRoot, "directory");
  const nodePath = path.join(dependencyRoot, "node", "bin", "node.exe");
  await requireType(path.dirname(path.dirname(nodePath)), "directory");
  await requireType(path.dirname(nodePath), "directory");
  await requireType(nodePath, "file");
  await requireType(path.join(dependencyRoot, "node", "node_modules"), "directory");
  await requireType(path.join(dependencyRoot, "bin"), "directory");
  const pythonRoot = path.join(dependencyRoot, "python");
  await requireType(pythonRoot, "directory");
  let pythonPath;
  for (const relative of ["python.exe", "python/python.exe", "bin/python.exe"]) {
    const candidate = path.join(pythonRoot, relative);
    try {
      await requireType(path.dirname(candidate), "directory");
      await requireType(candidate, "file");
      pythonPath = candidate;
      break;
    } catch (error) { if (error.code !== "ENOENT") throw error; }
  }
  if (!pythonPath) throw new Error("Runtime Python executable is missing");
  const nodeVersion = run(nodePath, ["--version"], 10_000);
  const pythonVersion = run(pythonPath, ["--version"], 10_000);
  if (!/^v\d+\.\d+\.\d+(?:[-+].*)?$/.test(nodeVersion) || !/^Python \d+\.\d+\.\d+/.test(pythonVersion)) throw new Error("Runtime executable version output is invalid");
  if (metadata.nodeVersion && metadata.nodeVersion !== nodeVersion) throw new Error("Runtime Node version differs from runtime.json");
  if (metadata.pythonVersion && `Python ${metadata.pythonVersion}` !== pythonVersion) throw new Error("Runtime Python version differs from runtime.json");
  return { bundleVersion: metadata.bundleVersion, bundleFormatVersion: formatVersion, nodeVersion, pythonVersion };
}

export function isWithin(parent, candidate) {
  const relative = path.relative(path.resolve(parent), path.resolve(candidate));
  return relative === "" || (!relative.startsWith(`..${path.sep}`) && relative !== ".." && !path.isAbsolute(relative));
}

async function assertPlainDirectoryChain(directory) {
  const absolute = path.resolve(directory);
  let current = absolute;
  while (true) {
    try { await requireType(current, "directory"); }
    catch (error) { if (error.code !== "ENOENT") throw error; }
    const parent = path.dirname(current);
    if (parent === current) break;
    current = parent;
  }
}

async function exists(filePath) {
  try { await fs.lstat(filePath); return true; }
  catch (error) { if (error.code === "ENOENT") return false; throw error; }
}

/** Transaction entry point; injectable I/O permits synthetic fixture tests. */
export async function installRuntime({ manifest, installRoot, pythonPath = "python", downloadTimeoutMs,
  download = downloadArchive, extract = extractArchive, validate = validateRuntime, log = console.log }) {
  manifest = validateManifest(manifest);
  installRoot = path.resolve(installRoot);
  await assertPlainDirectoryChain(installRoot);
  await fs.mkdir(installRoot, { recursive: true });
  const finalRoot = path.join(installRoot, RUNTIME_NAME);
  const lockPath = path.join(installRoot, `.${RUNTIME_NAME}.install.lock`);
  const token = randomUUID();
  const lock = await fs.open(lockPath, "wx", 0o600).catch(error => {
    if (error.code === "EEXIST") throw new Error("Another install or an unreleased lock exists; inspect it before retrying");
    throw error;
  });
  let stage;
  let backupRoot = null;
  let placedNew = false;
  let keepStage = false;
  try {
    await lock.writeFile(JSON.stringify({ schema: 1, pid: process.pid, token, createdAt: new Date().toISOString(), bundleVersion: manifest.bundleVersion }));
    await assertPlainDirectoryChain(installRoot);
    stage = await fs.mkdtemp(path.join(installRoot, "manual-runtime-install-"));
    const archivePath = path.join(stage, manifest.archiveName);
    const payloadPath = path.join(stage, "payload");
    const extractedRoot = path.join(payloadPath, RUNTIME_NAME);
    log(`Downloading verified bundle ${manifest.bundleVersion}`);
    await download(manifest, archivePath, { timeoutMs: downloadTimeoutMs });
    await verifyArchiveFile(archivePath, manifest);
    await extract(manifest, archivePath, payloadPath, pythonPath);
    await validate(extractedRoot, manifest);
    await assertPlainDirectoryChain(installRoot);
    if (await exists(finalRoot)) {
      await requireType(finalRoot, "directory");
      backupRoot = path.join(installRoot, `${RUNTIME_NAME}.previous-${randomUUID()}`);
      await fs.rename(finalRoot, backupRoot);
    }
    try {
      await fs.rename(extractedRoot, finalRoot);
      placedNew = true;
      const result = await validate(finalRoot, manifest);
      return { ...result, installed: true, finalRoot, backupRoot };
    } catch (failure) {
      try {
        if (placedNew && await exists(finalRoot)) {
          const failedRoot = path.join(installRoot, `${RUNTIME_NAME}.failed-${randomUUID()}`);
          await fs.rename(finalRoot, failedRoot);
          log(`Failed candidate retained at ${failedRoot}`);
        }
        if (backupRoot) await fs.rename(backupRoot, finalRoot);
      } catch (rollbackFailure) {
        keepStage = true;
        throw new AggregateError([failure, rollbackFailure], `Install and rollback failed. Preserve ${installRoot} and staging ${stage} for recovery.`);
      }
      throw new Error("Installation failed; the previous runtime was restored when one existed", { cause: failure });
    }
  } finally {
    await lock.close();
    try {
      const current = JSON.parse(await fs.readFile(lockPath, "utf8"));
      if (current.token === token) await fs.unlink(lockPath);
    } catch (error) { log(`Install lock requires manual inspection: ${error.message}`); }
    if (stage && !keepStage && isWithin(installRoot, stage) && path.basename(stage).startsWith("manual-runtime-install-")) {
      await fs.rm(stage, { recursive: true, force: true }).catch(error => log(`Staging cleanup requires inspection: ${error.message}`));
    }
  }
}

const HELP = `Legacy Codex workspace-dependencies runtime recovery (Windows x64).
  node legacy/install-codex-workspace-runtime-win10.mjs [--dry-run]
  node legacy/install-codex-workspace-runtime-win10.mjs --apply --expected-version VERSION [--python PATH]
  node legacy/install-codex-workspace-runtime-win10.mjs --doctor

Default: fetch only the official manifest and print a plan. No archive or file writes.
--apply                   Download, verify, stage and install; close Codex first.
--doctor                  Validate the installed runtime and execute --version only.
--expected-version V      Required with --apply; refuse if the reviewed V changed.
--python PATH             Python 3.10+ with gzip/xz support (default: python in PATH).
--timeout-seconds N        Manifest timeout, 1..3600 (default: 30).
--download-timeout-seconds N  Full download timeout (default: 900).

This community recovery tool uses an internal, unsupported manifest/layout.
It installs workspace dependencies; it does not install Codex or provision a sandbox.
`;

export async function main(argv = process.argv.slice(2)) {
  const options = parseArgs(argv);
  if (options.help) { console.log(HELP); return; }
  const installRoot = path.join(os.homedir(), ".cache", "codex-runtimes");
  const finalRoot = path.join(installRoot, RUNTIME_NAME);
  if (options.doctor) {
    console.log(JSON.stringify({ mode: "doctor", ...await validateRuntime(finalRoot) }, null, 2));
    return;
  }
  const manifest = await fetchManifest(options);
  const plan = { mode: options.apply ? "apply" : "dry-run", bundleVersion: manifest.bundleVersion,
    format: manifest.format, archiveBytes: manifest.archiveSizeBytes, archiveSha256: manifest.archiveSha256,
    archiveUrl: manifest.archiveUrl, destination: "~/.cache/codex-runtimes/codex-primary-runtime",
    existingRuntime: await exists(finalRoot) };
  console.log(JSON.stringify(plan, null, 2));
  if (!options.apply) return;
  if (process.platform !== "win32" || process.arch !== "x64") throw new Error("--apply supports Windows x64 only");
  const python = runPythonHelper(options.pythonPath, ["probe"], options.timeoutMs);
  if (isWithin(finalRoot, process.execPath) || isWithin(finalRoot, python.pythonExecutable)) {
    throw new Error("Run this installer with independent Node and Python executables outside the runtime being replaced");
  }
  const result = await installRuntime({ manifest, installRoot, pythonPath: options.pythonPath,
    downloadTimeoutMs: options.downloadTimeoutMs });
  console.log(JSON.stringify(result, null, 2));
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(error => { console.error(error.stack ?? String(error)); if (error.cause) console.error(`Cause: ${error.cause.message}`); process.exitCode = 1; });
}

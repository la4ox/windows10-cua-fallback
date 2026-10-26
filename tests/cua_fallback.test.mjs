import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { captureWindow, clickAndCapture } from "../windows-cua-fallback/scripts/cua_fallback.mjs";

// Exercise execFile and argument boundaries using a tiny JSON-only child process.
// No GUI API, Python stub dependency, or Windows input is involved in these tests.
async function fixture(t, verification = { valid: true, hwnd: 123, reasons: [], coordinate_input_supported: true }) {
  const directory = await mkdtemp(path.join(os.tmpdir(), "cua fallback tests "));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const scriptPath = path.join(directory, "fixture child.mjs");
  await writeFile(scriptPath, `
import { readFile } from "node:fs/promises";
const args = process.argv.slice(2);
const value = flag => args[args.indexOf(flag) + 1];
let config = {};
try { config = JSON.parse(await readFile(value("--metadata"), "utf8")); } catch {}
if (args[0] === "verify") {
  console.log(JSON.stringify({ ...config, argv: args }));
  if (config.valid === false) process.exitCode = 2;
} else {
  console.log(JSON.stringify({ ok: true, hwnd: Number(value("--hwnd")), ...config, argv: args }));
}
`, "utf8");
  const metadataPath = path.join(directory, "before snapshot.json");
  await writeFile(metadataPath, JSON.stringify(verification), "utf8");
  const calls = [];
  const window = { app: "calculator.test", id: 123 };
  const sky = {
    activate_window: async ({ window: target }) => { calls.push(["activate", target.id]); },
    get_window_state: async ({ window: target }) => {
      calls.push(["observe", target.id]);
      return { window: target, accessibility: null };
    },
    click: async ({ window: target, x, y }) => { calls.push(["click", target.id, x, y]); },
  };
  return {
    directory, calls, sky, window, pythonPath: process.execPath, scriptPath, metadataPath,
    outputPathAfter: path.join(directory, "after screenshot.png"),
    metadataPathAfter: path.join(directory, "after snapshot.json"), x: 10, y: 20,
  };
}

test("valid target is verified against the observed HWND before a single click", async t => {
  const f = await fixture(t);
  const result = await clickAndCapture(f);
  const index = result.verification.argv.indexOf("--expected-hwnd");
  assert.equal(result.verification.argv[index + 1], "123");
  assert.deepEqual(f.calls.map(call => call[0]), ["activate", "observe", "click", "observe"]);
  assert.deepEqual(result.click, { x: 10, y: 20 });
  assert.equal(result.capture.hwnd, f.window.id);
});

test("a valid snapshot of a different window cannot authorize input", async t => {
  const f = await fixture(t, { valid: true, hwnd: 999, reasons: [] });
  await assert.rejects(clickAndCapture(f), { code: "ERR_SNAPSHOT_REJECTED" });
  assert.equal(f.calls.filter(call => call[0] === "click").length, 0);
});

test("Python exit 2 rejects the snapshot without attempting input", async t => {
  const f = await fixture(t, { valid: false, hwnd: 123, reasons: ["stale"] });
  await assert.rejects(clickAndCapture(f), { code: "ERR_SNAPSHOT_REJECTED" });
  assert.equal(f.calls.filter(call => call[0] === "click").length, 0);
});

test("an observed window replacement is rejected before verification or input", async t => {
  const f = await fixture(t);
  f.sky.get_window_state = async () => ({ window: { ...f.window, id: 456 } });
  await assert.rejects(clickAndCapture(f));
  assert.equal(f.calls.filter(call => call[0] === "click").length, 0);
});

test("invalid HWND, coordinates, and age limits cause no UI call", async t => {
  const f = await fixture(t);
  const changes = [
    { window: { ...f.window, id: 0 } }, { window: { ...f.window, id: -1 } },
    { x: -1 }, { x: 0.5 }, { y: Infinity }, { maxAge: NaN }, { maxAge: Infinity },
    { maxAge: -1 }, { method: "desktop" }, { method: "auto" },
  ];
  for (const change of changes) {
    await assert.rejects(clickAndCapture({ ...f, ...change }), TypeError);
  }
  assert.deepEqual(f.calls, []);
});

test("failed click returns unknown outcome and never retries input", async t => {
  const f = await fixture(t);
  let attempts = 0;
  f.sky.click = async () => { attempts += 1; throw new Error("input status unavailable"); };
  await assert.rejects(clickAndCapture(f), { code: "ERR_INPUT_OUTCOME_UNKNOWN" });
  assert.equal(attempts, 1);
});

test("failed post-click capture reports unknown outcome without a second click", async t => {
  const f = await fixture(t);
  await writeFile(f.metadataPathAfter, JSON.stringify({ ok: false, error: "capture failed" }), "utf8");
  await assert.rejects(clickAndCapture(f), { code: "ERR_INPUT_OUTCOME_UNKNOWN" });
  assert.equal(f.calls.filter(call => call[0] === "click").length, 1);
});

test("capture passes paths containing spaces intact and binds the returned HWND", async t => {
  const f = await fixture(t);
  // An empty response file gives the capture fixture its ordinary success result.
  await writeFile(f.metadataPath, "{}", "utf8");
  const result = await captureWindow({ ...f, outputPath: f.outputPathAfter });
  const args = result.capture.argv;
  assert.equal(args[args.indexOf("--output") + 1], f.outputPathAfter);
  assert.equal(args[args.indexOf("--metadata") + 1], f.metadataPath);
  assert.equal(result.capture.hwnd, 123);
  assert.equal(args[args.indexOf("--method") + 1], "printwindow");
  assert.equal(f.calls.filter(call => call[0] === "click").length, 0);
});

test("capture rejects a child response identifying a different HWND", async t => {
  const f = await fixture(t);
  await writeFile(f.metadataPath, JSON.stringify({ hwnd: 999 }), "utf8");
  await assert.rejects(captureWindow({ ...f, outputPath: f.outputPathAfter }));
  assert.equal(f.calls.filter(call => call[0] === "click").length, 0);
});

test("ambiguous coordinate frames reject input with a structured reason", async t => {
  const f = await fixture(t, {
    valid: false, hwnd: 123, coordinate_input_supported: false,
    reasons: ["frame origins differ"], reason_codes: ["ambiguous_frame"],
  });
  await assert.rejects(clickAndCapture(f), error =>
    error.code === "ERR_SNAPSHOT_REJECTED" && error.reasonCodes.includes("ambiguous_frame"));
  assert.equal(f.calls.filter(call => call[0] === "click").length, 0);
});

test("legacy verification without coordinate authorization cannot trigger input", async t => {
  const f = await fixture(t, { valid: true, hwnd: 123, reasons: [] });
  await assert.rejects(clickAndCapture(f), { code: "ERR_SNAPSHOT_REJECTED" });
  assert.equal(f.calls.filter(call => call[0] === "click").length, 0);
});

test("explicit screen capture remains available without enabling input", async t => {
  const f = await fixture(t);
  await writeFile(f.metadataPath, "{}", "utf8");
  const result = await captureWindow({ ...f, method: "screen", outputPath: f.outputPathAfter });
  assert.equal(result.capture.argv[result.capture.argv.indexOf("--method") + 1], "screen");
  assert.equal(f.calls.filter(call => call[0] === "click").length, 0);
});

import { execFile as execFileCallback } from "node:child_process";
import { promisify } from "node:util";

const execFile = promisify(execFileCallback);
const HWND_CONTRACT = "This fallback requires the returned @oai/sky Window.id to be a native HWND.";

function requireString(value, label) {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new TypeError(`${label} must be a non-empty string`);
  }
  return value;
}

function requireCoordinate(value, label) {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new TypeError(`${label} must be a non-negative safe integer`);
  }
  return value;
}

function requireNonNegativeFinite(value, label) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    throw new TypeError(`${label} must be a finite non-negative number`);
  }
  return value;
}

function requireWindow(window) {
  if (typeof window !== "object" || window === null ||
      typeof window.app !== "string" || window.app.length === 0 ||
      !Number.isSafeInteger(window.id) || window.id <= 0) {
    throw new TypeError(`window must be a returned @oai/sky window with a positive id. ${HWND_CONTRACT}`);
  }
  return window;
}

function requireMethod(method) {
  if (!["printwindow", "screen"].includes(method)) {
    throw new TypeError("method must be printwindow or explicitly requested screen");
  }
  return method;
}

function requireSameWindow(expected, actual) {
  requireWindow(actual);
  if (expected.id !== actual.id || expected.app !== actual.app) {
    throw new Error("The observed target window changed; select and capture it again.");
  }
}

function parseJsonOutput(stdout, label) {
  const lines = String(stdout).split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  if (lines.length === 0) throw new Error(`${label} returned no JSON output`);
  try {
    return JSON.parse(lines.at(-1));
  } catch (error) {
    throw new Error(`${label} returned invalid JSON`, { cause: error });
  }
}

async function runPython(pythonPath, scriptPath, args, label) {
  let stdout;
  let stderr;
  try {
    ({ stdout, stderr } = await execFile(pythonPath, [scriptPath, ...args.map(String)], {
      windowsHide: true,
      timeout: 30_000,
      maxBuffer: 4 * 1024 * 1024,
      encoding: "utf8",
    }));
  } catch (error) {
    // The verifier deliberately exits 2 when its checks reject a snapshot.
    // Keep that rejection structured, without treating other process failures as valid results.
    if (args[0] !== "verify" || error.code !== 2) throw error;
    const rejection = parseJsonOutput(error.stdout, label);
    if (rejection.valid !== false) throw error;
    return rejection;
  }
  const result = parseJsonOutput(stdout, label);
  if (result.ok === false) {
    throw new Error(`${label} failed: ${result.error ?? stderr ?? "unknown error"}`);
  }
  return result;
}

async function observeText(sky, window) {
  const state = await sky.get_window_state({ window, include_screenshot: false, include_text: true });
  requireSameWindow(window, state?.window);
  return { state, window: state.window };
}

function requireCaptureTarget(capture, window) {
  if (capture.hwnd !== window.id) {
    throw new Error(`Capture did not identify the selected HWND. ${HWND_CONTRACT}`);
  }
}

export async function captureWindow({
  sky, window, pythonPath, scriptPath, outputPath, metadataPath, method = "printwindow",
}) {
  requireWindow(window);
  requireString(pythonPath, "pythonPath");
  requireString(scriptPath, "scriptPath");
  requireString(outputPath, "outputPath");
  requireString(metadataPath, "metadataPath");
  requireMethod(method);
  await sky.activate_window({ window });
  const observed = await observeText(sky, window);
  const capture = await runPython(pythonPath, scriptPath, [
    "capture", "--hwnd", observed.window.id,
    "--output", outputPath, "--metadata", metadataPath, "--method", method,
  ], "window capture");
  requireCaptureTarget(capture, observed.window);
  return { ...observed, capture };
}

export async function clickAndCapture({
  sky, window, pythonPath, scriptPath, metadataPath, x, y,
  outputPathAfter, metadataPathAfter, maxAge = 300, method = "printwindow",
}) {
  requireWindow(window);
  requireString(pythonPath, "pythonPath");
  requireString(scriptPath, "scriptPath");
  requireString(metadataPath, "metadataPath");
  requireString(outputPathAfter, "outputPathAfter");
  requireString(metadataPathAfter, "metadataPathAfter");
  const clickX = requireCoordinate(x, "x");
  const clickY = requireCoordinate(y, "y");
  const verifiedMaxAge = requireNonNegativeFinite(maxAge, "maxAge");
  requireMethod(method);
  await sky.activate_window({ window });
  const before = await observeText(sky, window);
  const verification = await runPython(pythonPath, scriptPath, [
    "verify", "--metadata", metadataPath, "--expected-hwnd", before.window.id,
    "--x", clickX, "--y", clickY, "--max-age", verifiedMaxAge,
  ], "snapshot verification");
  if (verification.valid !== true || verification.hwnd !== before.window.id ||
      verification.coordinate_input_supported !== true) {
    const error = new Error(`Snapshot verification rejected the selected target: ${JSON.stringify(verification.reasons ?? [])}`);
    error.code = "ERR_SNAPSHOT_REJECTED";
    error.reasonCodes = verification.reason_codes ?? [];
    throw error;
  }

  try {
    await sky.click({ window: before.window, x: clickX, y: clickY });
    const after = await observeText(sky, before.window);
    const capture = await runPython(pythonPath, scriptPath, [
      "capture", "--hwnd", after.window.id, "--output", outputPathAfter,
      "--metadata", metadataPathAfter, "--method", method,
    ], "post-click capture");
    requireCaptureTarget(capture, after.window);
    return { ...after, verification, capture, click: { x: clickX, y: clickY } };
  } catch (cause) {
    const error = new Error(
      "Coordinate input was attempted; its outcome may be unknown. Do not retry automatically. Re-observe and capture the target before deciding the next action.",
      { cause },
    );
    error.code = "ERR_INPUT_OUTCOME_UNKNOWN";
    throw error;
  }
}

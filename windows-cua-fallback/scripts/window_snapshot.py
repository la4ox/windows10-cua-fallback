from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

from PIL import Image, ImageGrab, ImageStat


HWND_CONTRACT = (
    "The supplied @oai/sky Window.id must be a native HWND; this is a legacy "
    "runtime compatibility requirement, not a public cross-version guarantee."
)
FUTURE_TOLERANCE_SECONDS = 1.0
RECT_FIELDS = ("left", "top", "right", "bottom", "width", "height")
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DIB_RGB_COLORS = 0
BI_RGB = 0
PW_RENDERFULLCONTENT = 0x00000002


class RECT(ctypes.Structure):
    _fields_ = [(name, ctypes.c_long) for name in ("left", "top", "right", "bottom")]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class RGBQUAD(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ubyte) for name in ("rgbBlue", "rgbGreen", "rgbRed", "rgbReserved")]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", RGBQUAD * 1)]


user32 = gdi32 = dwmapi = None
if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowDC.argtypes = [wintypes.HWND]
    user32.GetWindowDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    user32.PrintWindow.restype = wintypes.BOOL
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL
    gdi32.CreateDIBSection.argtypes = [
        wintypes.HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD,
    ]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.GdiFlush.restype = wintypes.BOOL
    dwmapi.DwmGetWindowAttribute.argtypes = [
        wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
    ]
    dwmapi.DwmGetWindowAttribute.restype = ctypes.HRESULT


def set_dpi_awareness() -> None:
    setter = getattr(user32, "SetProcessDpiAwarenessContext", None)
    if setter is not None:
        setter.argtypes = [ctypes.c_void_p]
        setter.restype = wintypes.BOOL
        setter(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2


def parse_hwnd(value: str) -> int:
    try:
        hwnd = int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("HWND must be a decimal or 0x-prefixed integer") from exc
    if hwnd <= 0:
        raise argparse.ArgumentTypeError("HWND must be positive")
    return hwnd


def non_negative_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def non_negative_finite_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be a number") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("value must be finite and non-negative")
    return parsed


def require_window(hwnd: int) -> None:
    if type(hwnd) is not int or hwnd <= 0:
        raise RuntimeError(f"HWND must be a positive integer. {HWND_CONTRACT}")
    if not user32.IsWindow(wintypes.HWND(hwnd)):
        raise RuntimeError(f"HWND {hwnd} is not a live native window. {HWND_CONTRACT}")


def window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(wintypes.HWND(hwnd))
    buffer = ctypes.create_unicode_buffer(max(1, length + 1))
    user32.GetWindowTextW(wintypes.HWND(hwnd), buffer, len(buffer))
    return buffer.value


def window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    if not user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid)) or not pid.value:
        raise RuntimeError("Could not determine the selected window's process identity")
    return int(pid.value)


def rect_values(rect: RECT, hwnd: int) -> dict[str, int]:
    width, height = int(rect.right - rect.left), int(rect.bottom - rect.top)
    if width <= 0 or height <= 0:
        raise RuntimeError(f"HWND {hwnd} has empty bounds")
    return {
        "left": int(rect.left), "top": int(rect.top), "right": int(rect.right),
        "bottom": int(rect.bottom), "width": width, "height": height,
    }


def window_rect(hwnd: int) -> dict[str, int]:
    """GetWindowRect includes invisible resize borders and matches PrintWindow's full render."""
    rect = RECT()
    if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        raise ctypes.WinError(ctypes.get_last_error())
    return rect_values(rect, hwnd)


def dwm_window_rect(hwnd: int) -> dict[str, int] | None:
    """DWM's visible frame can have a different origin and size from GetWindowRect."""
    rect = RECT()
    hr = dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd), wintypes.DWORD(DWMWA_EXTENDED_FRAME_BOUNDS),
        ctypes.byref(rect), ctypes.sizeof(rect),
    )
    return rect_values(rect, hwnd) if hr == 0 else None


def window_dpi(hwnd: int) -> int | None:
    getter = getattr(user32, "GetDpiForWindow", None)
    if getter is None:
        return None
    getter.argtypes = [wintypes.HWND]
    getter.restype = wintypes.UINT
    return int(getter(wintypes.HWND(hwnd))) or None


def read_window_state(hwnd: int) -> dict[str, object]:
    require_window(hwnd)
    raw_rect = window_rect(hwnd)
    return {
        "hwnd": hwnd, "pid": window_pid(hwnd), "title": window_title(hwnd),
        "visible": bool(user32.IsWindowVisible(wintypes.HWND(hwnd))),
        "foreground_hwnd": int(user32.GetForegroundWindow() or 0),
        "raw_rect": raw_rect, "dwm_rect": dwm_window_rect(hwnd),
        "rect": raw_rect, "dpi": window_dpi(hwnd),
    }


def valid_rect(rect: object) -> bool:
    return (
        isinstance(rect, dict) and all(type(rect.get(key)) is int for key in RECT_FIELDS)
        and rect["width"] > 0 and rect["height"] > 0
        and rect["right"] - rect["left"] == rect["width"]
        and rect["bottom"] - rect["top"] == rect["height"]
    )


def capture_rectangle(state: dict[str, object], method: str) -> dict[str, int]:
    key = "raw_rect" if method == "printwindow" else "dwm_rect" if method == "screen" else None
    if key is None:
        raise ValueError("Capture method must be printwindow or explicitly requested screen")
    rect = state.get(key)
    if not valid_rect(rect):
        raise RuntimeError(f"Cannot establish {key} for the requested capture method")
    return dict(rect)


def rect_changed(before: dict[str, object], current: dict[str, int], tolerance: int) -> bool:
    if type(tolerance) is not int or tolerance < 0:
        raise ValueError("rectangle tolerance must be a non-negative integer")
    return any(abs(int(before[key]) - int(current[key])) > tolerance for key in RECT_FIELDS)


def ensure_capture_stable(before: dict[str, object], after: dict[str, object], *, screen: bool) -> None:
    if not after["visible"] or before["hwnd"] != after["hwnd"] or before["pid"] != after["pid"]:
        raise RuntimeError("Window identity or visibility changed during capture")
    # Keep both coordinate frames stable even when this method uses only one of them.
    if before.get("raw_rect") != after.get("raw_rect") or before.get("dwm_rect") != after.get("dwm_rect") or before["dpi"] != after["dpi"]:
        raise RuntimeError("Window geometry or DPI changed during capture")
    if screen and (before["foreground_hwnd"] != before["hwnd"] or after["foreground_hwnd"] != before["hwnd"]):
        raise RuntimeError("Screen fallback lost foreground during capture")


def image_variation(image: Image.Image) -> float:
    sample = image.convert("RGB")
    sample.thumbnail((96, 96))
    return float(max(ImageStat.Stat(sample).stddev))


def capture_printwindow(hwnd: int, rect: dict[str, int]) -> tuple[Image.Image, dict[str, object]]:
    width, height = rect["width"], rect["height"]
    source_dc = user32.GetWindowDC(wintypes.HWND(hwnd))
    if not source_dc:
        raise ctypes.WinError(ctypes.get_last_error())
    memory_dc = gdi32.CreateCompatibleDC(source_dc)
    if not memory_dc:
        user32.ReleaseDC(wintypes.HWND(hwnd), source_dc)
        raise ctypes.WinError(ctypes.get_last_error())
    bitmap_info = BITMAPINFO()
    bitmap_info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bitmap_info.bmiHeader.biWidth = width
    bitmap_info.bmiHeader.biHeight = -height
    bitmap_info.bmiHeader.biPlanes = 1
    bitmap_info.bmiHeader.biBitCount = 32
    bitmap_info.bmiHeader.biCompression = BI_RGB
    bits = ctypes.c_void_p()
    bitmap = gdi32.CreateDIBSection(source_dc, ctypes.byref(bitmap_info), DIB_RGB_COLORS, ctypes.byref(bits), None, 0)
    if not bitmap or not bits.value:
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(wintypes.HWND(hwnd), source_dc)
        raise ctypes.WinError(ctypes.get_last_error())
    previous = gdi32.SelectObject(memory_dc, bitmap)
    try:
        result = bool(user32.PrintWindow(wintypes.HWND(hwnd), memory_dc, PW_RENDERFULLCONTENT))
        gdi32.GdiFlush()
        raw = ctypes.string_at(bits.value, width * height * 4)
        image = Image.frombytes("RGB", (width, height), raw, "raw", "BGRX")
        return image, {"returned": result, "variation": image_variation(image)}
    finally:
        if previous:
            gdi32.SelectObject(memory_dc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(wintypes.HWND(hwnd), source_dc)


def capture_screen(hwnd: int, rect: dict[str, int]) -> Image.Image:
    before = read_window_state(hwnd)
    if not before["visible"] or before["foreground_hwnd"] != hwnd:
        raise RuntimeError(f"Screen fallback requires HWND {hwnd} to be visible and foreground")
    if rect_changed(rect, capture_rectangle(before, "screen"), 0):
        raise RuntimeError("Window geometry changed before screen capture")
    image = ImageGrab.grab(
        bbox=(rect["left"], rect["top"], rect["right"], rect["bottom"]), all_screens=True,
    ).convert("RGB")
    # Discard the pixels if focus, process, scale, or geometry changed during the grab.
    ensure_capture_stable(before, read_window_state(hwnd), screen=True)
    return image


def atomic_save_image(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    image.save(temporary, format="PNG")
    os.replace(temporary, path)


def atomic_write_json(value: dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def capture(args: argparse.Namespace) -> int:
    hwnd = args.hwnd
    before = read_window_state(hwnd)
    if not before["visible"]:
        raise RuntimeError(f"HWND {hwnd} is not visible")
    output = Path(args.output).expanduser().resolve()
    metadata_path = Path(args.metadata).expanduser().resolve()
    if output == metadata_path:
        raise ValueError("Image and metadata paths must be different")
    rect = capture_rectangle(before, args.method)
    print_details = None
    selected_method = args.method
    if args.method == "printwindow":
        image, print_details = capture_printwindow(hwnd, rect)
        if not print_details["returned"]:
            raise RuntimeError("PrintWindow returned failure")
    else:
        image = capture_screen(hwnd, rect)
    captured_ns = time.time_ns()
    after = read_window_state(hwnd)
    ensure_capture_stable(before, after, screen=selected_method == "screen")
    if image.size != (rect["width"], rect["height"]):
        raise RuntimeError("Captured image dimensions do not match the selected window")
    # No files are committed until the post-grab identity/geometry checks succeed.
    atomic_save_image(image, output)
    metadata = {
        "schema": 1, "captured_at_utc": datetime.fromtimestamp(captured_ns / 1_000_000_000, tz=timezone.utc).isoformat(),
        "captured_at_unix_ns": captured_ns, **after,
        "rect": rect, "capture_rect": rect,
        "capture_origin": {"x": rect["left"], "y": rect["top"]},
        "capture_rect_source": "GetWindowRect" if selected_method == "printwindow" else "DWM_EXTENDED_FRAME_BOUNDS",
        "coordinate_input_supported": valid_rect(after["raw_rect"]) and valid_rect(after["dwm_rect"]) and after["raw_rect"] == after["dwm_rect"] and type(after["dpi"]) is int and after["dpi"] > 0,
        "window_id_contract": HWND_CONTRACT,
        "foreground_matches": after["foreground_hwnd"] == hwnd,
        "method": selected_method, "printwindow": print_details,
        "coordinate_space": "capture-relative physical pixels from capture_origin; sky.click origin is undocumented",
        "image": {"path": str(output), "width": image.width, "height": image.height, "sha256": sha256_file(output)},
    }
    atomic_write_json(metadata, metadata_path)
    print(json.dumps({"ok": True, "metadata": str(metadata_path), **metadata}, ensure_ascii=True))
    return 0


def validate_snapshot_state(
    metadata: dict[str, object], current: dict[str, object] | None, *, now_ns: int,
    max_age: float, rect_tolerance: int = 0, expected_hwnd: int | None = None,
    require_foreground: bool = False, x: int | None = None, y: int | None = None,
) -> dict[str, object]:
    """Validate metadata against a separately observed state, without acquiring pixels or input."""
    if not math.isfinite(max_age) or max_age < 0:
        raise ValueError("max_age must be finite and non-negative")
    if type(rect_tolerance) is not int or rect_tolerance < 0:
        raise ValueError("rect_tolerance must be a non-negative integer")
    if expected_hwnd is not None and (type(expected_hwnd) is not int or expected_hwnd <= 0):
        raise ValueError("expected_hwnd must be a positive integer")
    reasons, codes = [], []

    def reject(code: str, message: str) -> None:
        codes.append(code)
        reasons.append(message)

    if metadata.get("schema") != 1:
        reject("schema", "Unsupported metadata schema")
    hwnd = metadata.get("hwnd")
    if type(hwnd) is not int or hwnd <= 0:
        reject("hwnd", f"Snapshot does not identify a positive native HWND. {HWND_CONTRACT}")
    if expected_hwnd is not None and hwnd != expected_hwnd:
        reject("target", "Snapshot belongs to a different selected window")
    method = metadata.get("method")
    if method not in {"screen", "printwindow"}:
        reject("method", "Snapshot capture method is unsupported")
    coordinate_requested = x is not None or y is not None
    saved_raw, saved_dwm = metadata.get("raw_rect"), metadata.get("dwm_rect")
    saved_frames_valid = valid_rect(saved_raw) and valid_rect(saved_dwm)
    if not saved_frames_valid:
        reject("frame_metadata", "Both raw and DWM rectangles are required for verification; capture a new snapshot")
    saved_frames_equal = saved_frames_valid and saved_raw == saved_dwm
    current_frames_equal = False
    if coordinate_requested and saved_frames_valid and not saved_frames_equal:
        reject("ambiguous_frame", "Raw and DWM coordinate frames differ; the sky.click origin is undocumented, so only capture is available")
    capture_rect = metadata.get("capture_rect")
    if not valid_rect(capture_rect):
        reject("capture_rect", "Snapshot capture rectangle is missing or invalid")
    else:
        expected_rect = saved_raw if method == "printwindow" else saved_dwm
        expected_source = "GetWindowRect" if method == "printwindow" else "DWM_EXTENDED_FRAME_BOUNDS"
        if capture_rect != expected_rect or metadata.get("rect") != capture_rect:
            reject("capture_rect", "Snapshot rectangle does not match its capture method")
        if metadata.get("capture_origin") != {"x": capture_rect["left"], "y": capture_rect["top"]}:
            reject("capture_origin", "Snapshot capture origin differs from its rectangle")
        if metadata.get("capture_rect_source") != expected_source:
            reject("capture_rect", "Snapshot rectangle source does not match its capture method")
    if current is None:
        reject("live", "Window is no longer live")
    else:
        if current.get("hwnd") != hwnd:
            reject("target", "Observed native HWND differs from the snapshot")
        if not current.get("visible"):
            reject("visible", "Window is not visible")
        if type(metadata.get("pid")) is not int or metadata.get("pid", 0) <= 0 or current.get("pid") != metadata.get("pid"):
            reject("pid", "Window process identity changed or is unavailable")
        current_raw, current_dwm = current.get("raw_rect"), current.get("dwm_rect")
        current_frames_valid = valid_rect(current_raw) and valid_rect(current_dwm)
        current_frames_equal = current_frames_valid and current_raw == current_dwm
        if not current_frames_valid:
            reject("frame_current", "Current raw and DWM rectangles cannot both be established")
        if saved_frames_valid and current_frames_valid:
            for key in ("raw_rect", "dwm_rect"):
                if rect_changed(metadata[key], current[key], rect_tolerance):
                    reject("rect", f"Window {key} geometry changed")
        if coordinate_requested and current_frames_valid and not current_frames_equal and "ambiguous_frame" not in codes:
            reject("ambiguous_frame", "Current raw and DWM coordinate frames differ; coordinate input cannot be authorized")
        captured_dpi = metadata.get("dpi")
        if type(captured_dpi) is not int or captured_dpi <= 0 or current.get("dpi") != captured_dpi:
            reject("dpi", "Window DPI changed or cannot be verified")
        # Screen pixels describe the visible desktop, unlike a PrintWindow render.
        if (require_foreground or method == "screen") and current.get("foreground_hwnd") != hwnd:
            reject("foreground", "Screen fallback target is no longer foreground")
    captured_ns = metadata.get("captured_at_unix_ns")
    age_seconds = None
    if type(captured_ns) is not int or captured_ns <= 0:
        reject("timestamp", "Snapshot timestamp is invalid")
    else:
        age_seconds = (now_ns - captured_ns) / 1_000_000_000
        if age_seconds < -FUTURE_TOLERANCE_SECONDS:
            reject("future", "Snapshot timestamp is materially in the future")
        elif age_seconds > max_age:
            reject("age", f"Snapshot age {age_seconds:.3f}s exceeds {max_age}s")
    image = metadata.get("image")
    if not isinstance(image, dict) or any(type(image.get(key)) is not int or image[key] <= 0 for key in ("width", "height")):
        reject("dimensions", "Snapshot image dimensions are invalid")
        image = {}
    else:
        rect = metadata.get("capture_rect", {})
        if not isinstance(rect, dict) or image["width"] != rect.get("width") or image["height"] != rect.get("height"):
            reject("dimensions", "Snapshot image and window dimensions differ")
    if x is not None or y is not None:
        if type(x) is not int or type(y) is not int:
            reject("point", "Both coordinates must be integers")
        elif x < 0 or y < 0 or x >= image.get("width", 0) or y >= image.get("height", 0):
            reject("bounds", "Point is outside the captured image")
    return {
        "valid": not reasons, "reasons": reasons, "reason_codes": codes, "hwnd": hwnd,
        "expected_hwnd": expected_hwnd, "foreground_hwnd": None if current is None else current.get("foreground_hwnd"),
        "age_seconds": None if age_seconds is None else round(age_seconds, 3),
        "current_rect": None if current is None else current.get("rect"),
        "current_raw_rect": None if current is None else current.get("raw_rect"),
        "current_dwm_rect": None if current is None else current.get("dwm_rect"),
        "capture_rect": capture_rect, "capture_origin": metadata.get("capture_origin"),
        "current_pid": None if current is None else current.get("pid"),
        "current_dpi": None if current is None else current.get("dpi"),
        "foreground_required": require_foreground or method == "screen",
        "coordinate_input_supported": not reasons and saved_frames_equal and current_frames_equal,
        "window_id_contract": HWND_CONTRACT,
        "point": None if x is None and y is None else {"x": x, "y": y},
    }


def verify(args: argparse.Namespace) -> int:
    metadata = json.loads(Path(args.metadata).expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise ValueError("Snapshot metadata must be a JSON object")
    hwnd = metadata.get("hwnd")
    current = None
    if type(hwnd) is int and hwnd > 0 and user32.IsWindow(wintypes.HWND(hwnd)):
        current = read_window_state(hwnd)
    result = validate_snapshot_state(
        metadata, current, now_ns=time.time_ns(), max_age=args.max_age,
        rect_tolerance=args.rect_tolerance, expected_hwnd=args.expected_hwnd,
        require_foreground=args.require_foreground, x=args.x, y=args.y,
    )

    def reject(code: str, message: str) -> None:
        result["reason_codes"].append(code)
        result["reasons"].append(message)
        result["valid"] = False
        result["coordinate_input_supported"] = False

    image = metadata.get("image", {})
    image_path = Path(str(image.get("path", ""))) if isinstance(image, dict) else Path("")
    if not image_path.is_file():
        reject("image_missing", "Snapshot image is missing")
    elif sha256_file(image_path) != image.get("sha256"):
        reject("image_hash", "Snapshot image hash changed")
    else:
        try:
            with Image.open(image_path) as stored:
                if stored.format != "PNG" or stored.size != (image.get("width"), image.get("height")):
                    reject("image_dimensions", "Stored PNG dimensions differ from metadata")
                stored.verify()
        except (OSError, ValueError):
            reject("image_invalid", "Snapshot image is not a valid PNG")
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["valid"] else 2


def info(args: argparse.Namespace) -> int:
    print(json.dumps({**read_window_state(args.hwnd), "window_id_contract": HWND_CONTRACT}, ensure_ascii=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Windows native CUA screenshot fallback")
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture_parser = subparsers.add_parser("capture", help="capture exactly one native HWND")
    capture_parser.add_argument("--hwnd", required=True, type=parse_hwnd)
    capture_parser.add_argument("--output", required=True)
    capture_parser.add_argument("--metadata", required=True)
    capture_parser.add_argument("--method", choices=("printwindow", "screen"), default="printwindow")
    capture_parser.set_defaults(handler=capture)
    verify_parser = subparsers.add_parser("verify", help="verify a snapshot before coordinate input")
    verify_parser.add_argument("--metadata", required=True)
    verify_parser.add_argument("--expected-hwnd", type=parse_hwnd)
    verify_parser.add_argument("--x", type=int)
    verify_parser.add_argument("--y", type=int)
    verify_parser.add_argument("--max-age", type=non_negative_finite_float, default=120.0)
    verify_parser.add_argument("--rect-tolerance", type=non_negative_integer, default=0)
    verify_parser.add_argument("--require-foreground", action="store_true")
    verify_parser.set_defaults(handler=verify)
    info_parser = subparsers.add_parser("info", help="read native HWND geometry without capturing")
    info_parser.add_argument("--hwnd", required=True, type=parse_hwnd)
    info_parser.set_defaults(handler=info)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if sys.platform != "win32":
            raise RuntimeError("Live window capture/verification supports Windows only")
        set_dpi_awareness()
        return int(args.handler(args))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

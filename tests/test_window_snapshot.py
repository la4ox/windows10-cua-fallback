from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image


SCRIPT = Path(__file__).resolve().parents[1] / "windows-cua-fallback" / "scripts" / "window_snapshot.py"
SPEC = importlib.util.spec_from_file_location("window_snapshot", SCRIPT)
snapshot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(snapshot)

NOW = 1_800_000_000_000_000_000
RECT = {"left": 10, "top": 20, "right": 110, "bottom": 100, "width": 100, "height": 80}


def metadata(method="printwindow", *, raw=None, dwm=None):
    raw = dict(RECT if raw is None else raw)
    dwm = dict(RECT if dwm is None else dwm)
    captured = dict(raw if method == "printwindow" else dwm)
    return {
        "schema": 1, "hwnd": 123, "pid": 456, "visible": True, "method": method,
        "raw_rect": raw, "dwm_rect": dwm, "rect": captured, "capture_rect": dict(captured),
        "capture_origin": {"x": captured["left"], "y": captured["top"]},
        "capture_rect_source": "GetWindowRect" if method == "printwindow" else "DWM_EXTENDED_FRAME_BOUNDS",
        "dpi": 120, "captured_at_unix_ns": NOW - 1_000_000_000,
        "image": {"width": captured["width"], "height": captured["height"], "path": "unused.png", "sha256": "unused"},
    }


def state(*, raw=None, dwm=None):
    raw = dict(RECT if raw is None else raw)
    dwm = dict(RECT if dwm is None else dwm)
    return {
        "hwnd": 123, "pid": 456, "visible": True, "foreground_hwnd": 999,
        "raw_rect": raw, "dwm_rect": dwm, "rect": dict(raw), "dpi": 120,
    }


class SnapshotStateTests(unittest.TestCase):
    def validate(self, saved=None, current=None, **kwargs):
        return snapshot.validate_snapshot_state(
            metadata() if saved is None else saved, state() if current is None else current,
            now_ns=NOW, max_age=300, expected_hwnd=123, **kwargs,
        )

    def test_printwindow_allows_guarded_background_input(self):
        self.assertTrue(self.validate(x=99, y=79)["valid"])

    def test_screen_automatically_requires_foreground(self):
        saved = metadata("screen")
        rejected = self.validate(saved)
        self.assertFalse(rejected["valid"])
        self.assertIn("foreground", rejected["reason_codes"])
        current = state()
        current["foreground_hwnd"] = 123
        self.assertTrue(self.validate(saved, current)["valid"])

    def test_explicit_foreground_can_be_required_for_printwindow(self):
        self.assertFalse(self.validate(require_foreground=True)["valid"])

    def test_snapshot_is_bound_to_selected_target(self):
        saved = metadata()
        saved["hwnd"] = 124
        result = self.validate(saved)
        self.assertFalse(result["valid"])
        self.assertIn("target", result["reason_codes"])

    def test_missing_or_changed_dpi_rejects_coordinate_authorization(self):
        for dpi in (None, 96, 0):
            with self.subTest(dpi=dpi):
                current = state()
                current["dpi"] = dpi
                self.assertIn("dpi", self.validate(current=current)["reason_codes"])
        saved = metadata()
        saved.pop("dpi")
        self.assertIn("dpi", self.validate(saved)["reason_codes"])

    def test_future_timestamp_cannot_reset_snapshot_age(self):
        saved = metadata()
        saved["captured_at_unix_ns"] = NOW + 2_000_000_000
        self.assertIn("future", self.validate(saved)["reason_codes"])

    def test_subsecond_clock_adjustment_is_tolerated(self):
        saved = metadata()
        saved["captured_at_unix_ns"] = NOW + 500_000_000
        self.assertTrue(self.validate(saved)["valid"])

    def test_expired_and_malformed_timestamps_reject(self):
        for stamp, code in ((NOW - 301_000_000_000, "age"), (0, "timestamp"), (float("inf"), "timestamp")):
            with self.subTest(stamp=stamp):
                saved = metadata()
                saved["captured_at_unix_ns"] = stamp
                self.assertIn(code, self.validate(saved)["reason_codes"])

    def test_nonfinite_age_limits_and_negative_tolerance_raise(self):
        for age in (float("nan"), float("inf"), -1):
            with self.subTest(age=age), self.assertRaises(ValueError):
                snapshot.validate_snapshot_state(metadata(), state(), now_ns=NOW, max_age=age)
        with self.assertRaises(ValueError):
            self.validate(rect_tolerance=-1)

    def test_zero_hwnd_and_boolean_hwnd_are_rejected(self):
        for hwnd in (0, -1, True):
            with self.subTest(hwnd=hwnd):
                saved = metadata()
                saved["hwnd"] = hwnd
                self.assertIn("hwnd", self.validate(saved)["reason_codes"])

    def test_identity_visibility_geometry_and_scale_are_checked(self):
        for field, value, code in (("pid", 999, "pid"), ("visible", False, "visible"), ("dpi", 144, "dpi")):
            with self.subTest(field=field):
                current = state()
                current[field] = value
                self.assertIn(code, self.validate(current=current)["reason_codes"])
        current = state()
        current["raw_rect"]["left"] += 1
        current["raw_rect"]["right"] += 1
        self.assertIn("rect", self.validate(current=current)["reason_codes"])

    def test_either_frame_changing_rejects_verification(self):
        for frame in ("raw_rect", "dwm_rect"):
            with self.subTest(frame=frame):
                current = state()
                current[frame]["left"] += 1
                current[frame]["right"] += 1
                self.assertIn("rect", self.validate(current=current)["reason_codes"])

    def test_ambiguous_window_frames_allow_capture_verification_but_reject_clicks(self):
        raw = {"left": 2, "top": 12, "right": 118, "bottom": 108, "width": 116, "height": 96}
        for method in ("printwindow", "screen"):
            with self.subTest(method=method):
                saved = metadata(method, raw=raw)
                current = state(raw=raw)
                current["foreground_hwnd"] = 123
                observed = self.validate(saved, current)
                self.assertTrue(observed["valid"])
                self.assertFalse(observed["coordinate_input_supported"])
                rejected = self.validate(saved, current, x=10, y=10)
                self.assertFalse(rejected["valid"])
                self.assertIn("ambiguous_frame", rejected["reason_codes"])

    def test_tolerance_cannot_enable_ambiguous_frame_input(self):
        raw = dict(RECT)
        raw.update(left=9, right=109)
        result = self.validate(metadata(raw=raw), state(raw=raw), rect_tolerance=99, x=10, y=10)
        self.assertIn("ambiguous_frame", result["reason_codes"])

    def test_legacy_metadata_without_either_frame_cannot_authorize_input(self):
        for frame in ("raw_rect", "dwm_rect"):
            with self.subTest(frame=frame):
                saved = metadata()
                saved.pop(frame)
                self.assertIn("frame_metadata", self.validate(saved, x=10, y=10)["reason_codes"])

    def test_capture_method_rectangle_and_origin_are_checked(self):
        saved = metadata()
        saved["capture_origin"]["x"] += 8
        self.assertIn("capture_origin", self.validate(saved)["reason_codes"])
        saved = metadata()
        saved["capture_rect_source"] = "DWM_EXTENDED_FRAME_BOUNDS"
        self.assertIn("capture_rect", self.validate(saved)["reason_codes"])

    def test_out_of_bounds_and_partial_coordinates_reject(self):
        for x, y in ((-1, 0), (0, -1), (100, 0), (0, 80), (0, None), (True, 0)):
            with self.subTest(x=x, y=y):
                self.assertFalse(self.validate(x=x, y=y)["valid"])

    def test_image_dimensions_must_agree_with_window(self):
        saved = metadata()
        saved["image"]["width"] = 101
        self.assertIn("dimensions", self.validate(saved)["reason_codes"])

    def test_dead_window_rejects(self):
        result = snapshot.validate_snapshot_state(metadata(), None, now_ns=NOW, max_age=300)
        self.assertIn("live", result["reason_codes"])


class CaptureRaceTests(unittest.TestCase):
    def test_screen_grab_rechecks_focus_process_geometry_and_dpi(self):
        before = state()
        before["foreground_hwnd"] = 123
        variants = []
        for key, value in (("foreground_hwnd", 999), ("pid", 789), ("dpi", 144), ("visible", False)):
            after = copy.deepcopy(before)
            after[key] = value
            variants.append(after)
        after = copy.deepcopy(before)
        after["dwm_rect"]["left"] += 1
        variants.append(after)
        for after in variants:
            with self.subTest(after=after), patch.object(snapshot, "read_window_state", side_effect=[before, after]), \
                 patch.object(snapshot.ImageGrab, "grab", return_value=Image.new("RGB", (100, 80))):
                with self.assertRaises(RuntimeError):
                    snapshot.capture_screen(123, dict(RECT))

    def test_changed_capture_is_not_saved(self):
        before, after = state(), state()
        after["pid"] = 999
        with tempfile.TemporaryDirectory(prefix="cua capture tests ") as directory:
            output = Path(directory) / "capture.png"
            receipt = Path(directory) / "capture.json"
            args = argparse.Namespace(hwnd=123, output=str(output), metadata=str(receipt), method="printwindow")
            with patch.object(snapshot, "read_window_state", side_effect=[before, after]), \
                 patch.object(snapshot, "capture_printwindow", return_value=(Image.new("RGB", (100, 80)), {"returned": True, "variation": 5.0})):
                with self.assertRaises(RuntimeError):
                    snapshot.capture(args)
            self.assertFalse(output.exists())
            self.assertFalse(receipt.exists())

    def test_each_capture_method_uses_its_own_rectangle_and_dimensions(self):
        raw = {"left": 2, "top": 12, "right": 118, "bottom": 108, "width": 116, "height": 96}
        for method, expected_rect in (("printwindow", raw), ("screen", RECT)):
            with self.subTest(method=method), tempfile.TemporaryDirectory(prefix="cua frame tests ") as directory:
                before = state(raw=raw)
                before["foreground_hwnd"] = 123
                output = Path(directory) / "capture.png"
                receipt = Path(directory) / "capture.json"
                args = argparse.Namespace(hwnd=123, output=str(output), metadata=str(receipt), method=method)
                image = Image.new("RGB", (expected_rect["width"], expected_rect["height"]))
                stdout = io.StringIO()
                with patch.object(snapshot, "read_window_state", side_effect=[before, copy.deepcopy(before)]), \
                     patch.object(snapshot, "capture_printwindow", return_value=(image, {"returned": True, "variation": 5.0})) as print_capture, \
                     patch.object(snapshot, "capture_screen", return_value=image) as screen_capture, redirect_stdout(stdout):
                    self.assertEqual(snapshot.capture(args), 0)
                if method == "printwindow":
                    print_capture.assert_called_once_with(123, raw)
                    screen_capture.assert_not_called()
                else:
                    screen_capture.assert_called_once_with(123, RECT)
                    print_capture.assert_not_called()
                saved = json.loads(receipt.read_text(encoding="utf-8"))
                self.assertEqual(saved["raw_rect"], raw)
                self.assertEqual(saved["dwm_rect"], RECT)
                self.assertEqual(saved["capture_rect"], expected_rect)
                self.assertEqual(saved["capture_origin"], {"x": expected_rect["left"], "y": expected_rect["top"]})
                self.assertEqual((saved["image"]["width"], saved["image"]["height"]), image.size)
                self.assertFalse(saved["coordinate_input_supported"])

    def test_printwindow_failure_never_silently_grabs_desktop_pixels(self):
        with tempfile.TemporaryDirectory(prefix="cua no auto tests ") as directory:
            args = argparse.Namespace(hwnd=123, output=str(Path(directory) / "capture.png"),
                                      metadata=str(Path(directory) / "capture.json"), method="printwindow")
            with patch.object(snapshot, "read_window_state", return_value=state()), \
                 patch.object(snapshot, "capture_printwindow", return_value=(Image.new("RGB", (100, 80)), {"returned": False, "variation": 0.0})), \
                 patch.object(snapshot, "capture_screen") as screen_capture:
                with self.assertRaises(RuntimeError):
                    snapshot.capture(args)
            screen_capture.assert_not_called()

    def test_screen_grab_uses_only_dwm_visible_bounds(self):
        before = state(raw={"left": 2, "top": 12, "right": 118, "bottom": 108, "width": 116, "height": 96})
        before["foreground_hwnd"] = 123
        with patch.object(snapshot, "read_window_state", side_effect=[before, copy.deepcopy(before)]), \
             patch.object(snapshot.ImageGrab, "grab", return_value=Image.new("RGB", (100, 80))) as grab:
            self.assertEqual(snapshot.capture_screen(123, dict(RECT)).size, (100, 80))
        self.assertEqual(grab.call_args.kwargs["bbox"], (10, 20, 110, 100))


class StoredImageTests(unittest.TestCase):
    def run_verify(self, saved, directory):
        receipt = Path(directory) / "snapshot.json"
        receipt.write_text(json.dumps(saved), encoding="utf-8")
        args = argparse.Namespace(metadata=str(receipt), max_age=300, rect_tolerance=0,
                                  expected_hwnd=123, require_foreground=False, x=1, y=1)
        api = type("FakeUser32", (), {"IsWindow": staticmethod(lambda _: True)})()
        stdout = io.StringIO()
        with patch.object(snapshot, "user32", api), patch.object(snapshot, "read_window_state", return_value=state()), \
             patch.object(snapshot.time, "time_ns", return_value=NOW), redirect_stdout(stdout):
            code = snapshot.verify(args)
        return code, json.loads(stdout.getvalue())

    def test_valid_png_is_accepted_and_modified_png_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="cua image tests ") as directory:
            image = Path(directory) / "snapshot.png"
            Image.new("RGB", (100, 80), "red").save(image)
            saved = metadata()
            saved["image"].update(path=str(image), sha256=snapshot.sha256_file(image))
            self.assertEqual(self.run_verify(saved, directory)[0], 0)
            Image.new("RGB", (100, 80), "blue").save(image)
            code, result = self.run_verify(saved, directory)
            self.assertEqual(code, 2)
            self.assertIn("image_hash", result["reason_codes"])
            self.assertFalse(result["coordinate_input_supported"])

    def test_matching_hash_does_not_hide_wrong_png_dimensions(self):
        with tempfile.TemporaryDirectory(prefix="cua dimension tests ") as directory:
            image = Path(directory) / "snapshot.png"
            Image.new("RGB", (101, 80), "red").save(image)
            saved = metadata()
            saved["image"].update(path=str(image), sha256=snapshot.sha256_file(image))
            code, result = self.run_verify(saved, directory)
            self.assertEqual(code, 2)
            self.assertIn("image_dimensions", result["reason_codes"])


class CommandLineTests(unittest.TestCase):
    def test_invalid_cli_values_exit_before_window_access(self):
        cases = [
            ["info", "--hwnd", "0"],
            ["verify", "--metadata", "not-read.json", "--expected-hwnd", "0"],
            ["verify", "--metadata", "not-read.json", "--rect-tolerance", "-1"],
            ["verify", "--metadata", "not-read.json", "--max-age", "NaN"],
            ["verify", "--metadata", "not-read.json", "--max-age", "Infinity"],
            ["capture", "--hwnd", "123", "--output", "not-written.png", "--metadata", "not-written.json", "--method", "auto"],
        ]
        for args in cases:
            with self.subTest(args=args):
                result = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()

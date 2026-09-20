"""Regression tests for platform paths, release version and clipboard failures."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from core.constants import APP_VERSION
from core.paths import user_data_dir, autosave_path, recovery_path
from core.plot_clipboard import copy_png


class ReleaseTests(unittest.TestCase):
    def test_semantic_version(self):
        self.assertRegex(APP_VERSION, r"^\d+\.\d+\.\d+$")

    def test_windows_per_user_folder(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": "/example/local"}, clear=True), patch("sys.platform", "win32"):
            self.assertEqual(user_data_dir(), Path("/example/local/ScientificGraphStudio"))

    def test_macos_per_user_folder(self):
        with patch.dict(os.environ, {}, clear=True), patch("sys.platform", "darwin"), patch("pathlib.Path.home", return_value=Path("/example")):
            self.assertEqual(user_data_dir(), Path("/example/Library/Application Support/ScientificGraphStudio"))

    def test_linux_xdg_folder(self):
        with patch.dict(os.environ, {"XDG_DATA_HOME": "/example/state"}, clear=True), patch("sys.platform", "linux"):
            self.assertEqual(user_data_dir(), Path("/example/state/ScientificGraphStudio"))

    def test_autosave_creates_writable_directory(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"SGS_DATA_DIR": str(Path(tmp) / "state")}):
            self.assertTrue(autosave_path().parent.is_dir())
            self.assertEqual(autosave_path().name, "autosave.gpj")

    def test_frozen_recovery_does_not_load_arbitrary_working_directory(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"SGS_DATA_DIR": tmp}), patch.object(sys, "frozen", True, create=True):
            self.assertEqual(recovery_path(), Path(tmp) / "autosave.gpj")

    def test_unsupported_clipboard_fails_explicitly(self):
        with patch("sys.platform", "linux"):
            with self.assertRaises(RuntimeError):
                copy_png("unused.png")

    def test_mac_path_is_passed_as_argument_not_shell(self):
        with patch("sys.platform", "darwin"), patch("core.plot_clipboard.subprocess.run") as run:
            copy_png("/tmp/a'b.png")
            self.assertEqual(run.call_args.args[0][-1], "/tmp/a'b.png")
            self.assertNotIn("shell", run.call_args.kwargs)

    def test_windows_clipboard_supplies_dib_and_png(self):
        from PIL import Image
        clipboard = MagicMock()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "image.png"
            Image.new("RGBA", (3, 3), (0, 0, 0, 0)).save(path)
            with patch("sys.platform", "win32"), patch.dict(sys.modules, {"win32clipboard": clipboard}):
                copy_png(path)
            self.assertEqual(clipboard.SetClipboardData.call_count, 2)
            dib = clipboard.SetClipboardData.call_args_list[0].args[1]
            self.assertNotEqual(dib[:2], b"BM")
            self.assertTrue(clipboard.SetClipboardData.call_args_list[1].args[1].startswith(b"\x89PNG"))
            clipboard.CloseClipboard.assert_called_once()

    def test_windows_clipboard_closes_after_error(self):
        from PIL import Image
        clipboard = MagicMock()
        clipboard.SetClipboardData.side_effect = RuntimeError("busy")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "image.png"
            Image.new("RGB", (2, 2)).save(path)
            with patch("sys.platform", "win32"), patch.dict(sys.modules, {"win32clipboard": clipboard}):
                with self.assertRaises(RuntimeError):
                    copy_png(path)
            clipboard.CloseClipboard.assert_called_once()


if __name__ == "__main__":
    unittest.main()

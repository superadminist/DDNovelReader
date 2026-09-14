from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from novelreader import paths


class ApplicationPathTests(unittest.TestCase):
    def test_source_run_keeps_legacy_appdata_location(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            appdata = Path(temp) / "appdata"
            with patch.dict(os.environ, {"APPDATA": os.fspath(appdata), paths.DATA_ENV: ""}):
                with patch.object(paths, "is_frozen", return_value=False):
                    self.assertEqual(paths.default_data_dir(), appdata / "DDNovelReader")

    def test_frozen_run_uses_data_beside_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp) / "installed" / "QYReader.exe"
            with patch.dict(os.environ, {paths.DATA_ENV: ""}):
                with patch.object(paths, "is_frozen", return_value=True):
                    with patch.object(paths.sys, "executable", os.fspath(executable)):
                        self.assertEqual(paths.default_data_dir(), (executable.parent / "data").resolve())

    def test_first_frozen_launch_copies_legacy_data_without_deleting_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            appdata = root / "appdata"
            legacy = appdata / "DDNovelReader"
            legacy.mkdir(parents=True)
            (legacy / "library.json").write_text(
                json.dumps({"books": {}, "settings": {"theme": "夜间"}}, ensure_ascii=False),
                encoding="utf-8",
            )
            (legacy / "cache" / "sources").mkdir(parents=True)
            (legacy / "cache" / "sources" / "book.txt").write_text("正文", encoding="utf-8")
            executable = root / "installed" / "QYReader.exe"

            with patch.dict(os.environ, {"APPDATA": os.fspath(appdata), paths.DATA_ENV: ""}):
                with patch.object(paths, "is_frozen", return_value=True):
                    with patch.object(paths.sys, "executable", os.fspath(executable)):
                        target = paths.ensure_data_dir()

            self.assertEqual(target, (executable.parent / "data").resolve())
            self.assertEqual((target / "cache" / "sources" / "book.txt").read_text(encoding="utf-8"), "正文")
            self.assertTrue((legacy / "library.json").is_file())

    def test_existing_install_data_is_never_overwritten_by_legacy_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            appdata = root / "appdata"
            legacy = appdata / "DDNovelReader"
            legacy.mkdir(parents=True)
            (legacy / "library.json").write_text("legacy", encoding="utf-8")
            install = root / "installed"
            target = install / "data"
            target.mkdir(parents=True)
            (target / "library.json").write_text("installed", encoding="utf-8")

            with patch.dict(os.environ, {"APPDATA": os.fspath(appdata), paths.DATA_ENV: ""}):
                with patch.object(paths, "is_frozen", return_value=True):
                    with patch.object(paths.sys, "executable", os.fspath(install / "QYReader.exe")):
                        self.assertEqual(paths.ensure_data_dir(), target.resolve())

            self.assertEqual((target / "library.json").read_text(encoding="utf-8"), "installed")


if __name__ == "__main__":
    unittest.main()

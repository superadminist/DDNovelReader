from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PackagingContractTests(unittest.TestCase):
    def test_spec_packages_qt_frontend_without_legacy_tk_assets(self) -> None:
        spec = (ROOT / "多多朗读.spec").read_text(encoding="utf-8")

        self.assertIn('ROOT / "novelreader" / "main.py"', spec)
        self.assertIn('ROOT / "prototype" / "dist" / "client"', spec)
        self.assertIn('"prototype/dist/client"', spec)
        self.assertIn('"pyttsx3.drivers.sapi5"', spec)
        self.assertIn('"tkinter"', spec)
        self.assertIn('"tkinterdnd2"', spec)
        self.assertNotIn("runtime_hook_tkinter", spec)
        self.assertNotIn("_tkinter.pyd", spec)
        self.assertNotIn("tcl86t.dll", spec)
        self.assertNotIn("tk86t.dll", spec)
        self.assertNotIn("--single-process", spec)
        self.assertIn("upx=False", spec)

    def test_build_script_enforces_toolchain_and_build_order(self) -> None:
        script = (ROOT / "build.bat").read_text(encoding="utf-8")

        node_gate = "Number(process.versions.node.split('.')[0]) >= 20"
        frontend_build = "npm.cmd --prefix prototype run build"
        freeze = '"%PY%" -m PyInstaller --clean --noconfirm "多多朗读.spec"'
        self.assertIn(node_gate, script)
        self.assertLess(script.index(frontend_build), script.index(freeze))
        self.assertIn('set "PATH="', script)
        self.assertIn('set "Path="', script)
        self.assertIn("build-requirements.txt", script)
        self.assertNotIn("--single-process", script)

    def test_build_requirements_pin_pyinstaller(self) -> None:
        requirements = (ROOT / "build-requirements.txt").read_text(encoding="utf-8")

        self.assertEqual(requirements.strip(), "PyInstaller==6.21.0")


if __name__ == "__main__":
    unittest.main()

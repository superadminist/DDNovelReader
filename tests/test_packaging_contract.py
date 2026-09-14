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
        self.assertIn('ONEDIR = "--onedir" in sys.argv', spec)
        self.assertIn('"PySide6.Qt3DRender"', spec)
        self.assertIn('"PySide6.QtQuick3D"', spec)
        self.assertIn("_without_qml_tree", spec)
        self.assertIn('name="多多朗读-快速启动"', spec)
        self.assertIn("COLLECT(", spec)

    def test_build_script_enforces_toolchain_and_build_order(self) -> None:
        script = (ROOT / "build.bat").read_text(encoding="utf-8")

        node_gate = "Number(process.versions.node.split('.')[0]) >= 20"
        frontend_build = "npm.cmd --prefix prototype run build"
        package_build = '"%PY%" scripts\\package_windows.py'
        self.assertIn(node_gate, script)
        self.assertLess(script.index(frontend_build), script.index(package_build))
        self.assertIn("build-requirements.txt", script)
        self.assertNotIn("--single-process", script)

    def test_build_requirements_pin_pyinstaller(self) -> None:
        requirements = (ROOT / "build-requirements.txt").read_text(encoding="utf-8")

        self.assertEqual(requirements.strip(), "PyInstaller==6.21.0")

    def test_installer_supports_path_and_optional_desktop_icon(self) -> None:
        installer = (ROOT / "installer" / "DDNovelReader.iss").read_text(encoding="utf-8")

        self.assertIn("DefaultDirName={localappdata}\\Programs\\DDNovelReader", installer)
        self.assertIn('Name: "desktopicon"', installer)
        self.assertIn("Tasks: desktopicon", installer)
        self.assertIn('Source: "..\\dist\\多多朗读-快速启动\\*"', installer)
        self.assertIn('MessagesFile: "{#SourcePath}\\ChineseSimplified.isl"', installer)
        language = (ROOT / "installer" / "ChineseSimplified.isl").read_text(encoding="utf-8")
        self.assertIn("LanguageID=$0804", language)
        self.assertNotIn("[UninstallDelete]", installer)

    def test_build_script_compiles_installer_after_onedir_package(self) -> None:
        script = (ROOT / "build.bat").read_text(encoding="utf-8")
        package_script = (ROOT / "scripts" / "package_windows.py").read_text(encoding="utf-8")

        self.assertIn("scripts\\package_windows.py", script)
        self.assertIn('SPEC = ROOT / "多多朗读.spec"', package_script)
        self.assertIn('INSTALLER_SCRIPT = ROOT / "installer" / "DDNovelReader.iss"', package_script)
        self.assertLess(package_script.index('"--onedir"'), package_script.index("_run(iscc, INSTALLER_SCRIPT)"))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "多多朗读.spec"
INSTALLER_SCRIPT = ROOT / "installer" / "DDNovelReader.iss"


def _freeze_environment() -> dict[str, str]:
    """Use only the venv/base Python and Windows DLL search locations."""
    environment = {key: value for key, value in os.environ.items() if key.lower() != "path"}
    python_base = Path(sys.base_prefix)
    environment["Path"] = os.pathsep.join(
        [
            os.fspath(Path(sys.executable).parent),
            os.fspath(python_base),
            os.fspath(python_base / "Scripts"),
            os.fspath(Path(os.environ["SystemRoot"]) / "System32"),
            os.environ["SystemRoot"],
        ]
    )
    return environment


def _find_iscc() -> Path:
    discovered = shutil.which("ISCC.exe")
    if discovered:
        return Path(discovered)

    candidates = []
    for variable, suffix in (
        ("ProgramFiles(x86)", Path("Inno Setup 6") / "ISCC.exe"),
        ("ProgramFiles", Path("Inno Setup 6") / "ISCC.exe"),
        ("LOCALAPPDATA", Path("Programs") / "Inno Setup 6" / "ISCC.exe"),
    ):
        base = os.environ.get(variable)
        if base:
            candidates.append(Path(base) / suffix)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SystemExit("Inno Setup 6 not found. Download: https://jrsoftware.org/isdl.php")


def _run(*arguments: str | os.PathLike[str], environment: dict[str, str] | None = None) -> None:
    subprocess.check_call([os.fspath(argument) for argument in arguments], cwd=ROOT, env=environment)


def main() -> int:
    if not SPEC.is_file():
        raise SystemExit(f"PyInstaller spec not found: {SPEC}")
    if not INSTALLER_SCRIPT.is_file():
        raise SystemExit(f"Inno Setup script not found: {INSTALLER_SCRIPT}")

    iscc = _find_iscc()
    freeze_environment = _freeze_environment()
    print("Building fast-start package...", flush=True)
    _run(
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--workpath",
        ROOT / "build" / "onedir",
        SPEC,
        "--",
        "--onedir",
        environment=freeze_environment,
    )
    print("Building one-file compatibility package...", flush=True)
    _run(
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--workpath",
        ROOT / "build" / "onefile",
        SPEC,
        environment=freeze_environment,
    )
    print("Building Windows installer...", flush=True)
    _run(iscc, INSTALLER_SCRIPT)
    print(f"Installer ready: {ROOT / 'dist' / 'installer'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

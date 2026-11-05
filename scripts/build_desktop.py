"""Freeze an installed release wheel, never the editable development checkout."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(output, identity=None):
    import bms_tool

    package = Path(bms_tool.__file__).resolve().parent
    if package.is_relative_to(ROOT / "backend"):
        raise ValueError("Install the reviewed wheel in the build environment first.")
    provenance = json.loads((package / "data/distribution.json").read_text())
    if provenance["source_dirty"]:
        raise ValueError("Release freezing requires committed source provenance.")
    if (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        != provenance["source_commit"]
    ):
        raise ValueError("The installed wheel does not match this build script's commit.")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bms-desktop-build-") as temporary:
        temporary = Path(temporary)
        command = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--noupx",
            "--onedir",
            "--windowed",
            "--name",
            "BMS Studio",
            "--distpath",
            str(output),
            "--workpath",
            str(temporary / "work"),
            "--specpath",
            str(temporary),
            "--collect-data",
            "bms_tool",
            "--collect-submodules",
            "bms_tool",
            "--collect-submodules",
            "bacpypes3",
            "--collect-data",
            "tzdata",
            "--hidden-import",
            "uvicorn.loops.asyncio",
            "--hidden-import",
            "uvicorn.protocols.http.h11_impl",
            "--hidden-import",
            "uvicorn.lifespan.on",
        ]
        # Importing the GUI here makes missing Tcl/Tk a build failure rather than
        # a recipient's first-launch failure. PyInstaller's hook bundles it.
        import tkinter  # noqa: F401

        python_license = Path(sysconfig.get_path("stdlib")) / "LICENSE.txt"
        if not python_license.is_file():
            raise ValueError("The Python interpreter license must accompany the desktop build.")
        command.extend(
            [
                "--add-data",
                str(python_license) + os.pathsep + "licenses/Python",
                "--copy-metadata",
                "pyinstaller",
            ]
        )

        command.extend(["--hidden-import", "tkinter", "--hidden-import", "tkinter.ttk"])
        for line in (ROOT / "requirements/runtime.txt").read_text().splitlines():
            if "==" in line and not line.startswith((" ", "#")):
                name = line.split("==", 1)[0].strip()
                command.extend(["--copy-metadata", name])
        if sys.platform == "darwin":
            command.extend(["--osx-bundle-identifier", "org.bmsstudio.desktop"])
            if identity:
                command.extend(["--codesign-identity", identity])
        command.append(str(ROOT / "scripts/desktop_entry.py"))
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        subprocess.run(command, cwd=temporary, env=env, check=True)
    manifest = {
        "profile": "bms-desktop-build/1",
        "version": bms_tool.__version__,
        "source_commit": provenance["source_commit"],
        "python": platform.python_version(),
        "platform": sys.platform,
        "architecture": platform.machine(),
        "pyinstaller": importlib.metadata.version("pyinstaller"),
        "signature": "Developer ID" if identity and sys.platform == "darwin" else "unsigned/ad-hoc",
        "notarized": False,
    }
    (output / "desktop-build.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--identity", help="macOS Developer ID identity; no private key material")
    args = parser.parse_args()
    print(json.dumps(build(args.output, args.identity), indent=2))


if __name__ == "__main__":
    main()

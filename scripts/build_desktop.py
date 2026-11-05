"""Freeze an installed release wheel, never the editable development checkout."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import plistlib
import re
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
    version = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:b(\d+))?", bms_tool.__version__)
    if not version:
        raise ValueError("The desktop release version must have a supported numeric/beta form.")
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
        elif sys.platform == "win32":
            numbers = tuple(int(value or 0) for value in version.groups())
            version_file = temporary / "windows-version.txt"
            version_file.write_text(
                "VSVersionInfo(ffi=FixedFileInfo(filevers="
                + repr(numbers)
                + ",prodvers="
                + repr(numbers)
                + ",mask=0x3f,flags=0x2,OS=0x40004,fileType=0x1,subtype=0x0,date=(0,0)),kids=[StringFileInfo([StringTable('040904B0',[StringStruct('CompanyName','BMS Studio contributors'),StringStruct('FileDescription','BMS Studio local editor'),StringStruct('ProductName','BMS Studio'),StringStruct('ProductVersion',"
                + repr(bms_tool.__version__)
                + "),StringStruct('FileVersion',"
                + repr(bms_tool.__version__)
                + ")])]),VarFileInfo([VarStruct('Translation',[1033,1200])])])"
            )
            command.extend(["--version-file", str(version_file)])
        command.append(str(ROOT / "scripts/desktop_entry.py"))
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        subprocess.run(command, cwd=temporary, env=env, check=True)
    if sys.platform == "darwin":
        app = output / "BMS Studio.app"
        info = app / "Contents/Info.plist"
        metadata = plistlib.loads(info.read_bytes())
        metadata["CFBundleShortVersionString"] = ".".join(version.groups()[:3])
        metadata["CFBundleVersion"] = bms_tool.__version__
        info.write_bytes(plistlib.dumps(metadata))
        signing = ["codesign", "--force", "--sign", identity or "-"]
        if identity:
            signing.extend(["--options", "runtime", "--timestamp"])
        subprocess.run([*signing, str(app)], check=True)
        subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
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

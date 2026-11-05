"""Wrap a checked desktop payload in a macOS DMG or Windows per-user installer."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def package(payload, output, *, identity=None, notary_profile=None):
    payload, output = Path(payload).resolve(), Path(output).resolve()
    metadata = json.loads((payload / "desktop-build.json").read_text())
    version = metadata["version"]
    output.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        arch = "arm64" if metadata["architecture"] == "arm64" else "x64"
        asset = output / f"BMS-Studio-{version}-macos-{arch}.dmg"
        with tempfile.TemporaryDirectory(prefix="bms-dmg-") as temporary:
            root = Path(temporary)
            shutil.copytree(payload / "BMS Studio.app", root / "BMS Studio.app", symlinks=True)
            (root / "Applications").symlink_to("/Applications")
            (root / "READ-ME.txt").write_text(
                "Drag BMS Studio.app to Applications, then open it.\n"
                "The local launcher opens the web editor and provides Quit/Open logs.\n"
                "No Python or Node.js installation is needed.\n"
                "See the release notes for signature/notarization status.\n"
                "User data remains separate when updating or removing the app.\n"
            )
            subprocess.run(
                [
                    "hdiutil",
                    "create",
                    "-volname",
                    "BMS Studio",
                    "-srcfolder",
                    str(root),
                    "-ov",
                    "-format",
                    "UDZO",
                    str(asset),
                ],
                check=True,
            )
        if identity:
            subprocess.run(
                ["codesign", "--force", "--timestamp", "--sign", identity, str(asset)], check=True
            )
            subprocess.run(["codesign", "--verify", "--strict", str(asset)], check=True)
        if notary_profile:
            command = [
                "xcrun",
                "notarytool",
                "submit",
                str(asset),
                "--keychain-profile",
                notary_profile,
                "--wait",
            ]
            if os.environ.get("BMS_NOTARY_KEYCHAIN"):
                command.extend(["--keychain", os.environ["BMS_NOTARY_KEYCHAIN"]])
            subprocess.run(command, check=True)
            subprocess.run(["xcrun", "stapler", "staple", str(asset)], check=True)
            subprocess.run(["xcrun", "stapler", "validate", str(asset)], check=True)
            metadata["notarized"] = True
    elif sys.platform == "win32":
        compiler = shutil.which("ISCC.exe") or str(
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
            / "Inno Setup 6/ISCC.exe"
        )
        subprocess.run(
            [
                compiler,
                f"/DPayload={payload / 'BMS Studio'}",
                f"/DDestination={output}",
                f"/DAppVersion={version}",
                str(ROOT / "scripts/windows-installer.iss"),
            ],
            check=True,
        )
        asset = output / f"BMS-Studio-{version}-windows-x64-setup.exe"
    else:
        raise ValueError("Native installer wrapping is supported on Windows and macOS.")
    metadata["asset"] = asset.name
    (output / (asset.stem + "-build.json")).write_text(json.dumps(metadata, indent=2) + "\n")
    return asset


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--identity", default=os.environ.get("BMS_MACOS_IDENTITY"))
    parser.add_argument("--notary-profile", default=os.environ.get("BMS_NOTARY_PROFILE"))
    args = parser.parse_args()
    print(
        package(
            args.payload, args.output, identity=args.identity, notary_profile=args.notary_profile
        ).name
    )

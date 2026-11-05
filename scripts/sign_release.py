"""Optional CI signing. Credentials come only from the release environment."""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def run(command):
    # CalledProcessError would include password arguments in its traceback.
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError("Signing command failed; credential-bearing output withheld.")
    return result.stdout


def github_env(name, value):
    if "\n" in value or "\r" in value:
        raise ValueError("Signing configuration must be one line.")
    with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as stream:
        stream.write(name + "=" + value + "\n")


def prepare(record):
    certificate = os.environ.get("MACOS_CERTIFICATE_BASE64")
    if sys.platform != "darwin" or not certificate:
        return
    record.parent.mkdir(parents=True, exist_ok=True)
    keychain = Path(tempfile.gettempdir()) / (
        "bms-signing-" + secrets.token_hex(12) + ".keychain-db"
    )
    password = secrets.token_urlsafe(32)
    original = [
        p.strip().strip('"')
        for p in run(["security", "list-keychains", "-d", "user"]).decode().splitlines()
        if p.strip()
    ]
    record.write_text(json.dumps({"keychain": str(keychain), "original": original}))
    os.chmod(record, 0o600)
    run(["security", "create-keychain", "-p", password, str(keychain)])
    run(["security", "set-keychain-settings", "-lut", "21600", str(keychain)])
    run(["security", "unlock-keychain", "-p", password, str(keychain)])
    with tempfile.TemporaryDirectory(prefix="bms-signing-input-") as temporary:
        pfx = Path(temporary) / "identity.p12"
        pfx.write_bytes(base64.b64decode(certificate, validate=True))
        os.chmod(pfx, 0o600)
        run(
            [
                "security",
                "import",
                str(pfx),
                "-k",
                str(keychain),
                "-P",
                os.environ["MACOS_CERTIFICATE_PASSWORD"],
                "-T",
                "/usr/bin/codesign",
            ]
        )
        run(
            [
                "security",
                "set-key-partition-list",
                "-S",
                "apple-tool:,apple:",
                "-s",
                "-k",
                password,
                str(keychain),
            ]
        )
        run(["security", "list-keychains", "-d", "user", "-s", str(keychain), *original])
        github_env("BMS_MACOS_IDENTITY", os.environ["MACOS_SIGNING_IDENTITY"])
        key = os.environ.get("APPLE_NOTARY_KEY_BASE64")
        if key:
            api_key = Path(temporary) / "notary.p8"
            api_key.write_bytes(base64.b64decode(key, validate=True))
            os.chmod(api_key, 0o600)
            run(
                [
                    "xcrun",
                    "notarytool",
                    "store-credentials",
                    "bms-ci-notary",
                    "--keychain",
                    str(keychain),
                    "--key",
                    str(api_key),
                    "--key-id",
                    os.environ["APPLE_NOTARY_KEY_ID"],
                    "--issuer",
                    os.environ["APPLE_NOTARY_ISSUER"],
                ]
            )
            github_env("BMS_NOTARY_PROFILE", "bms-ci-notary")
            github_env("BMS_NOTARY_KEYCHAIN", str(keychain))


def windows(files):
    certificate = os.environ.get("WINDOWS_CERTIFICATE_BASE64")
    if sys.platform != "win32" or not certificate:
        return False
    tool = shutil.which("signtool.exe")
    if tool is None:
        candidates = sorted(
            (
                Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
                / "Windows Kits/10/bin"
            ).glob("*/x64/signtool.exe")
        )
        if not candidates:
            raise RuntimeError("Windows signing SDK is unavailable.")
        tool = str(candidates[-1])
    with tempfile.TemporaryDirectory(prefix="bms-signing-input-") as temporary:
        pfx = Path(temporary) / "identity.pfx"
        pfx.write_bytes(base64.b64decode(certificate, validate=True))
        for path in files:
            run(
                [
                    tool,
                    "sign",
                    "/f",
                    str(pfx),
                    "/p",
                    os.environ["WINDOWS_CERTIFICATE_PASSWORD"],
                    "/fd",
                    "SHA256",
                    "/tr",
                    "http://timestamp.digicert.com",
                    "/td",
                    "SHA256",
                    str(path),
                ]
            )
            run([tool, "verify", "/pa", "/all", str(path)])
    return True


def cleanup(record):
    if record.exists():
        data = json.loads(record.read_text())
        run(["security", "list-keychains", "-d", "user", "-s", *data["original"]])
        run(["security", "delete-keychain", data["keychain"]])
        record.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "windows", "cleanup"])
    parser.add_argument("--record", type=Path, default=Path("release-output/signing-keychain.json"))
    parser.add_argument("files", nargs="*", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.record)
    elif args.action == "cleanup":
        cleanup(args.record)
    else:
        print(
            "Authenticode verified"
            if windows(args.files)
            else "Windows signing is not configured; beta remains unsigned."
        )

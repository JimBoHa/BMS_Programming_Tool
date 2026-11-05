"""Validate receipts, inventory release assets and emit SHA-256 checksums."""

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


def finalize(directory, *, stable=False):
    directory = Path(directory)
    manifests = list(directory.glob("*-build.json"))
    if len(manifests) != 3:
        raise ValueError("Release requires all three native platform build manifests.")
    platforms = set()
    commits, versions = set(), set()
    for path in manifests:
        record = json.loads(path.read_text())
        platforms.add((record["platform"], record["architecture"]))
        commits.add(record["source_commit"])
        versions.add(record["version"])
        if not (directory / record["asset"]).is_file():
            raise ValueError("A platform's installer asset is missing.")
        if stable and (
            record["signature"] == "unsigned/ad-hoc"
            or (record["platform"] == "darwin" and not record["notarized"])
        ):
            raise ValueError("Stable publication requires signed, notarized native assets.")
    if len(platforms) != 3:
        raise ValueError("The platform manifests are not distinct.")
    if len(commits) != 1 or len(versions) != 1:
        raise ValueError("Platform installers do not share a source commit and version.")
    if len(list(directory.glob("*-audit.json"))) < 5:
        raise ValueError("Source/archive/native payload audit receipts are missing.")
    for path in directory.glob("*-audit.json"):
        result = json.loads(path.read_text())
        if not result.get("complete") or result.get("findings") or result.get("skipped"):
            raise ValueError("A release privacy audit did not pass.")
    if len(list(directory.glob("*-acceptance.json"))) < 3:
        raise ValueError("Native acceptance receipts are missing.")
    accepted = set()
    for path in directory.glob("*-acceptance.json"):
        result = json.loads(path.read_text())
        for key in (
            "bundled_startup",
            "occupied_port",
            "repeated_launch",
            "ui_and_metadata",
            "data_survives_restart",
            "installer_running_guard",
            "authenticated_lan_startup",
            "installer_install",
            "installer_update",
            "app_only_removal",
            "user_data_preserved",
            "installed_payload_audit",
        ):
            if result.get(key) != "passed":
                raise ValueError("A required installer acceptance check did not pass.")
        if (
            result.get("first_start_field_interfaces") != "closed"
            or result.get("owned_commands") != 0
        ):
            raise ValueError("Installer startup did not retain closed field interfaces.")
        accepted.add((result["platform"], result["architecture"]))
    if accepted != platforms:
        raise ValueError("Acceptance receipts do not cover the built platforms.")
    if not list(directory.glob("*.whl")) or not list(directory.glob("*documentation.zip")):
        raise ValueError("Wheel or illustrated documentation is missing.")
    for wheel in directory.glob("*.whl"):
        with zipfile.ZipFile(wheel) as archive:
            provenance = json.loads(archive.read("bms_tool/data/distribution.json"))
            if provenance["source_dirty"] or provenance["source_commit"] not in commits:
                raise ValueError("Wheel source provenance does not match the installers.")
    sums = []
    for path in sorted(directory.iterdir()):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            sums.append(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name)
    (directory / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n")
    return [json.loads(path.read_text()) for path in manifests]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--stable", action="store_true")
    parser.add_argument("--notes", type=Path)
    parser.add_argument("--notes-output", type=Path)
    args = parser.parse_args()
    records = finalize(args.directory, stable=args.stable)
    if args.notes:
        if not args.notes_output:
            parser.error("--notes-output is required with --notes")
        text = (
            args.notes.read_text()
            + "\n\n## Published installer status\n\n| Asset | Signature | Notarized | Installer checks |\n| --- | --- | --- | --- |\n"
        )
        for record in sorted(records, key=lambda r: r["asset"]):
            text += f"| `{record['asset']}` | {record['signature']} | {'Yes' if record['notarized'] else 'No'} | Passed |\n"
        args.notes_output.write_text(text)

"""Scan release payloads, including ZIP members and frozen Python archives.

Rules stay outside the repository. Reports contain categories and locations only.
Scan the installed/staged payload before wrapping it in a DMG or setup executable.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import zipfile
from pathlib import Path

if __package__:
    from .privacy_audit import rules, safe_location, scan_bytes
else:
    from privacy_audit import rules, safe_location, scan_bytes

HOME = re.compile(rb"(?:/Users/|/home/|[A-Za-z]:[\\/]Users[\\/])[A-Za-z0-9_.@-]+[\\/]")
# Exact third-party payload/source witnesses. These are upstream compiler paths
# or distributed examples, not this app's build-machine path. Private-rule
# matches are never exempted. UI assets and frozen app modules have no exemption.
UPSTREAM_HOME = (
    (
        re.compile(r"!PYZ\.pyz!_sysconfigdata__darwin_darwin$"),
        (b"/Users/runner/work/", b"/Users/runner/hostedtoolcache/"),
    ),
    (
        re.compile(
            r"(?:^|/)(?:pydantic_core/[^/]+\.(?:so|pyd)|pydantic_core-[^/]+\.dist-info/sboms/pydantic-core\.cyclonedx\.json)$"
        ),
        (
            b"/Users/runner/.cargo/registry/src/",
            b"/Users/runner/work/pydantic/pydantic/",
            b"/home/runner/.cargo/registry/src/",
            b"/home/runner/work/pydantic/pydantic/",
            b"C:\\Users\\runneradmin\\.cargo\\registry\\src\\",
        ),
    ),
    (
        re.compile(r"(?:^|/)tomli/[^/]+\.(?:so|pyd)$"),
        (b"/Users/runner/work/tomli/tomli/", b"/home/runner/work/tomli/tomli/"),
    ),
    (re.compile(r"(?:^|/)fastapi-[^/]+\.dist-info/METADATA$"), (b"/home/user/",)),
    (re.compile(r"(?:^|/)_tk_data/fileicon\.tcl$"), (b"/home/jimmac/ximian_art/icons/nautilus/",)),
)
MAX_MEMBER = 256 * 1024 * 1024
MAX_TOTAL = 2 * 1024 * 1024 * 1024
MAX_FILES = 50000


def audit(paths, private):
    findings, skipped, upstream, seen, total, scanned = [], [], [], set(), 0, 0

    def inspect(data, location, depth=0):
        nonlocal total, scanned
        total += len(data)
        scanned += 1
        if depth > 8 or total > MAX_TOTAL or scanned > MAX_FILES:
            raise ValueError("Release audit exceeded its bounded decode profile.")
        location = safe_location(location, private)
        if HOME.search(location.encode()):
            location = "<redacted-home-location>"
        findings.extend({"location": location, **row} for row in scan_bytes(data, private))
        for match in HOME.finditer(data):
            row = {
                "location": location,
                "line": data.count(b"\n", 0, match.start()) + 1,
                "kind": "absolute-home-directory",
            }
            if any(
                pattern.search(location)
                and any(data.startswith(prefix, match.start()) for prefix in prefixes)
                for pattern, prefixes in UPSTREAM_HOME
            ):
                upstream.append({**row, "kind": "reviewed-upstream-reference"})
            else:
                findings.append(row)
        if location.endswith(".map"):
            findings.append({"location": location, "line": 1, "kind": "production-source-map"})
        if data.startswith(b"PK\x03\x04"):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for member in archive.infolist():
                    if member.is_dir():
                        continue
                    if member.file_size > MAX_MEMBER:
                        raise ValueError("Archive member exceeds the audit limit.")
                    inspect(member.filename.encode(), location + "!<member-name>", depth + 1)
                    inspect(archive.read(member), location + "!" + member.filename, depth + 1)

    for requested in paths:
        requested = Path(requested).resolve()
        if not requested.exists():
            raise FileNotFoundError("A requested release payload is missing.")
        files = sorted(requested.rglob("*")) if requested.is_dir() else [requested]
        for path in files:
            if path.is_symlink():
                # Frozen macOS bundles use internal Framework/Resources links.
                if not path.resolve().is_relative_to(requested):
                    skipped.append({"location": path.name, "reason": "external-symlink"})
                continue
            if not path.is_file() or path.resolve() in seen:
                continue
            seen.add(path.resolve())
            location = path.relative_to(requested).as_posix() if requested.is_dir() else path.name
            inspect(location.encode(), "<payload-name>")
            if path.stat().st_size > MAX_MEMBER:
                skipped.append({"location": location, "reason": "oversized"})
                continue
            data = path.read_bytes()
            inspect(data, location)
            # Frozen modules are compressed inside the executable. A raw string
            # scan alone would miss constants and source filenames in the PYZ.
            if b"MEI\014\013\012\013\016" not in data:
                continue
            try:
                from PyInstaller.archive.readers import CArchiveReader
            except ImportError as exc:
                raise ValueError("PyInstaller is required to inspect frozen payloads.") from exc
            archive = CArchiveReader(str(path))
            for name, record in archive.toc.items():
                if record[-1] == "z":
                    embedded = archive.open_embedded_archive(name)
                    for module in embedded.toc:
                        raw = embedded.extract(module, raw=True)
                        if raw is not None:
                            inspect(raw, location + "!" + name + "!" + module)
                else:
                    raw = archive.extract(name)
                    if raw:
                        inspect(raw, location + "!" + name)
    return {
        "profile": "bms-release-payload-audit/1",
        "complete": not skipped,
        "objects_scanned": scanned,
        "decoded_bytes": total,
        "findings": findings,
        "skipped": skipped,
        "reviewed_upstream_references": upstream,
        "scope": "payload files, decoded ZIP members and frozen Python archives",
        "exclusions": ["hosted history/metadata", "DMG/setup container decoding", "OCR of images"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--private-rules", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        private = rules(json.loads(args.private_rules.read_text()) if args.private_rules else {})
        result = audit(args.paths, private)
    except Exception as exc:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {
                    "profile": "bms-release-payload-audit/1",
                    "complete": False,
                    "error_type": type(exc).__name__,
                }
            )
            + "\n"
        )
        parser.exit(2, "Release audit incomplete; values and decoder output withheld.\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    if result["findings"] or result["skipped"]:
        print(
            json.dumps(
                {
                    "complete": result["complete"],
                    "findings": result["findings"][:20],
                    "skipped": result["skipped"][:20],
                }
            )
        )
    raise SystemExit(int(bool(result["findings"] or result["skipped"])))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build an installable wheel with the reviewed browser assets and public metadata.

Run npm run build in web first. Only Git-tracked Python package source, the three
public JSON documents and the built UI are copied; user state/manuals are excluded.
The resulting wheel still requires the project's declared Python dependencies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DOCS = ("capabilities.json", "references.json", "requirements.json")


def build(destination, *, allow_dirty=False):
    destination = Path(destination).resolve()
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    if status.strip() and not allow_dirty:
        raise ValueError(
            "Commit reviewed source first, or use --allow-dirty for a development build."
        )
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dist = ROOT / "web" / "dist"
    if not (dist / "index.html").is_file():
        raise ValueError("Build web/ with npm run build before packaging.")
    paths = (
        subprocess.check_output(["git", "ls-files", "-z", "--", "backend/bms_tool"], cwd=ROOT)
        .decode()
        .split("\0")
    )
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bms-wheel-source-") as temporary:
        staged = Path(temporary)
        for name in paths:
            if not name:
                continue
            source = ROOT / name
            if source.is_symlink() or not source.is_file():
                raise ValueError("Tracked package source must be regular files: " + name)
            target = staged / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        for name in ("pyproject.toml", "README.md", "LICENSE"):
            source = ROOT / name
            if source.is_file():
                shutil.copy2(source, staged / name)
        package = staged / "backend" / "bms_tool"
        docs = package / "data" / "app_docs"
        docs.mkdir(parents=True)
        for name in PUBLIC_DOCS:
            source = ROOT / "docs" / name
            json.loads(source.read_text(encoding="utf-8"))
            shutil.copy2(source, docs / name)
        manifest = {
            "profile": "bms-studio-distribution/1",
            "source_commit": commit,
            "source_dirty": bool(status.strip()),
            "ui_files": {},
        }
        for source in sorted(dist.rglob("*")):
            if source.is_symlink():
                raise ValueError("Built UI must not contain symlinks.")
            if not source.is_file():
                continue
            relative = source.relative_to(dist)
            # Vite emits the entry file and flat assets. Do not bundle arbitrary
            # files accidentally copied into the build directory.
            if relative != Path("index.html") and not (
                len(relative.parts) == 2
                and relative.parts[0] == "assets"
                and relative.suffix in {".js", ".css", ".map", ".woff", ".woff2", ".svg", ".png"}
            ):
                raise ValueError("Unexpected built UI file: " + str(relative))
            target = package / "web_assets" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            manifest["ui_files"][relative.as_posix()] = hashlib.sha256(
                source.read_bytes()
            ).hexdigest()
        (package / "data" / "distribution.json").write_text(json.dumps(manifest, indent=2) + "\n")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--wheel-dir",
                str(destination),
                str(staged),
            ],
            check=True,
        )
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()
    manifest = build(args.output, allow_dirty=args.allow_dirty)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()

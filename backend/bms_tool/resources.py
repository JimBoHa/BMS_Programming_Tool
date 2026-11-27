"""Locate source-checkout or installed-package resources without writable code paths."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
SOURCE = PACKAGE.parents[1]
DOCUMENTS = {"capabilities.json", "references.json", "requirements.json"}


def source_checkout():
    return PACKAGE.parent == SOURCE / "backend" and (SOURCE / "pyproject.toml").is_file()


def toolchain_roots():
    """Prefer tools beside this checkout, then tools beside its Git main checkout."""
    yield SOURCE.parent
    marker = SOURCE / ".git"
    if not source_checkout() or not marker.is_file():
        return
    try:
        prefix, path = marker.read_text(encoding="utf-8").strip().split(": ", 1)
        if prefix != "gitdir":
            return
        admin = (SOURCE / path).resolve(strict=True)
        common = (admin / (admin / "commondir").read_text(encoding="utf-8").strip()).resolve(
            strict=True
        )
        backlink = (admin / (admin / "gitdir").read_text(encoding="utf-8").strip()).resolve(
            strict=True
        )
        if (
            common.name == ".git"
            and admin.parent == common / "worktrees"
            and backlink == marker.resolve()
            and common.parent.parent != SOURCE.parent
        ):
            yield common.parent.parent
    except (OSError, ValueError, RuntimeError):
        return


def toolchain_path(variable, relative):
    override = os.environ.get(variable)
    if override is not None:
        return Path(override)
    return next(
        (root / relative for root in toolchain_roots() if (root / relative).exists()),
        SOURCE.parent / relative,
    )


def public_document(name):
    if name not in DOCUMENTS:
        raise ValueError("Unknown bundled application document.")
    paths = [PACKAGE / "data" / "app_docs" / name]
    if source_checkout():
        paths.insert(0, SOURCE / "docs" / name)
    for path in paths:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    if name == "references.json":
        return []
    raise ValueError("Application metadata is missing; rebuild or reinstall the distribution.")


def web_directory():
    paths = [PACKAGE / "web_assets"]
    if source_checkout():
        paths.insert(0, SOURCE / "web" / "dist")
    for path in paths:
        if (path / "index.html").is_file():
            return path
    return None


def state_directory():
    explicit = os.environ.get("BMS_STUDIO_DATA")
    if explicit:
        return Path(explicit)
    if source_checkout():
        return SOURCE / ".state"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "BMS Studio"
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "BMS Studio"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "bms-studio"

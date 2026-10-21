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

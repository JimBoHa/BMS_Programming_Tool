"""Explicit reanalysis of integrity-checked saved bytes into a separate evidence record."""

import copy
import hashlib
import json
import os
import stat

from pydantic import Field

from .models import StrictModel

PROFILE = "saved-hardware-archive-reanalysis/1"


class ArchiveReanalysisRequest(StrictModel):
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$", strict=True)


def reanalyze_archive(workbench, key, source_sha256):
    options = ArchiveReanalysisRequest(source_sha256=source_sha256)
    parent = workbench.archive(key)
    source = parent.get("source")
    if not isinstance(source, dict) or source.get("sha256") != options.source_sha256:
        raise ValueError("Saved archive source identity changed; open its evidence again.")
    # The archive getter validates the identifier and saved evidence wrapper.
    path = workbench.directory / ("source-" + key + ".bin")
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or not 1 <= before.st_size <= 2 * 1024 * 1024:
            raise ValueError("Saved archive source must be a bounded regular file.")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            current = os.fstat(stream.fileno())
            if (current.st_dev, current.st_ino, current.st_size) != (
                before.st_dev,
                before.st_ino,
                before.st_size,
            ):
                raise ValueError("Saved archive source changed while opening; inspect it again.")
            data = stream.read(2 * 1024 * 1024 + 1)
    except OSError:
        raise ValueError(
            "Saved archive source is unavailable; restore its original bytes."
        ) from None
    if (
        len(data) != before.st_size
        or type(source.get("bytes")) is not int
        or source["bytes"] != len(data)
        or hashlib.sha256(data).hexdigest() != options.source_sha256
    ):
        raise ValueError("Saved archive source failed its recorded size or integrity check.")
    encoded = json.dumps(
        parent, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False
    ).encode()
    return workbench.import_archive(
        data,
        source.get("filename", "Archive.moi"),
        origin={
            "kind": "saved-archive-reanalysis",
            "profile": PROFILE,
            "parent_archive_id": key,
            "parent_source_sha256": options.source_sha256,
            "parent_evidence_sha256": hashlib.sha256(encoded).hexdigest(),
            "parent_origin": copy.deepcopy(parent.get("origin")),
            "controller_queries": False,
            "controller_writes": False,
            "current_controller_identity_verified": False,
        },
    )

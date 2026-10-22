"""Opt-in exact JSON source transport for portable Program documents only.

Storage/canonical hashes and ordinary API/native evidence responses are unchanged.
The envelope authenticates no sender; it binds exact source bytes and declared
identity so an editor projection cannot silently substitute a different source.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Annotated

from fastapi import Header
from fastapi.encoders import jsonable_encoder

FORMAT = "bms.program-source/1"
RESPONSE_FORMAT = "bms.program-source-response/1"
MAX_BYTES, MAX_ITEMS, MAX_DEPTH = 8 * 1024 * 1024, 200_000, 64
SourceMode = Annotated[bool, Header(alias="X-Studio-Program-Source")]


def _bounded(value, depth=0, remaining=None):
    remaining = [MAX_ITEMS] if remaining is None else remaining
    remaining[0] -= 1
    if remaining[0] < 0 or depth > MAX_DEPTH:
        raise ValueError("Program source exceeds its item/depth profile.")
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeError as exc:
            raise ValueError("Program strings require valid Unicode.") from exc
    if isinstance(value, dict):
        for key in value:
            try:
                key.encode("utf-8")
            except UnicodeError as exc:
                raise ValueError("Program keys require valid Unicode.") from exc
    if isinstance(value, (dict, list)):
        for child in value.values() if isinstance(value, dict) else value:
            _bounded(child, depth + 1, remaining)


def strict_source_json(source):
    if not isinstance(source, str):
        raise ValueError("Program source must be JSON text.")
    try:
        raw = source.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError("Program source requires valid UTF-8.") from exc
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("Program source requires 1 byte through 8 MiB.")

    def unique(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key in Program source.")
            result[key] = item
        return result

    def constant(value):
        raise ValueError("Nonfinite JSON constants are not Program source numbers.")

    def integer(token):
        if len(token) > 4096:
            raise ValueError("Program integer tokens exceed 4096 characters.")
        return int(token)

    def floating(token):
        if len(token) > 4096:
            raise ValueError("Program float tokens exceed 4096 characters.")
        return float(token)

    try:
        value = json.loads(
            source,
            object_pairs_hook=unique,
            parse_constant=constant,
            parse_int=integer,
            parse_float=floating,
        )
        _bounded(value)
        json.dumps(value, allow_nan=False)
    except (RecursionError, OverflowError) as exc:
        raise ValueError("Program source exceeds its finite JSON profile.") from exc
    return value


def unwrap_program_source(value):
    if not isinstance(value, dict) or value.get("format") != FORMAT:
        return value
    if set(value) != {"format", "source_json", "source_sha256", "program_id", "revision_text"}:
        raise ValueError("Program source envelope fields do not match its versioned profile.")
    source = value["source_json"]
    document = strict_source_json(source)
    if hashlib.sha256(source.encode()).hexdigest() != value["source_sha256"]:
        raise ValueError("Program source envelope byte hash mismatch.")
    if not isinstance(document, dict) or document.get("format") == FORMAT:
        raise ValueError("Program source envelope requires one ordinary Program object.")
    revision = document.get("revision", 0)
    if (
        type(revision) is not int
        or not isinstance(value["revision_text"], str)
        or not re.fullmatch(r"0|[1-9][0-9]*", value["revision_text"])
        or str(revision) != value["revision_text"]
        or document.get("id", "untitled") != value["program_id"]
    ):
        raise ValueError("Program source envelope identity/revision binding mismatch.")
    return document


def source_response(value, enabled=False, *, kind="programs"):
    if not enabled:
        return value
    from .models import Program

    document = jsonable_encoder(value)
    _bounded(document)
    source = json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if len(source.encode()) > MAX_BYTES:
        raise ValueError("Program source response exceeds its 8 MiB profile.")
    descriptors = []

    def visit(item, path):
        if isinstance(item, dict) and all(
            key in item for key in ("schema_version", "id", "nodes", "edges", "target")
        ):
            program = Program.model_validate(item)
            descriptors.append(
                {
                    "path": path,
                    "program_id": program.id,
                    "revision_text": str(program.revision),
                    "canonical_sha256": program.digest(),
                    "canonical_format": "canonical-json/1",
                }
            )
            # Metadata is opaque source, including embedded macro programs. It
            # must never be mistaken for a projected, independently edited root.
            return
        if isinstance(item, dict):
            for key, child in item.items():
                visit(child, [*path, key])
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, [*path, index])

    if kind == "programs":
        visit(document, [])
    elif kind != "blocks":
        raise ValueError("Unknown Program source response kind.")
    return {
        "format": RESPONSE_FORMAT,
        "kind": kind,
        "source_json": source,
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "programs": descriptors,
        "limits": {"bytes": MAX_BYTES, "items": MAX_ITEMS, "depth": MAX_DEPTH},
    }

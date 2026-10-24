"""Versioned numeric-literal generators; independent of canonical Program hashes."""

from __future__ import annotations

import hashlib
import json

from .models import Program

LEGACY = "studio-literals/1"
CURRENT = "studio-literals/2"
_RULES = {
    LEGACY: {
        "id": LEGACY,
        "integer_text": "Python format(value, '.15g')",
        "float_text": "Python format(value, '.15g')",
        "mantissa": "IEC fractional part required, including exponent notation",
        "scope": "Legacy source regeneration; archived integer coercion is not executable admission",
    },
    CURRENT: {
        "id": CURRENT,
        "integer_text": "Original decimal integer text after exact binary64 admission",
        "float_text": "Python repr(float): roundtrip finite binary64 text, including signed zero",
        "mantissa": "IEC fractional part required, including exponent notation",
        "scope": "Literal text before declared native binary32 conversion; arithmetic and target rounding remain explicit",
    },
}


def source_profile(identifier=CURRENT):
    if type(identifier) is not str or identifier not in _RULES:
        raise ValueError("Unknown numeric source-generator profile.")
    raw = json.dumps(_RULES[identifier], sort_keys=True, separators=(",", ":")).encode()
    return {"id": identifier, "rules_sha256": hashlib.sha256(raw).hexdigest()}


def verify_source_profile(value, *, expected=CURRENT):
    if type(value) is not dict or set(value) != {"id", "rules_sha256"}:
        raise ValueError("Numeric source-generator profile requires an exact ID and rules digest.")
    if value != source_profile(expected):
        raise ValueError("Unknown or conflicting numeric source-generator profile/rules digest.")
    return expected


def source_document(program):
    return json.dumps(
        {"source_generator": source_profile(), "program": program.model_dump()},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def read_profile_json(raw, *, limit):
    if len(raw) > limit:
        raise ValueError("Numeric source-profile document exceeds its byte bound.")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate source document field.")
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("Source document requires finite JSON values.")

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    except (RecursionError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Source document must contain bounded valid JSON.") from exc


def read_source_document(raw):
    doc = read_profile_json(raw, limit=8 * 1024 * 1024)
    if type(doc) is not dict or set(doc) != {"source_generator", "program"}:
        raise ValueError("Invalid versioned source document fields.")
    verify_source_profile(doc["source_generator"])
    return Program.model_validate(doc["program"])

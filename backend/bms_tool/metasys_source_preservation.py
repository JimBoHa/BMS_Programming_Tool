"""Check explicit source-change manifests against supplemental configuration captures.

This module has no network or database access. Imported captures are untrusted
supplemental evidence, not native backups, authenticated observations or Apply
authority. Only the source Value of an explicitly identified point is allowed to
change; neither a point's local identifier nor its item reference is rewritten.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from datetime import UTC, datetime
from uuid import UUID

PROFILE = "metasys-source-preservation/1"
SECTIONS = (
    "items",
    "properties",
    "incoming_item_references",
    "incoming_text_references",
    "historians",
    "historian_slices",
    "reporting",
)
MAX_POINTS = 128
MAX_ROWS = 100000
MAX_BYTES = 32 * 1024 * 1024
MANIFEST_KEYS = (
    "item_id",
    "guid",
    "metasys_object",
    "path",
    "name",
    "source_type",
    "old_source_instance",
    "proposed_source_instance",
)
BOUNDARY = (
    "Supplemental imported-record comparison only. Does not authenticate an engine, "
    "qualify a write method, establish a complete native backup, verify current values, "
    "or prove preservation of historian samples or records absent from the captures. "
    "A matching report grants no permission or authority to Apply."
)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def guid_key(value):
    try:
        return str(UUID(value)) if type(value) is str else None
    except ValueError:
        return None


def object_key(value):
    if type(value) is not str:
        return None
    parts = value.split(".")
    if len(parts) == 2 and all(part.isascii() and part.isdecimal() for part in parts):
        return tuple(map(int, parts))
    return None


def number(value, label, *, minimum=0, maximum=4194302):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an integer in {minimum}..{maximum}.")
    return value


def source_number(value):
    # SQL configuration exports commonly store numeric property values as text.
    if type(value) is str and value.isascii() and value.isdecimal():
        value = int(value)
    return number(value, "Captured source instance")


def snapshot(value):
    if type(value) is not dict or not isinstance(value.get("captured_utc"), str):
        raise ValueError("A capture with an explicit captured_utc is required.")
    try:
        instant = datetime.fromisoformat(value["captured_utc"])
        if instant.tzinfo is None:
            raise ValueError("Missing timezone.")
    except ValueError as exc:
        raise ValueError("Capture time must include its timezone.") from exc
    for section in SECTIONS:
        rows = value.get(section)
        if type(rows) is not list or len(rows) > MAX_ROWS:
            raise ValueError(f"Capture section {section} is missing or exceeds its row limit.")
        if any(type(row) is not dict for row in rows):
            raise ValueError(f"Capture section {section} must contain records.")
    if not value["items"] or not value["properties"]:
        raise ValueError("An empty item/property capture cannot qualify a manifest.")
    items = {}
    for item in value["items"]:
        key = number(item.get("itemID"), "Item ID", minimum=1, maximum=2147483647)
        if key in items:
            raise ValueError("Duplicate item ID in capture.")
        items[key] = item
    # Retain cardinality: duplicate Value rows must never be silently overwritten.
    properties = {}
    for row in value["properties"]:
        key = (row.get("ItemID"), row.get("AttribID"))
        if type(key[0]) is not int or type(key[1]) is not int or key[0] not in items:
            raise ValueError("Captured property has an invalid or absent owning item.")
        properties.setdefault(key, []).append(row)
    return items, properties


def source_row(properties, item_id):
    rows = properties.get((item_id, 32589), [])
    if len(rows) != 1:
        raise ValueError("Each changed point needs exactly one captured source row.")
    row = rows[0]
    if (
        type(row.get("ValueOrder")) is not int
        or row["ValueOrder"] != 1
        or "ParentValueOrder" not in row
        or row.get("ParentValueOrder") is not None
    ):
        raise ValueError("An indexed/nested source row is outside this profile.")
    source_number(row.get("Value"))
    return row


def manifest(value, before):
    if type(value) is not list or not 1 <= len(value) <= MAX_POINTS:
        raise ValueError(f"Use an explicit manifest of 1..{MAX_POINTS} points.")
    items, properties = snapshot(before)
    result, identifiers, guids, objects, paths = [], set(), set(), set(), set()
    for entry in value:
        if type(entry) is not dict or any(key not in entry for key in MANIFEST_KEYS):
            raise ValueError("A manifest point is missing its explicit identity/source fields.")
        change = {key: entry[key] for key in MANIFEST_KEYS}
        key = number(change["item_id"], "Manifest item ID", minimum=1, maximum=2147483647)
        item = items.get(key)
        if item is None:
            raise ValueError("Manifest point is absent from the original capture.")
        if type(change["guid"]) is not str or type(item.get("GUID")) is not str:
            raise ValueError("Manifest/capture point GUID is missing.")
        try:
            guid = str(UUID(change["guid"]))
            if not UUID(guid).int or UUID(item["GUID"]) != UUID(guid):
                raise ValueError("Different GUID.")
        except ValueError as exc:
            raise ValueError("Manifest GUID does not match the original point.") from exc
        for field, captured in [
            ("metasys_object", "ObjectId"),
            ("path", "PartialReference"),
            ("name", "UserName"),
        ]:
            if (
                type(change[field]) is not str
                or not change[field]
                or len(change[field]) > 2000
                or change[field] != item.get(captured)
            ):
                raise ValueError(f"Manifest {field} does not match the original point.")
        kind = number(change["source_type"], "Source type", maximum=1023)
        if kind not in (0, 5):
            raise ValueError("Only explicit mapped analog inputs and binary values are admitted.")
        local_key = object_key(change["metasys_object"])
        if local_key is None or local_key[0] != kind or not 0 <= local_key[1] <= 4194302:
            raise ValueError("Local object and declared source type do not agree.")
        if key in identifiers or guid in guids or local_key in objects or change["path"] in paths:
            raise ValueError("Manifest has duplicate or ambiguous point identities.")
        # Another captured record sharing an identity is also ambiguous, even if
        # only one of the records was selected in the proposed manifest.
        for other_key, other in items.items():
            if other_key != key and (
                guid_key(other.get("GUID")) == guid
                or object_key(other.get("ObjectId")) == local_key
                or other.get("PartialReference") == change["path"]
            ):
                raise ValueError("Captured point identity is ambiguous.")
        old = number(change["old_source_instance"], "Expected old source")
        new = number(change["proposed_source_instance"], "Proposed source")
        if old == new:
            raise ValueError("A source change must propose a different instance.")
        if source_number(source_row(properties, key)["Value"]) != old:
            raise ValueError("Expected old source differs from the original capture.")
        identifiers.add(key)
        guids.add(guid)
        objects.add(local_key)
        paths.add(change["path"])
        result.append({**change, "guid": guid})
    return result


def load_capture(path):
    """Bound file reads and reject ambiguous or non-JSON numeric input."""

    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("Duplicate JSON object key.")
            result[key] = value
        return result

    def constant(_value):
        raise ValueError("Non-finite JSON values are not admitted.")

    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Input exceeds the 32 MiB evidence-file budget.")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def write_review(path, report):
    """Private new file only; never replace an original capture or prior report."""
    raw = (json.dumps(report, indent=2, allow_nan=False) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)


def review_sources(proposed, before, after=None):
    """Produce local evidence; never execute an edit or issue an Apply token."""
    changes = manifest(proposed, before)
    result = {
        "profile": PROFILE,
        "reviewed_at": datetime.now(UTC).isoformat(),
        "boundary": BOUNDARY,
        "network_access": False,
        "configuration_writes": 0,
        "apply_available": False,
        "native_backup_verified": False,
        "manifest_sha256": digest(changes),
        "before_sha256": digest(before),
        "point_count": len(changes),
        "captured_counts": {s: len(before[s]) for s in SECTIONS},
        "original_source_preconditions_match": True,
        "changes": changes,
        "after_checked": after is not None,
        "captured_records_match": None,
        "all_expected_sources_observed_in_after_capture": None,
    }
    if after is None:
        return result
    _, after_properties = snapshot(after)
    if datetime.fromisoformat(after["captured_utc"]) < datetime.fromisoformat(
        before["captured_utc"]
    ):
        raise ValueError("After capture predates the original capture.")
    result["after_sha256"] = digest(after)
    by_id = {c["item_id"]: c for c in changes}
    observed = []
    for change in changes:
        try:
            actual = source_number(source_row(after_properties, change["item_id"])["Value"])
        except ValueError:
            actual = None
        observed.append(
            {
                "item_id": change["item_id"],
                "source": actual,
                "matches_expected": actual == change["proposed_source_instance"],
            }
        )
    differences = []
    for section in SECTIONS:
        original = before[section]
        expected = original
        actual = after[section]
        if section == "properties":
            expected, actual = [], []
            for rows, output, replacing in [
                (original, expected, True),
                (after[section], actual, False),
            ]:
                for row in rows:
                    clean = dict(row)
                    change = by_id.get(row["ItemID"])
                    if change is not None and row["AttribID"] == 32589:
                        # Source Value bookkeeping is observed and listed below;
                        # identity, type, owner, order and every other field remain protected.
                        clean.pop("EventTimeStamp", None)
                        clean.pop("ValueState", None)
                        clean["Value"] = (
                            change["proposed_source_instance"]
                            if replacing
                            else source_number(row["Value"])
                        )
                    output.append(clean)
        old_counts = Counter(canonical(row) for row in expected)
        new_counts = Counter(canonical(row) for row in actual)
        if old_counts != new_counts:
            differences.append(
                {
                    "section": section,
                    "missing_or_changed_rows": sum((old_counts - new_counts).values()),
                    "added_or_changed_rows": sum((new_counts - old_counts).values()),
                }
            )
    _, original_properties = snapshot(before)
    bookkeeping = []
    for change in changes:
        old_row = source_row(original_properties, change["item_id"])
        rows = after_properties.get((change["item_id"], 32589), [])
        if len(rows) == 1:
            for key in ["EventTimeStamp", "ValueState"]:
                if old_row.get(key) != rows[0].get(key):
                    bookkeeping.append(
                        {
                            "item_id": change["item_id"],
                            "field": key,
                            "before": old_row.get(key),
                            "after": rows[0].get(key),
                        }
                    )
    result.update(
        after_sources=observed,
        captured_record_differences=differences,
        source_bookkeeping_differences=bookkeeping,
        all_expected_sources_observed_in_after_capture=all(r["matches_expected"] for r in observed),
        captured_records_match=not differences,
    )
    return result

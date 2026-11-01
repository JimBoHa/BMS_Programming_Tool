"""Literal CAF/native archive identity evidence; never a compiler compatibility grant."""

import re
from collections import Counter

from pydantic import Field

from .caf import Q
from .caf_instance import CafInstanceEditor
from .moi_framing import native_frames
from .moi_identity import MoiIdentity, seal
from .native_backup_records import BackupInspectionSource

PROFILE = "caf-native-source-correlation/1"
SCOPE = (
    "Compare the original opened CAF with one immutable native File 3 archive. "
    "Device identity and literal record identities are historical source evidence. "
    "Different format encodings may have different identities without different behavior. "
    "Parameters, logic, saved/live values, packages, resources and hardware are not compared. "
    "No full-program match, compiler compatibility, application association or field action is granted."
)
MAX_OBJECTS = 20000


class CafNativeCorrelationRequest(BackupInspectionSource):
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    query: str = Field(default="", max_length=256, strict=True)
    offset: int = Field(default=0, ge=0, le=40000, strict=True)
    limit: int = Field(default=64, ge=1, le=128, strict=True)


def canonical_number(value, maximum):
    if not isinstance(value, str) or not re.fullmatch(r"0|[1-9][0-9]{0,9}", value):
        return None
    number = int(value)
    return number if number <= maximum else None


def string_property(caf, obj, pid):
    props = [p for p in obj if p.tag == Q + "property" and int(p.get("id")) == pid]
    scalar = caf.scalar(props[0]) if len(props) == 1 else None
    if (
        scalar
        and scalar["type"] == "string"
        and not scalar["attributes"]
        and len(scalar["text"].encode("utf-8")) <= 4096
    ):
        return scalar["text"]
    return None


def correlate(caf, backups, request):
    options = CafNativeCorrelationRequest.model_validate(request)
    if caf.hash != options.source_sha256:
        raise ValueError("The opened CAF changed; compare its original source again.")
    snapshot, files, _ = backups.load(options.model_dump(include={"capture_id", "snapshot_sha256"}))
    identity = MoiIdentity(files[3])
    if identity.reader.errors:
        raise ValueError("Native correlation requires unambiguous framed engineering records.")
    if any(
        record["properties"][32527]["scalar"]["datatype"] != "CharacterString"
        for record in identity.reader.records.values()
    ):
        raise ValueError("Native correlation requires typed engineering reference strings.")
    if len(caf.objects) > MAX_OBJECTS:
        raise ValueError("CAF correlation supports at most 20000 recorded objects.")
    refs = set(caf.objects) | set(identity.reader.records)
    if any(len(ref) > 512 for ref in refs):
        raise ValueError("CAF/native correlation references must be at most 512 characters.")
    caf_identity = CafInstanceEditor(caf)
    native_identity = identity.summary()
    for key, pid in (("name", 2390), ("model", 70)):
        scalar = identity.root["properties"].get(pid, {}).get("scalar") or {}
        value = scalar.get("value")
        if (
            scalar.get("datatype") != "CharacterString"
            or not isinstance(value, str)
            or len(value.encode("utf-8")) > 4096
        ):
            native_identity[key] = None
    caf_root = {
        "root_ref": caf_identity.ref,
        "root_class": canonical_number(caf_identity.root.get("classid"), 65535),
        "instance": caf_identity.current,
        "name": string_property(caf, caf_identity.root, 2390),
        "model": string_property(caf, caf_identity.root, 70),
    }
    checks = [
        {
            "field": key,
            "caf": caf_root[key],
            "native": native_identity[key],
            "status": "unavailable"
            if caf_root[key] is None or native_identity[key] is None
            else "equal"
            if caf_root[key] == native_identity[key]
            else "different",
        }
        for key in ("root_ref", "root_class", "instance", "name", "model")
    ]
    acquisition_verified = (
        snapshot.get("source_identity_matches") is True
        and native_identity["name"] is not None
        and native_identity["model"] is not None
        and snapshot.get("identity", {}).get("vendor-identifier") == 5
        and snapshot["device"] == f"device,{identity.instance}"
        and snapshot["identity"].get("object-name") == native_identity["name"]
        and snapshot["identity"].get("model-name") == native_identity["model"]
    )
    frames = {
        start: (cid, int.from_bytes(oid, "big") & 0x3FFFFF)
        for start, cid, oid, _ in native_frames(identity.data, required=True)
    }
    caf_ids = {
        ref: (
            canonical_number(obj.get("classid"), 65535),
            canonical_number(obj.get("objectid"), 4194303),
        )
        for ref, obj in caf.objects.items()
    }
    native_ids = {ref: frames[record["offset"]] for ref, record in identity.reader.records.items()}
    caf_ref_conflicts = {
        ref
        for ref, obj in caf.objects.items()
        if any(p.tag == Q + "property" and int(p.get("id")) == 32527 for p in obj)
        and string_property(caf, obj, 32527) != ref
    }
    caf_counts, native_counts = Counter(caf_ids.values()), Counter(native_ids.values())
    records = []
    for ref in sorted(refs):
        left, right = caf_ids.get(ref), native_ids.get(ref)
        if left is None:
            status = "native-only"
        elif right is None:
            status = "caf-only"
        elif None in left or ref in caf_ref_conflicts:
            status = "identity-unavailable"
        elif caf_counts[left] > 1 or native_counts[right] > 1:
            status = "ambiguous-identity"
        elif left == right:
            status = "same-record-identity"
        else:
            status = "different-record-identity"
        records.append(
            {
                "ref": ref,
                "status": status,
                "caf_class": left[0] if left else None,
                "caf_object_id": left[1] if left else None,
                "native_class": right[0] if right else None,
                "native_object_id": right[1] if right else None,
            }
        )
    counts = dict(Counter(row["status"] for row in records))
    differences = any(row["status"] == "different" for row in checks) or any(
        counts.get(key, 0) for key in ("different-record-identity", "caf-only", "native-only")
    )
    incomplete = (
        not acquisition_verified
        or any(row["status"] == "unavailable" for row in checks)
        or any(counts.get(key, 0) for key in ("identity-unavailable", "ambiguous-identity"))
    )
    matches = [
        row
        for row in records
        if options.query.casefold() in " ".join(str(v) for v in row.values()).casefold()
    ]
    body = {
        "profile": PROFILE,
        "scope": SCOPE,
        "request": options.model_dump(),
        "caf": {
            "sha256": caf.hash,
            "root_identity": caf_root,
            "source": "original-opened-archive",
            "root_metadata_entries": len(caf.extra_entries),
        },
        "native_backup": backups.envelope(snapshot, files),
        "device_checks": checks,
        "recorded_acquisition_identity_verified": acquisition_verified,
        "classification": "recorded-differences"
        if differences
        else "identity-incomplete"
        if incomplete
        else "recorded-identities-equal",
        "coverage": {
            "caf_objects": len(caf.objects),
            "native_engineering_records": len(native_ids),
            "native_metadata_records": len(identity.reader.metadata_records),
            "union_references": len(records),
            "record_status_counts": counts,
            "caf_reference_conflicts": len(caf_ref_conflicts),
            "not_compared": [
                "Parameters, child object properties, retained saved values and live values",
                "Graph wiring, execution order, state and behavior",
                "CAF class versions, native schema/release and compiler compatibility",
                "Packages, resources, hardware suitability and physical acceptance",
            ],
        },
        "query": options.query,
        "offset": options.offset,
        "limit": options.limit,
        "total_matches": len(matches),
        "next_offset": options.offset + options.limit
        if options.offset + options.limit < len(matches)
        else None,
        "records": matches[options.offset : options.offset + options.limit],
        "read_only": True,
        "controller_queries": False,
        "field_actions": False,
        "full_program_match_verified": False,
        "compiler_compatibility_verified": False,
        "application_association_granted": False,
        "can_apply": False,
    }
    return {**body, "report_sha256": seal(body)}

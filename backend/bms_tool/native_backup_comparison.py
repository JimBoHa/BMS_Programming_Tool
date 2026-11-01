"""Bounded comparison of retained original bytes; never a restore or live read."""

from collections import Counter
from datetime import UTC, datetime

from pydantic import Field

from .models import StrictModel
from .moi_application import MoiApplication
from .moi_identity import seal, sha
from .native_backup_records import BackupInspectionSource, NativeBackupRecords

PROFILE = "native-backup-comparison/1"
MAX_RECORDS = 4096
MAX_PROPERTIES = 65536
MAX_CHANGES = 4096
PREVIEW_CHARS = 256
SCOPE = (
    "Original retained Files 3/11/12 and recognized engineering record/property encodings only. "
    "Metadata records are compared as an unaligned byte-hash multiset. No saved-setting merge, "
    "semantic equivalence, destination compatibility, restore, controller query or field action."
)


class BackupComparisonRequest(StrictModel):
    left: BackupInspectionSource
    right: BackupInspectionSource
    query: str = Field(default="", max_length=256, strict=True)
    offset: int = Field(default=0, ge=0, le=MAX_CHANGES, strict=True)
    limit: int = Field(default=32, ge=1, le=64, strict=True)


def property_evidence(prop):
    if prop is None:
        return None
    scalar = prop["scalar"]
    preview = scalar.copy() if scalar is not None else None
    truncated = False
    if preview and isinstance(preview["value"], str) and len(preview["value"]) > PREVIEW_CHARS:
        preview["value"] = preview["value"][:PREVIEW_CHARS]
        truncated = True
    return {
        "encoded_sha256": prop["encoded_sha256"],
        "encoded_bytes": prop["value_end_offset"] - prop["value_start_offset"],
        "scalar": preview,
        "preview_truncated": truncated,
    }


def record_evidence(record):
    if record is None:
        return None
    return {
        "record_id": f"record:{record['offset']}",
        "class_id": record["class_id"],
        "class_name": record["class_name"],
        "record_sha256": record["sha256"],
        "property_count": len(record["properties"]),
    }


class NativeBackupComparison:
    def __init__(self, records: NativeBackupRecords):
        self.records = records

    def source(self, options):
        snapshot, files = self.records.load_files(options.model_dump())
        envelope = self.records.envelope(snapshot, files)
        envelope["connector_config"] = snapshot.get("connector_config")
        application, error = None, None
        try:
            application = MoiApplication(files[3])
        except ValueError as exc:
            error = str(exc)[:512]
        envelope["readability"] = {
            "supported": application is not None,
            "error": error,
            "record_framing": application.record_framing if application else None,
            "parse_error_count": len(application.errors) if application else None,
            "parse_errors": application.errors[:16] if application else [],
            "engineering_records": len(application.records) if application else None,
            "expanded_sha256": sha(application.data) if application else None,
        }
        metadata = (
            Counter(row["sha256"] for row in application.metadata_records) if application else None
        )
        envelope["metadata_records"] = {
            "count": sum(metadata.values()) if metadata is not None else None,
            "hash_multiset_sha256": seal(dict(metadata)) if metadata is not None else None,
            "alignment": "No metadata records are paired by offset, order, name or model.",
        }
        return envelope, files, application

    def compare(self, request):
        options = BackupComparisonRequest.model_validate(request)
        left, left_files, left_app = self.source(options.left)
        right, right_files, right_app = self.source(options.right)
        reasons = []
        for side, application in [("left", left_app), ("right", right_app)]:
            if application is None:
                reasons.append(f"{side}: original File 3 is outside the recognized native reader.")
            elif application.errors or application.record_framing != "declared-lengths":
                reasons.append(
                    f"{side}: structured comparison requires unambiguous declared records."
                )
        supported = not reasons
        rows, records_seen, properties_seen = [], 0, 0
        budget_reason = None
        references = sorted(set(left_app.records) | set(right_app.records)) if supported else []

        def add(kind, ref, first, second, *, prop=None):
            if len(rows) >= MAX_CHANGES:
                return False
            rows.append(
                {
                    "kind": kind,
                    "reference": ref,
                    "property": prop,
                    "name": (
                        (second or first)["name"]
                        if prop is not None
                        else (second or first)["class_name"]
                    ),
                    "left": property_evidence(first)
                    if prop is not None
                    else record_evidence(first),
                    "right": property_evidence(second)
                    if prop is not None
                    else record_evidence(second),
                }
            )
            return True

        for ref in references:
            if records_seen >= MAX_RECORDS:
                budget_reason = "Engineering record comparison budget reached."
                break
            records_seen += 1
            first, second = left_app.records.get(ref), right_app.records.get(ref)
            if first is None or second is None:
                if not add(
                    "record-added" if first is None else "record-removed", ref, first, second
                ):
                    budget_reason = "Change evidence budget reached."
                    break
                continue
            if first["sha256"] != second["sha256"]:
                kind = (
                    "record-class-changed"
                    if first["class_id"] != second["class_id"]
                    else "record-bytes-changed"
                )
                if not add(kind, ref, first, second):
                    budget_reason = "Change evidence budget reached."
                    break
            if first["class_id"] != second["class_id"]:
                # The reference identifies the replacement, not a compatible schema.
                continue
            for pid in sorted(set(first["properties"]) | set(second["properties"])):
                if properties_seen >= MAX_PROPERTIES:
                    budget_reason = "Property comparison budget reached."
                    break
                properties_seen += 1
                before, after = first["properties"].get(pid), second["properties"].get(pid)
                if before and after and before["encoded_sha256"] == after["encoded_sha256"]:
                    continue
                kind = (
                    "property-added"
                    if before is None
                    else "property-removed"
                    if after is None
                    else "property-encoding-changed"
                )
                if not add(kind, ref, before, after, prop=pid):
                    budget_reason = "Change evidence budget reached."
                    break
            if budget_reason:
                break
        needle = options.query.strip().casefold()
        matches = [row for row in rows if not needle or needle in str(row).casefold()]
        report = {
            "profile": PROFILE,
            "source_kind": "retained-native-backup-comparison",
            "captured_at": datetime.now(UTC).isoformat(),
            "left": left,
            "right": right,
            "same_recorded_target": seal(left["target"]) == seal(right["target"]),
            "same_recorded_interface": (
                seal(left["connector_config"]) == seal(right["connector_config"])
                if isinstance(left["connector_config"], dict)
                and isinstance(right["connector_config"], dict)
                and left["connector_config"]
                and right["connector_config"]
                else None
            ),
            "files": [
                {
                    "file": key,
                    "equal": left_files[key] == right_files[key],
                    "left": {"bytes": len(left_files[key]), "sha256": sha(left_files[key])},
                    "right": {"bytes": len(right_files[key]), "sha256": sha(right_files[key])},
                }
                for key in (3, 11, 12)
            ],
            "structured_comparison": {
                "supported": supported,
                "reasons": reasons,
                "scan_complete": supported and budget_reason is None,
                "budget_reason": budget_reason,
                "alignment": "Unique engineering reference; properties only within the same native class.",
                "recognized_reference_union": len(references) if supported else None,
                "records_compared": records_seen,
                "properties_compared": properties_seen,
                "change_rows_observed": len(rows),
                "metadata_hash_multisets_equal": (
                    left["metadata_records"]["hash_multiset_sha256"]
                    == right["metadata_records"]["hash_multiset_sha256"]
                    if left_app is not None and right_app is not None
                    else None
                ),
                "coverage": "Recognized engineering records and property encodings; no semantic equivalence.",
            },
            "query": options.query,
            "offset": options.offset,
            "limit": options.limit,
            "total_matches": len(matches),
            "next_offset": options.offset + options.limit
            if options.offset + options.limit < len(matches)
            else None,
            "rows": matches[options.offset : options.offset + options.limit],
            "limits": {
                "records": MAX_RECORDS,
                "properties": MAX_PROPERTIES,
                "changes": MAX_CHANGES,
                "scalar_preview_characters": PREVIEW_CHARS,
            },
            "scope": SCOPE,
            "read_only": True,
            "controller_queries": False,
            "field_actions": False,
            "restore_plan": False,
            "semantics_verified": False,
        }
        return {**report, "evidence_sha256": seal(report)}

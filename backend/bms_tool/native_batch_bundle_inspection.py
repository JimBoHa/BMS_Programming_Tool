"""Inspect portable batch evidence in memory, without adopting field authority."""

import asyncio
import copy
import io
import re
import stat
import struct
import zipfile
import zlib
from datetime import datetime

from fastapi import APIRouter, UploadFile

from .application_store import PROFILE as TRANSFER_PROFILE
from .application_store import encoded, identifier
from .moi_identity import seal, sha
from .native_backup_import import read_archive
from .native_backup_records import BackupInspectionSource, NativeBackupRecords
from .native_default_batch_evidence import MAX_BUNDLE, MAX_CAPTURE, MAX_COMPARISON, MAX_PROOF
from .native_default_batch_evidence import PROFILE as BUNDLE_PROFILE
from .native_default_batch_evidence import SCOPE as BUNDLE_SCOPE
from .native_default_batch_result_match import NativeDefaultBatchResultMatch
from .native_schedule_library import strict_json

PROFILE = "native-default-batch-bundle-inspection/1"
SCOPE = (
    "In-memory inspection of one portable typed-batch evidence bundle. Internal byte, "
    "proof and reconstructed-comparison consistency only; hashes are not signatures or "
    "vendor provenance. Historical bundled evidence is not a current controller, complete "
    "backup or journal, imported receipt, review, recovery or transfer authority."
)
FALSE_FLAGS = (
    "controller_queries",
    "field_actions",
    "can_apply",
    "field_transfer_enabled",
    "current_device_verified",
    "credentials_restored",
    "reviews_restored",
    "complete_controller_backup",
    "complete_journal",
)


def stored_members(raw):
    """Accept the exporter's fixed, stored ZIP layout; never extract paths."""
    if type(raw) is not bytes or not 66 <= len(raw) <= MAX_BUNDLE:
        raise ValueError("Comparison evidence ZIP must be at most 20 MiB.")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) not in (5, 6) or archive.comment:
                raise ValueError("Evidence ZIP requires its fixed five or six members.")
            names = [entry.filename for entry in entries]
            if len(set(names)) != len(names) or set(names) - {
                "manifest.json",
                "comparison.json",
                "intent.json",
                "proof.json",
                *[n for n in names if re.fullmatch(r"captures/[a-f0-9]{32}\.zip", n)],
            }:
                raise ValueError("Evidence ZIP has duplicate or unsupported member paths.")
            result, cursor = {}, 0
            for entry in entries:
                name = entry.filename.encode("ascii")
                limit = (
                    MAX_CAPTURE
                    if entry.filename.startswith("captures/")
                    else MAX_COMPARISON
                    if entry.filename == "comparison.json"
                    else 64 * 1024
                    if entry.filename == "manifest.json"
                    else MAX_PROOF
                )
                if (
                    entry.header_offset != cursor
                    or entry.flag_bits != 0
                    or entry.compress_type != zipfile.ZIP_STORED
                    or entry.extra
                    or entry.comment
                    or entry.volume != 0
                    or entry.is_dir()
                    or entry.external_attr & 16
                    or stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG)
                    or not 1 <= entry.file_size <= limit
                    or entry.compress_size != entry.file_size
                    or cursor + 30 > len(raw)
                ):
                    raise ValueError("Evidence ZIP member layout, type or size is unsupported.")
                header = struct.unpack_from("<4s5H3I2H", raw, cursor)
                if (
                    header[0] != b"PK\x03\x04"
                    or header[2:4] != (0, 0)
                    or header[6:9] != (entry.CRC, entry.file_size, entry.file_size)
                    or header[9:11] != (len(name), 0)
                    or raw[cursor + 30 : cursor + 30 + len(name)] != name
                ):
                    raise ValueError("Evidence ZIP local and central descriptions disagree.")
                with archive.open(entry) as stream:
                    value = stream.read(limit + 1)
                if len(value) != entry.file_size or zlib.crc32(value) != entry.CRC:
                    raise ValueError("Evidence ZIP member is damaged.")
                result[entry.filename] = value
                cursor += 30 + len(name) + len(value)
            directory = cursor
            for entry in entries:
                name = entry.filename.encode("ascii")
                if cursor + 46 + len(name) > len(raw):
                    raise ValueError("Evidence ZIP directory is truncated.")
                header = struct.unpack_from("<4s6H3I5H2I", raw, cursor)
                if (
                    header[0] != b"PK\x01\x02"
                    or header[3:5] != (0, 0)
                    or header[7:10] != (entry.CRC, entry.file_size, entry.file_size)
                    or header[10:14] != (len(name), 0, 0, 0)
                    or header[16] != entry.header_offset
                    or raw[cursor + 46 : cursor + 46 + len(name)] != name
                ):
                    raise ValueError("Evidence ZIP central directory is inconsistent.")
                cursor += 46 + len(name)
            if cursor + 22 != len(raw) or struct.unpack_from("<4s4H2IH", raw, cursor) != (
                b"PK\x05\x06",
                0,
                0,
                len(entries),
                len(entries),
                cursor - directory,
                directory,
                0,
            ):
                raise ValueError("Evidence ZIP has unsupported boundaries or trailing bytes.")
            return result
    except (
        zipfile.BadZipFile,
        OSError,
        RuntimeError,
        NotImplementedError,
        UnicodeError,
        struct.error,
        zlib.error,
    ) as exc:
        raise ValueError("Comparison evidence ZIP cannot be safely interpreted.") from exc


def sealed_json(raw, limit, profile=None):
    value = strict_json(raw, limit)
    if type(value) is not dict or (profile is not None and value.get("profile") != profile):
        raise ValueError("Evidence requires a supported sealed JSON object.")
    digest = value.get("evidence_sha256")
    if type(digest) is not str or digest != seal(
        {k: v for k, v in value.items() if k != "evidence_sha256"}
    ):
        raise ValueError("Evidence JSON seal differs from its actual contents.")
    return value


def timestamp(value):
    if type(value) is not str or not 1 <= len(value) <= 64:
        raise ValueError("Historical evidence requires a bounded observation time.")
    try:
        if datetime.fromisoformat(value).tzinfo is None:
            raise ValueError("Missing timezone.")
    except ValueError as exc:
        raise ValueError("Historical evidence requires a valid time with timezone.") from exc


class _MemoryEvidence:
    """Only read methods; deliberately no application store or journal connection."""

    def __init__(self, captures, intent, proof, kind):
        self.captures, self.intent, self.proof, self.kind = captures, intent, proof, kind

    def load(self, key):
        identifier(key)
        if key not in self.captures:
            raise ValueError("The bundle lacks a required original capture.")
        return copy.deepcopy(self.captures[key])

    def receipt(self, key, **kwargs):
        if key != self.intent["id"]:
            raise ValueError("The bundle has a different recorded intent.")
        # A private comparison input, never a receipt in the application journal.
        return {
            "pending": False,
            "intent": copy.deepcopy(self.intent),
            "result": copy.deepcopy(self.proof) if self.kind == "result" else None,
        }

    def verified_readback(self, key):
        if key != self.intent["id"]:
            raise ValueError("The bundle has a different recorded readback.")
        return copy.deepcopy(self.proof) if self.kind == "readback-event" else None


class _MemoryRecords(NativeBackupRecords):
    def load_files(self, request):
        options = BackupInspectionSource.model_validate(request)
        snapshot, files = self.storage.load(options.capture_id)
        if snapshot["evidence_sha256"] != options.snapshot_sha256:
            raise ValueError("The bundled snapshot binding changed.")
        return snapshot, files


class _MemoryComparison(NativeDefaultBatchResultMatch):
    def _original(self, capture_id):
        return self.storage.load(capture_id)


def inspect_bundle(raw):
    """Recompile/compare solely from the input bytes, without retaining any state."""
    try:
        members = stored_members(raw)
        manifest = sealed_json(members["manifest.json"], 64 * 1024, BUNDLE_PROFILE)
        if (
            set(manifest)
            != {
                "profile",
                "scope",
                "receipt_id",
                "intent_sha256",
                "verified_proof",
                "comparison_sha256",
                "comparison_state",
                "original_backup_id",
                "current_capture_id",
                "captures",
                "members",
                "read_only",
                "evidence_sha256",
                *FALSE_FLAGS,
            }
            or manifest["scope"] != BUNDLE_SCOPE
            or manifest["read_only"] is not True
            or any(manifest[key] is not False for key in FALSE_FLAGS)
            or type(manifest["captures"]) is not dict
            or type(manifest["members"]) is not dict
            or type(manifest["verified_proof"]) is not dict
            or set(manifest["verified_proof"]) != {"kind", "sha256", "time"}
        ):
            raise ValueError("The evidence manifest scope or authority markers are unsupported.")
        for key in ("receipt_id", "original_backup_id", "current_capture_id"):
            identifier(manifest[key])
        roles = {manifest["original_backup_id"], manifest["current_capture_id"]}
        names = {
            "manifest.json",
            "comparison.json",
            "intent.json",
            "proof.json",
            *[f"captures/{key}.zip" for key in roles],
        }
        if (
            set(manifest["captures"]) != roles
            or set(members) != names
            or set(manifest["members"]) != names - {"manifest.json"}
        ):
            raise ValueError("The evidence manifest does not describe exactly its source roles.")
        for name, detail in manifest["members"].items():
            if (
                type(detail) is not dict
                or set(detail) != {"bytes", "sha256"}
                or type(detail["bytes"]) is not int
                or detail != {"bytes": len(members[name]), "sha256": sha(members[name])}
            ):
                raise ValueError("An evidence member differs from its declared bytes or hash.")
        captures = {}
        for key, digest in manifest["captures"].items():
            snapshot, files, _ = read_archive(members[f"captures/{key}.zip"])
            if snapshot["id"] != key or snapshot["evidence_sha256"] != digest:
                raise ValueError("A nested original capture differs from its declared binding.")
            timestamp(snapshot["captured_at"])
            captures[key] = snapshot, files
        intent = sealed_json(members["intent.json"], MAX_PROOF, TRANSFER_PROFILE)
        proof = sealed_json(members["proof.json"], MAX_PROOF, TRANSFER_PROFILE)
        comparison = sealed_json(members["comparison.json"], MAX_COMPARISON)
        reference = manifest["verified_proof"]
        timestamp(reference["time"])
        kind = reference["kind"]
        if (
            intent.get("id") != manifest["receipt_id"]
            or intent["evidence_sha256"] != manifest["intent_sha256"]
            or intent.get("may_have_applied") is not True
            or proof.get("receipt_id") != manifest["receipt_id"]
            or proof["evidence_sha256"] != reference["sha256"]
            or kind not in ("result", "readback-event")
            or (
                kind == "result"
                and (
                    proof.get("intent_sha256") != intent["evidence_sha256"]
                    or proof.get("may_have_applied") is not True
                    or proof.get("finished_at") != reference["time"]
                )
            )
            or (
                kind == "readback-event"
                and (
                    proof.get("stage") != "readback" or proof.get("created_at") != reference["time"]
                )
            )
        ):
            raise ValueError(
                "The included proof does not bind its original intent and selected kind."
            )
        observation = proof if kind == "result" else proof.get("detail")
        if (
            type(observation) is not dict
            or observation.get("status") != "verified"
            or observation.get("operational") is not True
            or type(observation.get("system_status")) is not int
            or observation["system_status"] != 0
            or observation.get("native_sha256") != intent.get("native_payload_sha256")
            or observation.get("expected_native_sha256") != intent.get("native_payload_sha256")
            or type(observation.get("readback")) is not dict
            or observation["readback"].get("identity") != intent.get("identity")
            or observation["readback"].get("status") != "verified_new"
            or type(observation.get("preservation")) is not dict
            or observation["preservation"].get("application_identical_except_selected_defaults")
            is not True
            or observation["preservation"].get("identity_unchanged") is not True
            or observation["preservation"].get("preserved_native_sha256")
            != intent.get("native_payload_sha256")
        ):
            raise ValueError(
                "The included historical proof has an inconsistent native verification."
            )
        memory = _MemoryEvidence(captures, intent, proof, kind)
        report = _MemoryComparison(_MemoryRecords(memory)).compare(
            {
                "receipt_id": manifest["receipt_id"],
                "capture_id": manifest["current_capture_id"],
                "snapshot_sha256": manifest["captures"][manifest["current_capture_id"]],
            }
        )
        original = captures[manifest["original_backup_id"]][1]
        preservation = observation["preservation"]
        expected_selected = []
        for row, guard in zip(report["selected"], intent["batch_guard"]["fields"], strict=True):
            values = (
                {"before_bits": guard["prior_bits"], "after_bits": row["expected"]["bits"]}
                if row["kind"] == "real"
                else {"before_value": guard["prior_value"], "after_value": row["expected"]["value"]}
            )
            expected_selected.append(
                {
                    "kind": row["kind"],
                    "record_ref": row["record_ref"],
                    "class_id": row["class_id"],
                    "effective_value_verified": True,
                    **values,
                }
            )
        if (
            encoded(preservation.get("selected_defaults")) != encoded(expected_selected)
            or preservation.get("source_application_sha256") != sha(original[3])
            or preservation.get("source_saved_parameters_sha256")
            != sha(original[11] + original[12])
            or preservation.get("controller_writes") is not False
            or preservation.get("enum_semantics_verified") is not False
        ):
            raise ValueError(
                "The historical preservation proof differs from its reconstructed edits."
            )
        if (
            encoded(report) != encoded(comparison)
            or manifest["comparison_sha256"] != report["evidence_sha256"]
            or manifest["comparison_state"] != report["state"]
            or manifest["original_backup_id"] != report["original_backup_id"]
        ):
            raise ValueError(
                "The included comparison differs from actual bundled-file recompilation."
            )
        body = {
            "profile": PROFILE,
            "scope": SCOPE,
            "bundle_sha256": sha(raw),
            "bundle_bytes": len(raw),
            "manifest_sha256": sha(members["manifest.json"]),
            "manifest": manifest,
            "comparison": report,
            "members": [
                {"name": name, "bytes": len(value), "sha256": sha(value)}
                for name, value in sorted(members.items())
            ],
            "capture_count": len(captures),
            "internal_consistency_verified": True,
            "native_result_reconstructed": True,
            "read_only": True,
            "storage_imported": False,
            "receipt_restored": False,
            "vendor_provenance_verified": False,
            **{key: False for key in FALSE_FLAGS},
        }
        return {**body, "inspection_sha256": seal(body)}
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError(
            "Comparison evidence has missing or inconsistent supported fields."
        ) from exc


def batch_bundle_inspection_router():
    router = APIRouter(prefix="/api/bacnet/controller/native-application/default-batch/result")

    @router.post("/inspect-evidence")
    async def inspect_evidence(file: UploadFile):
        raw = await file.read(MAX_BUNDLE + 1)
        return await asyncio.to_thread(inspect_bundle, raw)

    return router

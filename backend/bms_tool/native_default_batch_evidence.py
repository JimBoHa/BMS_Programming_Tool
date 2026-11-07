"""Explicit portable export of retained batch evidence, without field authority."""

import io
import json
import stat
import zipfile

from fastapi.responses import JSONResponse, Response
from pydantic import Field

from .application_store import encoded
from .moi_identity import seal, sha
from .native_default_batch_result_match import NativeDefaultBatchResultMatch
from .native_default_recovery import DefaultRecoveryPrepare, _verified_proof

PROFILE = "native-default-batch-evidence-bundle/1"
HEADER = "X-Native-Batch-Evidence"
MAX_BUNDLE = 20 * 1024 * 1024
MAX_CAPTURE = 8 * 1024 * 1024
MAX_COMPARISON = 512 * 1024
MAX_PROOF = 128 * 1024
SCOPE = (
    "Local export of retained Files3/11/12, original typed-batch intent, selected immutable "
    "verification proof and comparison. Not a complete journal or controller backup, "
    "import, executable application, recovery or field authority."
)


class BatchEvidenceExport(DefaultRecoveryPrepare):
    comparison_sha256: str = Field(strict=True, pattern=r"^[0-9a-f]{64}$")


class NativeDefaultBatchEvidence:
    def __init__(self, records):
        self.records = records
        self.storage = records.storage

    def _capture(self, capture_id, snapshot_sha256):
        try:
            snapshot, files = self.storage.load(capture_id)
            if (
                snapshot["id"] != capture_id
                or snapshot["evidence_sha256"] != snapshot_sha256
                or set(files) != {3, 11, 12}
            ):
                raise ValueError("The selected capture changed; compare the retained source again.")
            raw = self.storage.export(capture_id)
            if not 1 <= len(raw) <= MAX_CAPTURE:
                raise ValueError("The retained capture archive exceeds its 8 MiB limit.")
            expected = {
                "manifest.json": encoded(snapshot),
                **{f"file-{number}.bin": value for number, value in files.items()},
            }
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                members = archive.infolist()
                if (
                    len(members) != 4
                    or {m.filename for m in members} != set(expected)
                    or archive.comment
                ):
                    raise ValueError("The exported capture has inconsistent members.")
                for member in members:
                    if (
                        member.is_dir()
                        or member.flag_bits & 1
                        or member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                        or stat.S_IFMT(member.external_attr >> 16) not in (0, stat.S_IFREG)
                        or member.file_size != len(expected[member.filename])
                    ):
                        raise ValueError(
                            "The exported capture member changed or has an unsupported type."
                        )
                    with archive.open(member) as stream:
                        value = stream.read(len(expected[member.filename]) + 1)
                    if value != expected[member.filename]:
                        raise ValueError(
                            "The exported capture does not preserve its original bytes."
                        )
            return raw
        except (OSError, zipfile.BadZipFile, NotImplementedError) as exc:
            raise ValueError(
                "A retained capture is unavailable or inconsistent; compare again."
            ) from exc

    def export(self, request):
        options = BatchEvidenceExport.model_validate(request)
        query = options.model_dump(exclude={"comparison_sha256"})
        report = NativeDefaultBatchResultMatch(self.records).compare(query)
        if report["evidence_sha256"] != options.comparison_sha256:
            raise ValueError("The selected comparison changed; compare the retained source again.")
        receipt = self.storage.receipt(options.receipt_id, include_events=False)
        proof_ref = _verified_proof(receipt, self.storage, options.receipt_id, label="typed batch")
        if (
            receipt["intent"]["evidence_sha256"] != report["intent_sha256"]
            or seal({k: v for k, v in receipt["intent"].items() if k != "evidence_sha256"})
            != report["intent_sha256"]
            or proof_ref != report["verified_proof"]
        ):
            raise ValueError("The original intent or selected verification proof changed.")
        proof = (
            receipt["result"]
            if proof_ref["kind"] == "result"
            else self.storage.verified_readback(options.receipt_id)
        )
        if (
            proof is None
            or proof.get("evidence_sha256") != proof_ref["sha256"]
            or seal({k: v for k, v in proof.items() if k != "evidence_sha256"})
            != proof_ref["sha256"]
        ):
            raise ValueError("The selected immutable verification proof is unavailable.")
        members = {
            "intent.json": encoded(receipt["intent"]),
            "proof.json": encoded(proof),
            "comparison.json": JSONResponse(report).body,
        }
        if (
            any(len(members[name]) > MAX_PROOF for name in ("intent.json", "proof.json"))
            or len(members["comparison.json"]) > MAX_COMPARISON
        ):
            raise ValueError("The selected comparison or proof exceeds its evidence export bound.")
        captures = {
            report["original_backup_id"]: report["original_snapshot_sha256"],
            report["source"]["capture_id"]: report["source"]["snapshot_sha256"],
        }
        if (
            report["original_backup_id"] == report["source"]["capture_id"]
            and report["original_snapshot_sha256"] != report["source"]["snapshot_sha256"]
        ):
            raise ValueError("One capture cannot have two different snapshot bindings.")
        for capture_id, snapshot_sha256 in sorted(captures.items()):
            members[f"captures/{capture_id}.zip"] = self._capture(capture_id, snapshot_sha256)
        body = {
            "profile": PROFILE,
            "scope": SCOPE,
            "receipt_id": options.receipt_id,
            "intent_sha256": report["intent_sha256"],
            "verified_proof": proof_ref,
            "comparison_sha256": options.comparison_sha256,
            "comparison_state": report["state"],
            "original_backup_id": report["original_backup_id"],
            "current_capture_id": report["source"]["capture_id"],
            "captures": captures,
            "members": {
                name: {"bytes": len(value), "sha256": sha(value)}
                for name, value in sorted(members.items())
            },
            "read_only": True,
            "controller_queries": False,
            "field_actions": False,
            "can_apply": False,
            "field_transfer_enabled": False,
            "current_device_verified": False,
            "credentials_restored": False,
            "reviews_restored": False,
            "complete_controller_backup": False,
            "complete_journal": False,
        }
        manifest = {**body, "evidence_sha256": seal(body)}
        manifest_bytes = encoded(manifest)
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_STORED) as archive:
            archive.writestr("manifest.json", manifest_bytes)
            for name, value in sorted(members.items()):
                archive.writestr(name, value)
        raw = output.getvalue()
        if len(raw) > MAX_BUNDLE:
            raise ValueError("The comparison evidence bundle exceeds its 20 MiB limit.")
        metadata = {
            "profile": PROFILE,
            "scope": SCOPE,
            "receipt_id": options.receipt_id,
            "comparison_sha256": options.comparison_sha256,
            "comparison_state": report["state"],
            "original_backup_id": report["original_backup_id"],
            "current_capture_id": report["source"]["capture_id"],
            "proof_sha256": proof_ref["sha256"],
            "manifest_sha256": sha(manifest_bytes),
            "bundle_sha256": sha(raw),
            "bytes": len(raw),
            "capture_count": len(captures),
            "member_count": len(members) + 1,
            "read_only": True,
            "field_actions": False,
            "can_apply": False,
            "current_device_verified": False,
            "credentials_restored": False,
            "reviews_restored": False,
            "complete_controller_backup": False,
            "complete_journal": False,
        }
        return raw, metadata

    def response(self, request):
        raw, metadata = self.export(request)
        return Response(
            raw,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="native-batch-evidence-{metadata["receipt_id"]}.zip"',
                HEADER: json.dumps(metadata, separators=(",", ":")),
            },
        )

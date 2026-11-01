"""Snapshot-based native Real-default compilation; no controller operations."""

from pydantic import Field

from .models import StrictModel
from .moi_identity import MoiIdentity, seal, sha
from .moi_parameters import ParameterApplication
from .moi_signal_defaults import MoiSignalDefaults

PROFILE = "native-effective-signal-default-compiler/1"
SCOPE = (
    "Compile one existing class 526/527 Real Default Value after merging this retained "
    "snapshot's saved parameters into its native application. Preserve every other merged "
    "expanded byte. No controller query/write, current-setting guarantee, general logic "
    "generation, CCT reopening or physical/firmware acceptance."
)


class SignalCompilerSource(StrictModel):
    capture_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class SignalCompilerPreview(SignalCompilerSource):
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_ref: str = Field(min_length=1, max_length=512, strict=True)
    encoded_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    value_text: str = Field(min_length=1, max_length=128, strict=True)


class SignalCompilerExport(SignalCompilerPreview):
    review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EffectiveSignalCompiler:
    def __init__(self, files):
        if set(files) != {3, 11, 12}:
            raise ValueError("Compile from one complete retained File 3/11/12 snapshot.")
        self.archive = MoiSignalDefaults(files[3])
        self.merged, self.parameters = ParameterApplication(
            files[3], files[11], files[12]
        ).compile()
        self.effective = MoiSignalDefaults(self.merged)
        before, after = self.archive.editor.summary(), self.effective.editor.summary()
        if any(before[key] != after[key] for key in ("instance", "name", "model")):
            raise ValueError(
                "Saved settings would change application identity; this profile refuses it."
            )
        if self.archive.candidates.keys() != self.effective.candidates.keys():
            raise ValueError("Saved settings changed supported signal membership or references.")
        for ref, (record, _) in self.effective.candidates.items():
            original, _ = self.archive.candidates[ref]
            old_id = self.archive.editor.data[original["offset"] + 6 : original["offset"] + 10]
            new_id = self.effective.editor.data[record["offset"] + 6 : record["offset"] + 10]
            if old_id != new_id:
                raise ValueError(
                    "Saved settings reassigned a signal reference to another native object."
                )
        self.files = {
            str(key): {"bytes": len(data), "sha256": sha(data)} for key, data in files.items()
        }

    def fields(self):
        result = []
        if len(self.effective.candidates) > 4096:
            raise ValueError("This compiler view supports at most 4096 existing signal defaults.")
        for ref, (record, prop) in sorted(self.effective.candidates.items()):
            old_record, old = self.archive.candidates[ref]
            if old_record["class_id"] != record["class_id"]:
                raise ValueError("Saved settings changed a signal's native class.")
            result.append(
                {
                    "ref": ref,
                    "class_id": record["class_id"],
                    "property": 3113,
                    "encoded_sha256": prop["encoded_sha256"],
                    "archive_value": old["scalar"]["value"],
                    "archive_bits": self.archive.editor.data[
                        old["value_start_offset"] + 1 : old["value_start_offset"] + 5
                    ].hex(),
                    "effective_value": prop["scalar"]["value"],
                    "effective_bits": self.effective.editor.data[
                        prop["value_start_offset"] + 1 : prop["value_start_offset"] + 5
                    ].hex(),
                    "saved_value_differs": old["encoded_sha256"] != prop["encoded_sha256"],
                }
            )
        return result

    def compile(self, *, record_ref, encoded_sha256, value_text):
        request = {
            "source_sha256": self.effective.editor.source_sha256,
            "record_ref": record_ref,
            "encoded_sha256": encoded_sha256,
            "value_text": value_text,
        }
        plan = self.effective.preview(**request)
        output, edit = self.effective.export(**request, plan_sha256=plan["plan_sha256"])
        checked = MoiIdentity(output)
        before = self.effective.editor
        offset = edit["native_byte_offset"]
        if (
            checked.data[:offset] != before.data[:offset]
            or checked.data[offset + 4 :] != before.data[offset + 4 :]
        ):
            raise ValueError("Compiled output changed a non-selected merged application byte.")
        return output, {
            "profile": PROFILE,
            "scope": SCOPE,
            "files": self.files,
            "parameter_merge": self.parameters,
            "selected_edit": edit,
            "compiled_sha256": sha(output),
            "compiled_native_sha256": sha(checked.data),
            "native_record_count": len(checked.records),
            "other_merged_bytes_preserved": True,
            "selected_field_changed": edit["changed"],
            "controller_write": False,
            "field_transfer_enabled": False,
        }


class SignalCompilerService:
    def __init__(self, storage):
        self.storage = storage

    def sources(self):
        captures = self.storage.captures()
        return {
            "profile": PROFILE,
            "scope": SCOPE,
            "controller_queries": False,
            "sources": [
                {
                    key: row.get(key)
                    for key in (
                        "id",
                        "captured_at",
                        "target",
                        "device",
                        "identity",
                        "source_identity_matches",
                        "evidence_sha256",
                    )
                }
                for row in captures
            ],
        }

    def load(self, capture_id):
        SignalCompilerSource(capture_id=capture_id)
        folder = self.storage.directory / capture_id
        if folder.is_symlink():
            raise ValueError(
                "Native compiler snapshots must remain in their original storage folder."
            )
        try:
            snapshot, files = self.storage.load(capture_id)
        except OSError as exc:
            raise ValueError(
                "Native backup source is unavailable; retain or capture a complete backup before compiling."
            ) from exc
        if (
            not snapshot.get("source_identity_matches")
            or snapshot.get("identity", {}).get("vendor-identifier") != 5
        ):
            raise ValueError("Select a complete identity-verified native vendor 5 backup.")
        compiler = EffectiveSignalCompiler(files)
        identity = compiler.archive.editor.summary()
        if (
            snapshot.get("device") != f"device,{identity['instance']}"
            or snapshot["identity"].get("object-name") != identity["name"]
            or snapshot["identity"].get("model-name") != identity["model"]
        ):
            raise ValueError("Retained native application and snapshot identity disagree.")
        return snapshot, compiler

    def source(self, capture_id):
        snapshot, compiler = self.load(capture_id)
        return {
            "profile": PROFILE,
            "scope": SCOPE,
            "capture_id": capture_id,
            "snapshot_sha256": snapshot["evidence_sha256"],
            "captured_at": snapshot["captured_at"],
            "target": snapshot["target"],
            "device": snapshot["device"],
            "identity": snapshot["identity"],
            "parameter_merge": compiler.parameters,
            "fields": compiler.fields(),
            "controller_queries": False,
            "controller_write": False,
        }

    def preview(self, request):
        request = SignalCompilerPreview.model_validate(request)
        snapshot, compiler = self.load(request.capture_id)
        if request.snapshot_sha256 != snapshot["evidence_sha256"]:
            raise ValueError("The retained snapshot changed; reopen its source before review.")
        output, compilation = compiler.compile(
            **request.model_dump(include={"record_ref", "encoded_sha256", "value_text"})
        )
        body = {
            "profile": PROFILE,
            "request": request.model_dump(),
            "target": snapshot["target"],
            "device": snapshot["device"],
            "captured_at": snapshot["captured_at"],
            "compilation": compilation,
            "controller_write": False,
            "scope": SCOPE,
        }
        return output, {**body, "review_sha256": seal(body)}

    def export(self, request):
        request = SignalCompilerExport.model_validate(request)
        output, review = self.preview(request.model_dump(exclude={"review_sha256"}))
        if request.review_sha256 != review["review_sha256"]:
            raise ValueError(
                "The native compilation review changed; review the current source again."
            )
        return output, review

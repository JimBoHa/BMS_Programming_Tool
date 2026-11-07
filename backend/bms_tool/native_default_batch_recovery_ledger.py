"""Bounded recorded batch lineage; no parent/source reads or field authority."""

import copy
import math
import struct
from typing import Literal

from pydantic import Field, model_validator

from .models import StrictModel
from .moi_identity import seal
from .native_default_batch_ledger import batch_reference
from .native_default_batch_recovery import PROFILE as ORIGIN_PROFILE
from .native_default_batch_recovery_transfer import METADATA
from .native_default_batch_recovery_transfer import PROFILE as TRANSFER_PROFILE
from .native_default_batch_recovery_transfer import SCOPE as TRANSFER_SCOPE
from .native_ledger_details import Digest, Identifier, RecordedProof

PROFILE = "native-default-batch-recovery-recorded/1"
SCOPE = (
    "Recorded previous typed batch origin seal and child-receipt bindings only. "
    "Parent receipts, backup files and current controller state are not revalidated. "
    "This projection grants no recovery or transfer authority; Enum meanings remain unverified."
)
UNAVAILABLE = (
    "Recorded batch recovery metadata is incomplete or inconsistent; inspect original evidence."
)


def recovery_namespace(body):
    return type(body) is dict and any(k.startswith("recovery_") for k in body)


class RecordedField(StrictModel):
    kind: Literal["real", "boolean", "enum"]
    record_ref: str = Field(strict=True, min_length=1, max_length=512)
    class_id: int = Field(strict=True)
    property: int = Field(strict=True, ge=3113, le=3113)
    previous: dict
    recorded_after: dict
    current: dict
    already_recorded: bool = Field(strict=True)
    current_encoded_sha256: Digest

    @model_validator(mode="after")
    def typed_values(self):
        if (
            self.class_id
            not in {"real": (526, 527), "boolean": (530, 531), "enum": (528, 529)}[self.kind]
        ):
            raise ValueError("The recorded class and datatype differ.")
        if any(ord(c) < 32 or ord(c) == 127 for c in self.record_ref):
            raise ValueError("Use a single-line native reference.")
        self.record_ref.encode("utf-8", "strict")
        for v in (self.previous, self.recorded_after, self.current):
            if self.kind == "real":
                if set(v) != {"bits"} or type(v["bits"]) is not str or len(v["bits"]) != 8:
                    raise ValueError("Recorded Real values need exact finite float32 bits.")
                raw = bytes.fromhex(v["bits"])
                if raw.hex() != v["bits"] or not math.isfinite(struct.unpack(">f", raw)[0]):
                    raise ValueError("Recorded Real values need exact finite float32 bits.")
            elif set(v) != {"value"} or (
                self.kind == "boolean"
                and type(v["value"]) is not bool
                or self.kind == "enum"
                and (type(v["value"]) is not int or not 0 <= v["value"] <= 65535)
            ):
                raise ValueError("The recorded value lost its strict datatype.")
        if self.current not in (
            self.previous,
            self.recorded_after,
        ) or self.already_recorded is not (self.current == self.previous):
            raise ValueError("The recorded current value contradicts its original lineage.")
        return self


class RecordedOrigin(StrictModel):
    profile: Literal[ORIGIN_PROFILE]
    parent_receipt_id: Identifier
    parent_intent_sha256: Digest
    original_dispatch: Literal["possible"]
    verified_proof: RecordedProof
    original_backup_id: Identifier
    original_snapshot_sha256: Digest
    current_capture_id: Identifier
    current_snapshot_sha256: Digest
    recorded_native_payload_sha256: Digest
    fields: list[RecordedField] = Field(min_length=1, max_length=16)
    enum_semantics_verified: bool = Field(strict=True)


def recovery_reference(body):
    unavailable = {
        "native_default_batch": {"state": "unavailable", "scope": UNAVAILABLE},
        "native_default_batch_recovery": {"state": "unavailable", "scope": UNAVAILABLE},
    }
    try:
        if (
            not recovery_namespace(body)
            or {k for k in body if k.startswith("recovery_")} != METADATA
            or body.get("recovery_profile") != TRANSFER_PROFILE
            or body.get("recovery_scope") != TRANSFER_SCOPE
        ):
            return unavailable
        origin = RecordedOrigin.model_validate(body["recovery_origin"])
        o = origin.model_dump()
        ordinary = batch_reference({k: v for k, v in body.items() if k not in METADATA})
        base = ordinary.get("native_default_batch", {})
        if (
            base.get("state") != "recorded"
            or seal(o) != body.get("recovery_origin_sha256")
            or origin.enum_semantics_verified is not False
            or origin.parent_receipt_id == body.get("id")
            or origin.original_backup_id == origin.current_capture_id
            or origin.current_capture_id != body.get("review_capture_id")
            or origin.current_capture_id != body["batch_edit"]["capture_id"]
            or origin.current_snapshot_sha256 != body["batch_edit"]["snapshot_sha256"]
            or body.get("identity", {}).get("device") != f"device,{body['old_instance']}"
            or type(body["identity"].get("vendor-identifier")) is not int
            or body["identity"]["vendor-identifier"] != 5
            or body["identity"].get("object-name") != body.get("old_name")
            or type(body.get("target")) is not dict
            or body["target"].get("device") not in (None, f"device,{body['old_instance']}")
            or type(body["target"].get("address")) is not str
            or not body["target"]["address"]
            or len(origin.fields) != len(base["selected"])
        ):
            return unavailable
        if (
            type(body.get("id")) is not str
            or len(body["id"]) != 32
            or any(c not in "0123456789abcdef" for c in body["id"])
        ):
            return unavailable
        for f, selected, guard in zip(
            origin.fields, base["selected"], body["batch_guard"]["fields"], strict=True
        ):
            proposed = (
                {"bits": selected["after_encoding_hex"][2:-2]}
                if f.kind == "real"
                else {"value": selected["after_encoding_hex"] == "112f"}
                if f.kind == "boolean"
                else {"value": int(selected["after_encoding_hex"][2:-2], 16)}
            )
            current = (
                {"bits": guard["prior_bits"]}
                if f.kind == "real"
                else {"value": guard["prior_value"]}
            )
            if (
                any(getattr(f, k) != selected[k] for k in ("kind", "record_ref", "class_id"))
                or f.current_encoded_sha256 != guard["encoded_sha256"]
                or f.previous != proposed
                or f.current != current
            ):
                return unavailable
        return {
            **ordinary,
            "native_default_batch_recovery": {
                "state": "recorded",
                "profile": PROFILE,
                "scope": SCOPE,
                "child_receipt_id": body["id"],
                "instance": body["old_instance"],
                "review_capture_id": body["review_capture_id"],
                "review_snapshot_sha256": body["batch_edit"]["snapshot_sha256"],
                "origin": copy.deepcopy(o),
                "origin_sha256": body["recovery_origin_sha256"],
                "compiled_native_sha256": base["compiled_native_sha256"],
                "field_authority": False,
                "parent_revalidated": False,
                "source_revalidated": False,
                "current_device_verified": False,
            },
        }
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        OverflowError,
        struct.error,
        UnicodeError,
    ):
        return unavailable
